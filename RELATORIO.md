# Material para o relatório: NetSentinel

Este documento reúne todas as informações necessárias para escrever o relatório do trabalho:
contexto teórico, arquitetura, decisões de projeto, testes realizados com evidências reais,
limitações e referências. A seção 1 sugere uma estrutura; as demais trazem o conteúdo de cada parte.

---

## 1. Estrutura sugerida para o relatório

1. Introdução (problema, objetivo, visão geral da solução)
2. Fundamentação teórica (gerência de redes, FCAPS, modelo gerente-agente, agentes de IA, MCP)
3. Arquitetura da solução
4. Implementação (módulos, ferramentas, segurança)
5. Metodologia de testes
6. Resultados
7. Discussão: decisões de projeto, limitações e trabalhos futuros
8. Conclusão
9. Referências

---

## 2. Identificação

| Item | Valor |
|---|---|
| Disciplina | Gerência e Aplicações em Redes (UFRGS) |
| Título sugerido | NetSentinel: um agente de IA autônomo para gerência de falhas em redes |
| Linguagem | Python 3.10+ (testado com 3.13.3) |
| Plataforma de testes | Windows 11 |
| Motor de IA | Claude Code 2.1.285 em modo headless (`claude -p`), via assinatura Claude |
| Protocolo de ferramentas | MCP (Model Context Protocol), transporte stdio |
| Dependências | `mcp`, `requests`, `truststore` (ver `requirements.txt`) |
| Tamanho do código | cerca de 850 linhas de Python em 5 módulos, mais o prompt do agente (33 linhas) |

---

## 3. Introdução

### 3.1 Problema
Em uma rede, quando um serviço falha, o operador precisa descobrir **onde** está o problema antes de
corrigi-lo. A pergunta é se a falha está na resolução de nomes, na conectividade, no serviço ou na
aplicação. Para isso, ele executa uma sequência de testes (ping, DNS, porta, HTTP, traceroute),
interpreta os resultados e decide uma ação. Ferramentas de monitoramento tradicionais (Zabbix, Nagios,
PRTG) **detectam** a falha e geram o alerta, mas o **diagnóstico** e a **decisão** continuam manuais
ou dependem de regras fixas escritas previamente.

### 3.2 Objetivo
Desenvolver um **agente de IA autônomo** para gerência de falhas. Ao receber um alerta, ele deve:
1. decidir sozinho quais testes de rede executar;
2. identificar a camada e a causa provável da falha;
3. corrigir o problema quando for seguro;
4. registrar um relatório do incidente.

### 3.3 Visão geral da solução
Um **monitor** determinístico (sem IA) verifica periodicamente uma lista de alvos. Quando um alvo passa
de OK para FALHA, o monitor aciona o **agente de IA**. O agente é um modelo de linguagem (Claude)
executado pelo Claude Code em modo não interativo. Ele investiga usando ferramentas de rede expostas por um
**servidor MCP**, pode reiniciar serviços de um **laboratório local** e devolve um relatório em Markdown.
Depois disso, o monitor verifica de novo o alvo para confirmar se a correção funcionou.

---

## 4. Fundamentação teórica

### 4.1 Gerência de redes e o modelo FCAPS
O modelo FCAPS (ITU-T M.3400 / ISO) divide a gerência de redes em cinco áreas: **F**ault (falhas),
**C**onfiguration (configuração), **A**ccounting (contabilização), **P**erformance (desempenho) e
**S**ecurity (segurança). O NetSentinel atua principalmente em:
- **Gerência de falhas**: detecção (monitor), diagnóstico (agente) e recuperação (reinício de serviço);
- **Gerência de desempenho**: detecção de lentidão por limiar de tempo de resposta (`slow_threshold_ms`).

### 4.2 Modelo gerente-agente
Na gerência clássica (por exemplo, SNMP), o **gerente** (NMS) consulta **agentes** instalados nos
dispositivos, que expõem informações descritas numa **MIB** e podem enviar notificações (traps).
No NetSentinel há um paralelo:

| Gerência clássica (SNMP) | NetSentinel |
|---|---|
| Gerente (NMS) faz polling dos dispositivos | `monitor.py` faz polling dos alvos a cada 10 s |
| Trap / notificação de evento | Transição OK → FAIL dispara o agente |
| Operador humano interpreta e age | Agente de IA interpreta e age |
| MIB descreve os objetos gerenciáveis | Esquema das ferramentas MCP descreve as ações disponíveis |
| `SET` altera o estado do dispositivo | `restart_service` altera o estado do serviço |

### 4.3 Diagnóstico por camadas
O agente segue a abordagem *bottom-up* do modelo TCP/IP:

| Camada | Pergunta | Ferramenta |
|---|---|---|
| Aplicação (nomes) | O nome resolve para um IP? | `dns_lookup` (DNS, RFC 1034/1035) |
| Rede | O host é alcançável? | `ping` (ICMP Echo, RFC 792), `traceroute` |
| Transporte | A porta aceita conexões? | `check_port` (handshake TCP, RFC 9293) |
| Aplicação | O serviço responde corretamente e rápido? | `check_http` (HTTP, RFC 9110) |

O resultado de `check_port` permite separar casos:
- **closed** (*connection refused*, TCP RST): o host está ativo, mas nenhum processo escuta, então o serviço caiu;
- **timeout**: o pacote foi filtrado por firewall ou o host está inalcançável;
- **open**: o transporte está bem, e o problema, se existir, está na aplicação.

### 4.4 Agentes de IA e uso de ferramentas (*tool use*)
Um **agente de IA** é um sistema em que um modelo de linguagem (LLM) decide, em ciclo, qual ação
executar, observa o resultado e decide a próxima ação, até concluir a tarefa. O modelo não executa nada
diretamente: ele **solicita** a chamada de uma ferramenta (nome + argumentos) e o ambiente a executa,
devolvendo o resultado. A diferença em relação a um script de regras fixas é que a **sequência de testes
não é programada**: o modelo escolhe os testes conforme as evidências. Por exemplo, ele não roda `ping`
em um domínio que nem resolve.

### 4.5 MCP (Model Context Protocol)
O MCP é um protocolo aberto que padroniza como aplicações de IA descobrem e chamam ferramentas externas.
Um **servidor MCP** anuncia suas ferramentas (nome, descrição e esquema JSON dos parâmetros), e um
**cliente MCP** (aqui, o Claude Code) as disponibiliza ao modelo. A comunicação usa JSON-RPC 2.0;
no NetSentinel, o transporte é **stdio** (o Claude Code inicia o servidor como subprocesso).
O papel do MCP lembra o de MIB + SNMP: é um contrato padronizado entre quem decide e quem expõe as operações.

---

## 5. Arquitetura

```
 targets.json ──► monitor.py (polling sem IA, a cada 10 s)
                     │ transição OK → FAIL
                     ▼
                agent.py ──subprocess──► claude -p (Claude Code, assinatura)
                     ▲                        │ chamadas de ferramenta via MCP (stdio)
                     │ relatório (Markdown)    ▼
                     │                  mcp_server.py ──► net_tools.py
                     │                                    ping, dns_lookup, check_port,
          reports/<data>_<alvo>.md                       check_http, traceroute, restart_service
                                                                 │ comando via TCP 127.0.0.1:8099
                                                                 ▼
                                                      lab.py (controlador do laboratório)
                                                      web :8080 (HTTP) · db :6543 (TCP)
```

### 5.1 Fluxo de um incidente
1. O monitor verifica cada alvo de `targets.json` (HTTP, TCP ou ping).
2. Se um alvo que estava OK falha, o monitor gera um alerta com a descrição da falha.
3. O `agent.py` monta a mensagem do alerta (alvo, erro observado, se é serviço do laboratório) e executa
   o `claude -p`, enviando o alerta pela entrada padrão.
4. O Claude Code inicia o servidor MCP e o modelo chama as ferramentas que achar necessárias.
5. Cada chamada e cada resultado aparecem no console em tempo real (eventos `stream-json`).
6. O modelo escreve o relatório final, e o `agent.py` o devolve ao monitor.
7. O monitor verifica o alvo novamente, anexa o resultado ao relatório e salva em `reports/`.

### 5.2 Módulos

| Arquivo | Linhas | Responsabilidade |
|---|---|---|
| `monitor.py` | 124 | Loop de polling, painel `[OK]`/`[FAIL]`, disparo na transição, verificação pós-ação |
| `agent.py` | 210 | Execução do Claude Code headless, leitura do stream JSON, timeout, gravação do relatório |
| `agent_prompt.md` | 33 | Prompt de sistema: método de diagnóstico, política de remediação, formato do relatório |
| `net_tools.py` | 218 | Ferramentas de rede (funções Python puras, retornam JSON com a chave `ok`) |
| `mcp_server.py` | 16 | Registra as funções de `net_tools.py` como ferramentas MCP (`FastMCP`) |
| `lab.py` | 280 | Controlador do laboratório: serviços falsos e porta de controle |
| `targets.json` | — | Alvos monitorados |

---

## 6. Implementação

### 6.1 Ferramentas de rede (`net_tools.py`)

| Ferramenta | Implementação | Retorno |
|---|---|---|
| `ping(host)` | `ping -n 4` (Windows) / `ping -c 4` (Linux), conta as linhas com "TTL" (independe do idioma do SO) | `loss_pct`, `latency_ms` |
| `dns_lookup(name)` | `socket.getaddrinfo` (resolvedor do sistema) | `addresses`, `time_ms` |
| `check_port(host, port)` | `socket.create_connection`, timeout de 3 s | `state`: `open`/`closed`/`timeout`/`error` |
| `check_http(url)` | `requests.get`, timeout de 10 s, certificados do SO via `truststore` | `status`, `time_ms` |
| `traceroute(host)` | `tracert -d -h 10 -w 500` / `traceroute -n -m 10` | saída dos saltos |
| `restart_service(name)` | Pede ao controlador do laboratório para reiniciar o serviço; só aceita `web` e `db` | `state`, `port` |

As **docstrings** de cada função são publicadas pelo MCP como descrição da ferramenta. São elas que o
modelo lê para escolher qual usar (por exemplo, "use traceroute somente quando o ping falhar").

### 6.2 Monitor (`monitor.py`)
- Tipos de alvo: `http` (falha se houver erro, status ≥ 400 ou tempo acima de `slow_threshold_ms`, padrão de
  2000 ms), `tcp` (porta fechada ou sem resposta) e `ping` (sem respostas).
- **Disparo por transição:** o agente só é acionado quando o alvo passa de OK para FAIL. Assim o modelo
  não é chamado a cada ciclo para o mesmo problema, o que economiza o limite de uso e evita ações repetidas.
- `targets.json` é relido a cada ciclo, então alvos podem ser ativados ou desativados sem reiniciar o monitor.
- Opções: `--once`, `--no-agent`, `--interval N`.

### 6.3 Agente (`agent.py` + `agent_prompt.md`)
Comando executado:
```
claude -p --mcp-config .netsentinel/mcp_config.json --strict-mcp-config --tools "" \
  --allowedTools mcp__netsentinel --permission-mode dontAsk \
  --append-system-prompt-file agent_prompt.md --output-format stream-json --verbose \
  --no-session-persistence
```
- O prompt de sistema define o método (camada por camada, mínimo de chamadas), a **política de
  remediação** (só reiniciar serviço do laboratório que esteja fora do ar e nunca reiniciar por lentidão) e o formato
  do relatório (em português: Resumo, Evidências, Causa provável, Ação tomada, Recomendação).
- O alerta vai pela entrada padrão para não ser confundido com opções da linha de comando.
- Timeout de 180 s por investigação. Erros (CLI ausente, sem login, sem resposta) geram `AgentError`.

### 6.4 Segurança: princípio do menor privilégio
| Mecanismo | Efeito |
|---|---|
| `--tools ""` | Desliga todas as ferramentas nativas do Claude Code (shell, leitura e escrita de arquivos) |
| `--strict-mcp-config` | Carrega só o servidor MCP do projeto, ignorando outras configurações do usuário |
| `--allowedTools mcp__netsentinel` + `--permission-mode dontAsk` | Só as ferramentas do NetSentinel são permitidas; qualquer outra é negada sem perguntar |
| Lista fixa em `restart_service` | Mesmo que o modelo tente, só os serviços `web` e `db` podem ser reiniciados |
| Validação de host (regex) | Impede injeção de opções nos comandos `ping`/`tracert` (ex.: host começando com `-`) |
| `subprocess` sem shell | Argumentos passados como lista, sem interpretação por shell |
| Remoção de `ANTHROPIC_API_KEY` do ambiente | Garante o uso da assinatura e evita cobrança na API |

### 6.5 Laboratório (`lab.py`)
- `web`: servidor HTTP (`http.server`) em 127.0.0.1:8080. No modo *slow*, cada resposta atrasa 5 s.
- `db`: servidor TCP em 127.0.0.1:6543, que envia uma linha de saudação e fecha a conexão.
- Os serviços rodam **dentro de um processo controlador** (`python lab.py run`), que recebe comandos JSON
  numa porta de controle local (127.0.0.1:8099) e registra no console quem executou cada ação
  (`by cli` / `by agent`).

---

## 7. Decisões de projeto e justificativas

| Decisão | Alternativas consideradas | Justificativa |
|---|---|---|
| Agente de IA em vez de agente SNMP | Agente SNMP com MIB própria | O objetivo era um agente que **decide e age sozinho**, não só que expõe dados |
| Claude Code headless (`claude -p`) | API da Anthropic com SDK; Claude Agent SDK; modelo local (Ollama) | Usa a assinatura existente, **sem custo adicional**. A API cobra por token, e o Agent SDK exige chave de API pela política da Anthropic. Modelos locais são menos confiáveis no uso de ferramentas |
| Ferramentas via MCP | Deixar o modelo usar o shell (Bash) | O MCP permite expor **só** as operações desejadas, com descrição e esquema, e é um protocolo padronizado |
| Monitor sem IA + agente só em incidentes | Agente rodando em loop o tempo todo | O polling determinístico é barato e previsível; a IA, mais lenta e limitada por cota, fica para o diagnóstico |
| Disparo só na transição OK → FAIL | Disparar a cada ciclo com falha | Evita investigações e ações repetidas para o mesmo incidente |
| Laboratório com serviços falsos | Derrubar serviços reais da máquina | Demonstração previsível, segura e reproduzível em qualquer PC |
| Controlador do laboratório em processo próprio | Serviços como processos independentes iniciados pela ferramenta | **Problema encontrado nos testes:** o Claude Code encerra toda a árvore de processos ao terminar, então o serviço reiniciado pelo agente morria junto. Com o controlador, o agente só envia um comando, e o serviço vive num processo iniciado pelo usuário |
| Porta 6543 para o `db` | Porta 9000 (escolha inicial) | **Problema encontrado nos testes:** a 9000 caía numa faixa reservada pelo Windows (Hyper-V/WSL), `WinError 10013` |
| `truststore` | Desativar a verificação TLS | **Problema encontrado nos testes:** o certificado de `www.ufrgs.br` falhava no Python (cadeia incompleta para o repositório `certifi`). O `truststore` usa os certificados do SO, como o navegador, sem abrir mão da segurança |
| Relatórios em português, código em inglês | — | Código seguindo a convenção usual; relatório legível para a apresentação |

---

## 8. Metodologia de testes

**Ambiente:** Windows 11, Python 3.13.3 em ambiente virtual, Claude Code 2.1.285 com o modelo padrão da
conta. Os alvos foram os dois serviços do laboratório (`web-lab`, `db-lab`), o DNS do Google (`8.8.8.8`,
ping), o site da UFRGS (HTTPS, limiar de 5000 ms) e um domínio inexistente (`broken-dns`, ativado só no cenário 3).

**Procedimento:** com o laboratório e o monitor rodando, cada falha foi provocada por um comando, e
foram observados:
1. a detecção pelo monitor;
2. a sequência de ferramentas escolhida pelo agente;
3. a ação tomada;
4. a verificação do monitor depois da ação.

**Testes sem IA** (validação das ferramentas):
- `ping` em 8.8.8.8 e 127.0.0.1;
- `dns_lookup` de um nome válido e de um inexistente;
- `check_port` em porta aberta e fechada;
- `check_http` normal e no modo lento;
- `restart_service` com um nome fora da lista (rejeitado);
- `ping` com argumento malicioso (`-n 1 x`, rejeitado pela validação).

O passo a passo para reproduzir está em `TUTORIAL.md`.

---

## 9. Resultados

### 9.1 Resumo

| # | Cenário | Falha provocada | Ferramentas chamadas pelo agente | Diagnóstico | Ação | Verificação | Tempo* |
|---|---|---|---|---|---|---|---|
| 1 | Serviço caiu | `lab.py stop web` | `check_port` → `restart_service` → `check_http` | Serviço parado (porta fechada) | Reiniciou `web` | **OK** (HTTP 200) | ~35 s |
| 1b | Serviço caiu (TCP) | `lab.py stop db` | `check_port` → `restart_service` → `check_port` | Serviço parado (porta fechada) | Reiniciou `db` | **OK** (porta aberta) | ~34 s |
| 2 | Lentidão | `lab.py slow` | `check_port` → `check_http` | Problema na aplicação (porta ok, HTTP 200 em ~5 s) | **Nenhuma** (correto: política proíbe reiniciar por lentidão) | Continua lento (esperado) | ~33 s |
| 3 | DNS | domínio inexistente | `dns_lookup` (alvo) ‖ `dns_lookup` (controle: www.ufrgs.br) | Falha de resolução do nome; resolvedor funcionando | **Nenhuma** (não é serviço do laboratório) | Continua falhando (esperado) | ~19 s |

\* Do início do ciclo de verificação até o relatório salvo, incluindo cerca de 5 s das verificações do próprio
monitor (o ping usa 4 pacotes) e o tempo de inicialização do Claude Code e do servidor MCP.
‖ = chamadas feitas em paralelo pelo modelo.

### 9.2 Observações relevantes para a discussão
- **Escolha adaptativa dos testes:** o agente não executou ping nem DNS para alvos em 127.0.0.1 e justificou
  isso no relatório ("o alvo é IP de loopback e a conexão foi recusada, não expirou"). No cenário 3, não
  testou porta nem HTTP porque "sem endereço IP não há onde testar".
- **Teste de controle espontâneo:** no cenário 3, o agente resolveu por conta própria um segundo domínio
  (www.ufrgs.br) para separar "resolvedor quebrado" de "nome inexistente". Isso não estava no prompt.
- **Respeito à política:** no cenário 2, o agente explicou por que **não** reiniciou: "a política só
  permite reiniciar quando o serviço está fora do ar".
- **Confirmação da ação:** depois de reiniciar, o agente sempre conferiu a recuperação (`check_http` ou `check_port`),
  e o monitor confirmou de forma independente.
- **Paralelismo:** no cenário 3, o modelo pediu as duas consultas DNS na mesma etapa.

### 9.3 Exemplos de relatórios gerados
Os relatórios completos dos testes estão em `examples/` (cópias da pasta `reports/`, que não vai para o git). Trecho do cenário 1:

> **Causa provável:** o processo do servidor HTTP não estava em execução. A falha está na camada de transporte/serviço:
> o host responde, mas nada escuta na porta 8080. Não é um problema de DNS nem de conectividade, porque o alvo é um IP de loopback e o host recusou a conexão ativamente.
>
> **Ação tomada:** reiniciei o serviço `web` com `restart_service`. Isso era seguro: o alvo é um serviço de laboratório e estava fora do ar (porta fechada).
> Depois confirmei a recuperação com `check_http`, que retornou HTTP 200 em 11 ms.

### 9.4 Problemas encontrados durante o desenvolvimento
1. **Serviço reiniciado morria ao fim da investigação:** no primeiro teste, o agente reiniciou o `web`
   corretamente, mas a verificação do monitor falhou. O Claude Code encerra a árvore de processos ao
   terminar, e o serviço era filho do servidor MCP. Para resolver, o laboratório virou um controlador
   em processo próprio (seção 7).
2. **Porta reservada pelo Windows:** a 9000 está numa faixa de exclusão do Hyper-V (`WinError 10013`).
   Para resolver, o `db` foi para a porta 6543.
3. **Certificado TLS da UFRGS:** `CERTIFICATE_VERIFY_FAILED` no Python, embora o `curl` (que usa o repositório
   do Windows) funcionasse. Para resolver, foi adotado o `truststore`.
4. **Formato do retorno MCP:** o `FastMCP` encapsula strings como `{"result": "..."}`, o que fazia o
   console exibir `FAIL` em resultados bem-sucedidos. Para resolver, o `agent.py` desfaz o encapsulamento antes de exibir.

---

## 10. Limitações

- **Não determinismo:** o texto e, às vezes, a sequência de ferramentas variam entre execuções.
  A política de remediação é reforçada pela lista fixa no código, mas a qualidade do diagnóstico depende do modelo.
- **Latência:** cerca de 20 a 30 s por investigação. Adequado para gerência de falhas, inadequado para reação em tempo real.
- **Dependência externa:** é preciso internet, conta com assinatura Claude e respeito ao limite de uso; sem isso,
  o sistema degrada para monitoramento simples (`--no-agent`).
- **Remediação limitada:** a única ação corretiva é reiniciar serviços do laboratório. Não há ações em
  equipamentos reais (roteadores, switches), por segurança.
- **Escopo das verificações:** não há SNMP, consulta de logs nem métricas de CPU/memória. O agente vê só o que
  as ferramentas expõem.
- **Polling único e local:** um único monitor, sem redundância nem pontos de observação distribuídos.
- **Testes em uma plataforma:** os testes foram no Windows 11. O código trata Linux e macOS (`ping -c`,
  `traceroute`), mas esses sistemas não foram testados.

## 11. Trabalhos futuros

- Novas ferramentas: consulta SNMP (`snmpget`) a equipamentos, leitura de logs, métricas do host,
  verificação de certificado TLS (validade/expiração).
- Notificação de incidentes (e-mail, Telegram, Slack).
- Alertas por desempenho com histórico (média móvel em vez de limiar fixo).
- Aprovação humana antes de ações de risco (*human-in-the-loop*).
- Correlação de incidentes: vários alvos falhando ao mesmo tempo indicam uma causa comum (ex.: queda do enlace).
- Avaliação quantitativa: bateria de cenários repetida N vezes, medindo a taxa de diagnósticos corretos.

---

## 12. Conclusão (pontos para desenvolver)

- O NetSentinel automatiza o ciclo completo de gerência de falhas: detecção, diagnóstico, correção e registro.
- O uso de um LLM permite um diagnóstico **adaptativo**: a sequência de testes não é programada, e sim
  escolhida pelas evidências, como faria um operador.
- Dividir os papéis entre um **monitor determinístico** e um **agente sob demanda** une o custo baixo e a
  previsibilidade do monitoramento tradicional à flexibilidade da IA.
- O MCP e as restrições do Claude Code permitem dar autonomia ao agente com **menor privilégio**: ele
  decide o que fazer, mas só pode fazer o que foi explicitamente exposto.
- Os quatro cenários testados produziram diagnósticos corretos. Isso inclui um caso em que a decisão certa era **não agir**.

---

## 13. Referências

- ITU-T Recommendation M.3400: *TMN management functions* (modelo FCAPS).
- RFC 3411: *An Architecture for Describing SNMP Management Frameworks*.
- RFC 792: *Internet Control Message Protocol* (ICMP).
- RFC 1034 / RFC 1035: *Domain Names: Concepts and Facilities* / *Implementation and Specification* (DNS).
- RFC 9293: *Transmission Control Protocol* (TCP).
- RFC 9110: *HTTP Semantics*.
- Model Context Protocol: especificação. https://modelcontextprotocol.io
- Claude Code: modo headless. https://code.claude.com/docs/en/headless
- Claude Code: referência da CLI. https://code.claude.com/docs/en/cli-reference
- Claude Agent SDK: visão geral (política de autenticação). https://code.claude.com/docs/en/agent-sdk/overview
- KUROSE, J.; ROSS, K. *Redes de Computadores e a Internet: uma abordagem top-down*. Pearson.

---

## 14. Sugestões de figuras para o relatório

1. **Diagrama de arquitetura** (seção 5): pode ser redesenhado a partir do diagrama ASCII.
2. **Diagrama de sequência de um incidente:** monitor → agent.py → Claude Code → MCP → net_tools → lab.
3. **Capturas de tela dos 3 terminais** em cada cenário: laboratório (log `by agent`), monitor (chamadas
   de ferramenta ao vivo) e sabotador.
4. **Tabela de resultados** (seção 9.1).
5. **Trecho de um relatório gerado** (pasta `examples/`).
