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
| Modelo padrão | Claude Sonnet (`sonnet` → `claude-sonnet-5-5`), configurável por `NETSENTINEL_MODEL` |
| Modelos testados | Claude Sonnet 5.5, Claude Haiku 4.5 e Claude Opus 5.5 |
| Protocolo de ferramentas | MCP (Model Context Protocol), transporte stdio |
| Dependências | `mcp`, `requests`, `truststore` (ver `requirements.txt`) |
| Tamanho do código | cerca de 1150 linhas de Python em 8 módulos, mais o prompt do agente (36 linhas) |

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

As mensagens seguem o JSON-RPC 2.0:

| Tipo | Campos | Exemplo no NetSentinel |
|---|---|---|
| Requisição | `id`, `method`, `params` | `{"id": 4, "method": "tools/call", "params": {"name": "check_port", ...}}` |
| Resposta | `id`, `result` ou `error` | `{"id": 4, "result": {"content": [{"type": "text", "text": "{\"ok\": false, ...}"}]}}` |
| Notificação | `method`, sem `id` | `{"method": "notifications/initialized"}` (não espera resposta) |

Uma sessão MCP tem três fases:
1. **inicialização**: `initialize` negocia a versão do protocolo e as capacidades;
2. **descoberta**: `tools/list` devolve o catálogo de ferramentas;
3. **uso**: `tools/call` executa uma ferramenta.

Comparando com o SNMP: `tools/list` faz um papel parecido com a leitura da MIB, e `tools/call`, com um `GET`/`SET`.

---

## 5. Arquitetura

```
 targets.json ──► monitor.py (polling sem IA, a cada 10 s)
                     │ transição OK → FAIL
                     ▼
                agent.py ──subprocess──► claude -p (Claude Code, assinatura)
                     ▲                        │ MCP: JSON-RPC 2.0 sobre stdio
                     │ relatório (Markdown)    ▼
                     │                  mcp_tap.py (proxy) ──► .netsentinel/mcp_trace.jsonl ──► mcp_view.py (console)
                     │                        │ repassa as mensagens sem alterar
                     │                        ▼
                     │                  mcp_server.py ──► net_tools.py
                     │                                    ping, dns_lookup, check_port,
          reports/<data>_<alvo>.md                       check_http, traceroute, restart_service
                                                                 │ comando via TCP 127.0.0.1:8099
                                                                 ▼
                                                      lab.py (controlador do laboratório)
                                                      web :8080 (HTTP) · db :6543 (TCP)
```

### 5.1 Fluxo de um incidente
1. O monitor verifica cada alvo de `config/targets.json` (HTTP, TCP ou ping).
2. Se um alvo que estava OK falha, o monitor gera um alerta com a descrição da falha.
3. O `agent.py` monta a mensagem do alerta (alvo, erro observado, se é serviço do laboratório) e executa
   o `claude -p`, enviando o alerta pela entrada padrão.
4. O Claude Code inicia o servidor MCP (através do proxy `mcp_tap.py`), negocia o protocolo
   (`initialize`), obtém o catálogo (`tools/list`), e o modelo chama as ferramentas que achar necessárias
   (`tools/call`).
5. Cada decisão do modelo (`[LLM]`) e cada mensagem MCP (`[MCP]`) aparecem no console em tempo real.
6. O modelo escreve o relatório final, e o `agent.py` o devolve ao monitor.
7. O monitor verifica o alvo novamente, anexa o resultado ao relatório e salva em `reports/`.

### 5.2 Módulos

| Arquivo | Linhas | Responsabilidade |
|---|---|---|
| `src/monitor.py` | 128 | Loop de polling, painel `[OK]`/`[FAIL]`, disparo na transição, verificação pós-ação |
| `src/agent.py` | 207 | Execução do Claude Code headless, leitura do stream JSON, timeout, gravação do relatório |
| `src/agent_prompt.md` | 36 | Prompt de sistema: método de diagnóstico, política de remediação, formato do relatório |
| `src/net_tools.py` | 233 | Ferramentas de rede (funções Python puras, retornam JSON com a chave `ok`); também roda pela linha de comando |
| `src/mcp_server.py` | 16 | Registra as funções de `net_tools.py` como ferramentas MCP (`FastMCP`) |
| `src/mcp_tap.py` | 71 | Proxy stdio entre o Claude Code e o servidor MCP; grava cada mensagem JSON-RPC |
| `src/mcp_view.py` | 127 | Exibe ao vivo, no console do monitor, as mensagens gravadas pelo proxy (resumidas ou completas) |
| `src/lab.py` | 313 | Controlador do laboratório: serviços falsos, porta de controle e cenário de DNS |
| `src/paths.py` | 15 | Caminhos do projeto compartilhados pelos módulos |
| `config/targets.json` | — | Alvos monitorados |

### 5.3 Organização do repositório
```
README.md              visão geral, instalação e comandos
requirements.txt       dependências (mcp, requests, truststore)
config/targets.json    alvos monitorados
src/                   código-fonte
docs/                  plano, tutorial, este material e exemplos de relatórios por modelo
reports/               relatórios gerados em execução (fora do controle de versão)
```

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
- `config/targets.json` é relido a cada ciclo, então alvos podem ser ativados ou desativados sem reiniciar o monitor.
- Opções: `--once`, `--no-agent`, `--interval N`.

### 6.3 Agente (`agent.py` + `agent_prompt.md`)
Comando executado:
```
claude -p --mcp-config .netsentinel/mcp_config.json --strict-mcp-config --tools "" \
  --allowedTools mcp__netsentinel --permission-mode dontAsk \
  --append-system-prompt-file src/agent_prompt.md --output-format stream-json --verbose \
  --no-session-persistence --model sonnet
```
- O prompt de sistema define o método (camada por camada, mínimo de chamadas), a **política de
  remediação** (só reiniciar serviço do laboratório que esteja fora do ar e nunca reiniciar por lentidão) e o formato
  do relatório (em português: Resumo, Evidências, Causa provável, Ação tomada, Recomendação).
- O alerta vai pela entrada padrão para não ser confundido com opções da linha de comando.
- Timeout de 180 s por investigação. Erros (CLI ausente, sem login, sem resposta) geram `AgentError`.
- O modelo é escolhido por `--model` (padrão `sonnet`; a variável `NETSENTINEL_MODEL` permite `haiku` ou
  `opus`). O modelo efetivamente usado é lido do evento inicial do stream e exibido no console.
- No prompt foram incluídas duas regras depois dos testes com o Haiku (seção 9.5): começar o relatório
  direto em "Resumo" e, quando um nome não resolve, consultar um domínio conhecido como controle.

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
- Os serviços rodam **dentro de um processo controlador** (`python src/lab.py run`), que recebe comandos JSON
  numa porta de controle local (127.0.0.1:8099) e registra no console quem executou cada ação
  (`by cli` / `by agent`).
- Cenário de DNS: `python src/lab.py dns-fail` ativa em `config/targets.json` um alvo cujo domínio não
  existe (`netsentinel-nonexistent-domain.xyz`) e `dns-ok` o desativa. Como o monitor relê o arquivo a
  cada ciclo e esquece o estado de alvos desativados, cada reativação gera um novo incidente.
- Todos os cenários são provocados pelo terminal: `stop web`/`stop db`, `slow`, `dns-fail`.

---

### 6.6 Observabilidade da comunicação agente ↔ MCP
Para que a comunicação entre o agente e o servidor MCP possa ser vista e analisada, o Claude Code não
inicia o servidor diretamente. Ele inicia o `mcp_tap.py`, um **proxy transparente** que:
1. inicia o servidor MCP real (`mcp_server.py`) como subprocesso;
2. repassa, sem alterar, cada linha (mensagem JSON-RPC) do cliente para o servidor e vice-versa;
3. grava uma cópia de cada mensagem, com horário e direção, em `.netsentinel/mcp_trace.jsonl`.

Enquanto o agente trabalha, o `mcp_view.py` lê esse arquivo e imprime cada mensagem no monitor. O
console intercala duas camadas:
- **`[LLM]`:** a decisão do modelo, lida do stream do Claude Code;
- **`[MCP]`:** a mensagem que efetivamente trafegou no protocolo.

Ao final, o registro é salvo em `reports/<data>_<alvo>_mcp.jsonl`. A opção `--mcp-trace` do monitor
escolhe o formato: `compact` (padrão, uma linha resumida por mensagem), `raw` (JSON completo) ou `off`.

Trecho real (cenário 1):
```
[MCP] client → server  #0 initialize       protocol 2025-11-25, client claude-code 2.1.300
[MCP] server → client  #0 result           server netsentinel 1.30.0, capabilities: experimental, prompts, resources, tools
[MCP] client → server     notifications/initialized
[MCP] client → server  #1 tools/list
[MCP] server → client  #1 result           6 tools: ping, dns_lookup, check_port, check_http, traceroute, restart_service
[LLM] decides to call check_port('127.0.0.1', 8080)
[MCP] client → server  #4 tools/call       check_port {"host": "127.0.0.1", "port": 8080}
[MCP] server → client  #4 result           {"ok": false, "host": "127.0.0.1", "port": 8080, "state": "closed", "error": "connection refused"}
[LLM] decides to call restart_service('web')
[MCP] client → server  #6 tools/call       restart_service {"name": "web"}
[MCP] server → client  #6 result           {"ok": true, "name": "web", "state": "running", "port": 8080}
```
O registro completo dessa investigação (19 mensagens) está em `docs/examples/mcp-trace/`.

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
| Proxy (`mcp_tap.py`) para mostrar a comunicação MCP | Logs dentro do servidor MCP; modo debug do Claude Code | O proxy mostra as mensagens **exatamente como trafegam** no protocolo, nos dois sentidos, sem alterar o servidor nem depender de recursos internos do Claude Code. Também serviria para qualquer outro servidor MCP |
| Sonnet como modelo padrão | Haiku (mais econômico), Opus (mais capaz) | Os três resolveram todos os cenários (seção 9.2). O Sonnet foi o mais rápido e seguiu o formato e a política sem ajustes; o Haiku precisou de duas regras extras no prompt; o Opus é o que mais consome o limite da assinatura |

---

## 8. Metodologia de testes

**Ambiente:** Windows 11, Python 3.13.3 em ambiente virtual, Claude Code 2.1.285. Os quatro cenários
foram executados com três modelos: Claude Opus 5.5, Claude Haiku 4.5 e Claude Sonnet 5.5. Os alvos foram os dois serviços do laboratório (`web-lab`, `db-lab`), o DNS do Google (`8.8.8.8`,
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

O passo a passo para reproduzir está em `docs/TUTORIAL.md`.

---

## 9. Resultados

### 9.1 Resumo (modelo padrão: Claude Sonnet 5.5)

| # | Cenário | Falha provocada | Ferramentas chamadas pelo agente | Diagnóstico | Ação | Verificação | Tempo* |
|---|---|---|---|---|---|---|---|
| 1 | Serviço caiu | `lab.py stop web` | `ping` ‖ `check_port` → `restart_service` → `check_http` | Serviço parado (host ok, porta fechada) | Reiniciou `web` | **OK** (HTTP 200) | ~25 s |
| 1b | Serviço caiu (TCP) | `lab.py stop db` | `ping` ‖ `check_port` → `restart_service` → `check_port` | Serviço parado (host ok, porta fechada) | Reiniciou `db` | **OK** (porta aberta) | ~23 s |
| 2 | Lentidão | `lab.py slow` | `ping` ‖ `check_port` ‖ `check_http` | Problema na aplicação (porta ok, HTTP 200 em ~5 s) | **Nenhuma** (correto: política proíbe reiniciar por lentidão) | Continua lento (esperado) | ~39 s |
| 3 | DNS | `lab.py dns-fail` | `dns_lookup` (alvo) ‖ `dns_lookup` (controle: www.ufrgs.br) | Falha de resolução do nome; resolvedor funcionando | **Nenhuma** (não é serviço do laboratório) | Continua falhando (esperado) | ~16 s |

\* Do início do ciclo de verificação até o relatório salvo, incluindo cerca de 5 s das verificações do próprio
monitor (o ping usa 4 pacotes; no cenário 2, cada HTTP leva 5 s) e o tempo de inicialização do Claude Code
e do servidor MCP.
‖ = chamadas feitas em paralelo pelo modelo.

### 9.2 Comparação entre modelos

Os mesmos quatro cenários foram executados com cada modelo. Todos chegaram ao diagnóstico correto e
tomaram a ação correta (reiniciar só nos cenários 1 e 1b).

| Cenário | Opus 5.5 | Haiku 4.5 | Sonnet 5.5 (padrão) |
|---|---|---|---|
| 1. web caiu | ✅ ~35 s · 3 chamadas | ✅ ~28 s · 5 chamadas | ✅ ~25 s · 4 chamadas |
| 1b. db caiu | ✅ ~34 s · 3 chamadas | ✅ ~32 s · 4 chamadas | ✅ ~23 s · 4 chamadas |
| 2. lentidão | ✅ ~33 s · 2 chamadas | ✅ ~44 s · 3 chamadas ⚠️ | ✅ ~39 s · 3 chamadas |
| 3. DNS | ✅ ~19 s · 2 chamadas | ✅ ~20 s · 1 chamada ⚠️ | ✅ ~16 s · 2 chamadas |

⚠️ Haiku, na primeira rodada (antes do ajuste no prompt):
- **cenário 2:** escreveu um texto introdutório antes das seções do relatório, fora do formato pedido;
- **cenário 3:** não fez a consulta de controle e afirmou que o domínio não existe sem verificar se o
  resolvedor funcionava (conclusão correta, evidência incompleta).

Depois de duas regras explícitas no prompt, o Haiku foi testado de novo nos cenários 2 e 3 e seguiu o
formato e fez a consulta de controle (com `google.com`).

**Diferenças de estilo:**
- **Opus:** o mais econômico em chamadas. Não usou `ping` em 127.0.0.1, justificando que a conexão
  recusada já prova que o host responde.
- **Sonnet e Haiku:** preferiram testar rede e porta em paralelo (`ping` ‖ `check_port`), uma chamada a
  mais que não altera o resultado.
- **Todos:** confirmaram a recuperação depois de reiniciar.

**Escolha do padrão:** o Sonnet ficou como padrão por ter sido o mais rápido e por seguir o formato e a
política sem ajustes. O Haiku é uma alternativa viável para economizar o limite da assinatura.

### 9.3 Observações relevantes para a discussão
- **Escolha adaptativa dos testes:** a sequência de ferramentas não é fixa. O Opus não executou ping
  para alvos em 127.0.0.1 e justificou isso ("o alvo é IP de loopback e a conexão foi recusada, não
  expirou"). No cenário 3, nenhum modelo testou porta nem HTTP, porque "sem endereço IP não há onde testar".
- **Teste de controle:** no cenário 3, o Opus resolveu por conta própria um segundo domínio (www.ufrgs.br)
  para separar "resolvedor quebrado" de "nome inexistente", sem que isso estivesse no prompt. Como o Haiku
  não fez o mesmo, a regra passou a ser explícita no prompt: um exemplo de como modelos menores precisam
  de instruções mais detalhadas.
- **Respeito à política:** no cenário 2, o agente explicou por que **não** reiniciou: "a política só
  permite reiniciar quando o serviço está fora do ar".
- **Confirmação da ação:** depois de reiniciar, o agente sempre conferiu a recuperação (`check_http` ou `check_port`),
  e o monitor confirmou de forma independente.
- **Paralelismo:** os modelos pedem várias ferramentas na mesma etapa (ex.: as duas consultas DNS do
  cenário 3, ou `ping`, `check_port` e `check_http` juntos no cenário 2). O registro MCP mostra que, mesmo
  assim, o Claude Code envia os `tools/call` ao servidor **um de cada vez**: a resposta `#4` chega antes
  da requisição `#5`.
- **Negociação de versão do MCP:** o registro mostrou que o Claude Code 2.1.300 tenta primeiro uma versão
  mais nova do protocolo (`server/discover`, 2026-07-28). O servidor, feito com a biblioteca `mcp` 1.30,
  responde com o erro `-32602`, e o cliente recua para o `initialize` com a versão `2025-11-25`. É a
  compatibilidade entre versões funcionando na prática.
- **Descoberta além das ferramentas:** depois de `initialize`, o cliente pede `tools/list`, `prompts/list`
  e `resources/list`. O servidor só oferece ferramentas (0 prompts, 0 resources).

### 9.4 Exemplos de relatórios gerados
Os relatórios completos dos testes estão em `docs/examples/`, separados por modelo (`sonnet-5.5/`,
`haiku-4.5/`, `opus-5.5/`), como cópias da pasta `reports/`, que não vai para o git. Trecho do cenário 1 (Opus):

> **Causa provável:** o processo do servidor HTTP não estava em execução. A falha está na camada de transporte/serviço:
> o host responde, mas nada escuta na porta 8080. Não é um problema de DNS nem de conectividade, porque o alvo é um IP de loopback e o host recusou a conexão ativamente.
>
> **Ação tomada:** reiniciei o serviço `web` com `restart_service`. Isso era seguro: o alvo é um serviço de laboratório e estava fora do ar (porta fechada).
> Depois confirmei a recuperação com `check_http`, que retornou HTTP 200 em 11 ms.

### 9.5 Problemas encontrados durante o desenvolvimento
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
5. **Haiku menos aderente ao prompt:** com o Haiku, um relatório veio com texto antes das seções e o
   diagnóstico de DNS veio sem consulta de controle. Para resolver, essas duas regras foram escritas
   explicitamente no prompt, e os cenários foram repetidos com sucesso.
6. **Cenário 3 exigia editar arquivo:** inicialmente, o alvo de DNS era ativado editando o
   `targets.json` à mão. Para que todos os cenários fossem controlados pelo terminal, foram criados os
   comandos `dns-fail`/`dns-ok`. Também foi corrigido o monitor, que não acionava o agente quando um alvo
   desativado era reativado (o estado antigo "FAIL" ficava guardado).

---

## 10. Limitações

- **Não determinismo:** o texto e, às vezes, a sequência de ferramentas variam entre execuções.
  A política de remediação é reforçada pela lista fixa no código, mas a qualidade do diagnóstico depende do
  modelo: modelos menores (Haiku) precisaram de instruções mais explícitas.
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
3. **Captura da comunicação MCP** no monitor (linhas `[LLM]` e `[MCP]`), com destaque para o par
   `tools/call` / `result` de mesmo `#id`; e um trecho do `_mcp.jsonl` com uma mensagem JSON-RPC completa.
4. **Capturas de tela dos 3 terminais** em cada cenário: laboratório (log `by agent`), monitor (chamadas
   de ferramenta ao vivo) e sabotador.
5. **Tabela de resultados** (seção 9.1) e **comparação entre modelos** (seção 9.2).
6. **Trecho de um relatório gerado** (pasta `docs/examples/`).
