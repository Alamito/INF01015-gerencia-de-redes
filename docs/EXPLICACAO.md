# NetSentinel: explicação técnica para a apresentação

Complemento visual: [`visual.html`](visual.html) (simulador interativo dos cenários).

## Em uma frase

Um **agente de IA autônomo de gerência de redes**. Um monitor comum (sem IA) verifica alvos periodicamente. Quando um alvo falha, ele aciona um LLM (Claude Code em modo headless) que investiga com ferramentas de rede, decide se pode corrigir, age e escreve um relatório de incidente.

Aqui "agente" significa agente de IA, que decide e age sozinho. Não é o agente SNMP do modelo gerente-agente clássico.

## Arquitetura

```
config/targets.json ──► monitor.py ──(OK → FAIL)──► agent.py ──► claude -p (assinatura)
                                                                    │ MCP (stdio)
                                                                    ▼
                                          lab.py ◄── net_tools.py ◄── mcp_server.py
```

São dois "cérebros" com papéis diferentes:

| Componente | Papel | Usa IA? |
|---|---|---|
| `monitor.py` | Polling a cada 10 s, detecta falhas | Não (determinístico, barato) |
| `agent.py` + LLM | Diagnostica, remedia e relata | Sim, só em incidentes |

**Por quê?** O polling é barato e previsível. A IA é lenta (cerca de 20 a 30 s) e limitada por cota, então só entra quando há problema.

## Fluxo de um incidente

1. O `monitor.py` carrega `targets.json` a cada ciclo. Isso permite ligar e desligar alvos com o monitor rodando.
2. Ele verifica cada alvo por tipo: `ping` (ICMP), `tcp` (abre a porta) ou `http` (GET com limiar de lentidão, padrão 2000 ms).
3. O agente só é acionado na **transição OK → FAIL** (`monitor.py:93`). Sem isso, cada ciclo com falha dispararia uma nova investigação.
4. O `agent.py` monta um alerta (alvo, erro, hora, se é serviço do lab) e o envia por **stdin** ao `claude -p`. Assim o texto não é confundido com opções da CLI.
5. O LLM chama as ferramentas via MCP, raciocinando camada por camada.
6. O relatório final em Markdown é salvo em `reports/`.
7. O monitor reverifica o alvo sozinho e anexa a seção "Verificação do monitor". Essa é uma confirmação independente: não depende do que o agente diz que fez.

## As ferramentas (`net_tools.py`)

São funções Python simples que retornam JSON com a chave `ok`. O `mcp_server.py` as expõe com `FastMCP`, em um loop sobre `ALL_TOOLS`.

| Ferramenta | Camada | O que faz |
|---|---|---|
| `dns_lookup` | Resolução de nomes | `socket.getaddrinfo` |
| `ping` | Rede (ICMP) | 4 pacotes; perda % e latência |
| `check_port` | Transporte (TCP) | Distingue `open`, `closed` (RST, serviço caiu), `timeout` (filtrado ou host fora) e `error` |
| `check_http` | Aplicação | Código de status e tempo de resposta |
| `traceroute` | Rede | Até 10 saltos, só se o ping falhar |
| `restart_service` | Remediação | Só aceita `web` e `db` |

Detalhes que vale citar:
- **Os docstrings são o contrato com a IA.** É o que o modelo lê para decidir qual ferramenta usar.
- O `ping` conta linhas com "TTL" em vez de ler o resumo, para funcionar em qualquer idioma do SO.
- O estado do `check_port` é informativo: `closed` indica serviço parado, e `timeout` indica problema de rede.
- A validação de host por regex (`HOST_PATTERN`) bloqueia injeção de argumentos. Exemplo: `-n 1 x` é rejeitado.
- O `truststore` usa os certificados do SO. Sem ele, `www.ufrgs.br` falhava por cadeia incompleta.

## Como o Claude Code é usado (`agent.py:39-51`)

```
claude -p --mcp-config ... --strict-mcp-config --tools ""
  --allowedTools mcp__netsentinel --permission-mode dontAsk
  --append-system-prompt-file agent_prompt.md --output-format stream-json
  --no-session-persistence --model sonnet
```

- **`-p`** é o modo headless, não interativo.
- **Sem API key.** O código remove `ANTHROPIC_API_KEY` do ambiente para usar a assinatura (Pro/Max) e não a API paga. O Agent SDK exigiria chave de API, por isso foi descartado.
- **`stream-json`** faz o console mostrar as chamadas de ferramenta ao vivo (`-> check_port(...)`, `<- ok {...}`).
- Há timeout de 180 s e uma thread que drena o stderr, para o pipe não travar.

## Segurança (menor privilégio)

Quatro camadas:
1. `--tools ""` remove todas as ferramentas nativas (shell, arquivos).
2. `--strict-mcp-config` permite só o nosso servidor MCP.
3. `--permission-mode dontAsk` não pergunta nada, porque o agente roda sem supervisão.
4. `restart_service` valida contra uma lista fixa no **código**, não só no prompt.

Esse último ponto responde a uma pergunta provável do professor: "e se o LLM errar?". A regra é imposta pelo código, e o prompt só orienta.

## O prompt do agente (`agent_prompt.md`)

- **Diagnóstico por camadas:** DNS, depois ping, depois porta, depois HTTP.
- **Teste de controle de DNS:** se um nome falha, resolve-se também um domínio conhecido. Isso separa "resolvedor quebrado" de "nome inexistente".
- **Política de remediação:** só reinicia se o alvo for serviço do lab **e** a porta estiver fechada. Nunca reinicia um serviço lento.
- **Formato fixo do relatório:** português, menos de 200 palavras, com as seções Resumo, Evidências, Causa provável, Ação tomada e Recomendação.

## O laboratório (`lab.py`)

Serve para simular incidentes de forma segura e reproduzível, sem derrubar serviços reais.

- Um **processo controlador** (`lab.py run`) hospeda dois serviços falsos: HTTP em `:8080` e TCP em `:6543`. Ele recebe comandos JSON numa porta de controle (`:8099`).
- O `net_tools.restart_service` só envia um comando a essa porta.
- **Por que um controlador separado?** Esse foi um problema real dos testes. O Claude Code encerra toda a árvore de processos ao terminar. Quando o serviço era filho do servidor MCP, ele morria junto com o agente. Com o controlador, o serviço vive num processo do usuário.

## Os cenários de demonstração

| # | Comando | Diagnóstico do agente | Ação |
|---|---|---|---|
| 1 | `lab.py stop web` | Host ok, porta fechada, então serviço parado | **Reinicia** e confirma com `check_http` |
| 2 | `lab.py slow` | Porta ok, HTTP 200 em ~5 s, então problema de aplicação | **Não reinicia** (a política proíbe) |
| 3 | `lab.py dns-fail` | Nome não resolve, mas o resolvedor funciona (controle) | Nenhuma (não é serviço do lab) |

O cenário 2 é o mais interessante para a banca. Ele mostra que o agente **sabe quando não agir**.

## Resultados

Os 4 cenários (os três acima mais `lab.py stop db`) foram testados com 3 modelos (Opus 5.5, Haiku 4.5 e Sonnet 5.5):
- **Todos acertaram** o diagnóstico e a ação.
- O Sonnet foi o mais rápido (16 a 39 s) e é o padrão.
- O Haiku errou na primeira rodada: escreveu texto fora do formato e pulou o teste de controle de DNS. Duas regras explícitas no prompt resolveram.
- O Opus gastou menos chamadas e dispensou o `ping` em loopback, justificando que conexão recusada já prova que o host responde.

Isso mostra que **a sequência de ferramentas é adaptativa, e não um script fixo**.

## Problemas reais que valem mencionar

1. O serviço reiniciado morria junto com o agente. A solução foi o controlador separado.
2. A porta 9000 está reservada pelo Hyper-V/WSL no Windows (`WinError 10013`), então o `db` foi para a 6543.
3. O certificado da UFRGS falhava no Python. Usou-se o `truststore`.
4. O `FastMCP` encapsula strings como `{"result": "..."}`, o que fazia o console mostrar `FAIL` em sucessos. O `agent.py` agora desfaz o encapsulamento.

## Limitações (para responder na banca)

- **Não determinismo:** o texto e, às vezes, a sequência de ferramentas variam entre execuções.
- **Latência de 20 a 30 s:** serve para gerência de falhas, não para reação em tempo real.
- **Dependência externa:** precisa de internet e de assinatura Claude. Sem isso, o sistema vira só monitor (`--no-agent`).
- **Remediação limitada:** só reinicia serviços do lab, sem ação em equipamentos reais.
- **Sem SNMP, logs ou métricas** de CPU e memória.
- **Testado só no Windows 11,** com dados de apenas uma rodada por cenário (sem avaliação estatística).

## Teoria de apoio (seção 4 do `RELATORIO.md`)

- **FCAPS:** o projeto cobre principalmente gerência de **falhas**.
- **Modelo OSI/TCP-IP:** o diagnóstico por camadas.
- **Tool use:** o LLM decide qual função chamar.
- **MCP (Model Context Protocol):** protocolo padrão que expõe só as operações desejadas, com descrição e esquema. A alternativa seria dar acesso ao shell, o que é bem mais perigoso.

## Possíveis perguntas da banca

- **"Por que não SNMP?"** O objetivo era um agente que decide e age, não só expõe dados. O SNMP é listado como trabalho futuro, como nova ferramenta.
- **"O que impede a IA de fazer algo perigoso?"** `--tools ""`, a lista fixa no código e a validação de host por regex.
- **"Por que o monitor não usa IA?"** Custo, latência e previsibilidade.
- **"Como sabem que a correção funcionou?"** O agente confirma, e o monitor reverifica de forma independente.
