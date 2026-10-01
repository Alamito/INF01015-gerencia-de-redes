# NetSentinel: agente de IA para monitoramento de rede
**Trabalho em grupo: Gerência e Aplicações em Redes (UFRGS)**

> **Padrão de código:** tudo em **inglês (en-US)**: nomes de arquivos, funções, variáveis, chaves JSON,
> comandos de CLI, comentários e mensagens do console. Só os **relatórios gerados pelo agente** saem em
> português, para facilitar a apresentação.

## 1. A ideia em 30 segundos
Um **agente de IA autônomo** que vigia serviços de rede. Quando algo cai, ele **investiga sozinho**
(ping, DNS, porta, HTTP, traceroute), **descobre a causa**, **tenta corrigir** e **escreve um relatório**.

```
[10:00] monitoring 4 targets...
[10:05] ALERT: web-lab (http://127.0.0.1:8080) is not responding
[agent] investigating...
  -> ping(127.0.0.1): ok, 0% loss
  -> check_port(127.0.0.1, 8080): closed
  -> restart_service(web): restarted
REPORT: host is up, but the web service on port 8080 went down.
Action: service restarted. Verification: OK.
```

**Por que esse projeto:** é pouco código (cerca de 850 linhas de Python), roda em qualquer PC com Python, sem VM
nem Docker, e a demo é previsível porque temos um mini-laboratório de serviços falsos que derrubamos na hora.

## 2. Tecnologias e custo (sem API key, sem pagar nada a mais)
- **Python 3.10+**
- **Claude Code em modo headless** (`claude -p`) como "cérebro" do agente. Ele usa a **assinatura do Claude
  (Pro/Max)** de quem está logado no Claude Code, então **não precisa de API key nem gera cobrança extra**,
  só consome o limite de uso da assinatura.
- **Modelo:** Claude Sonnet por padrão (`--model sonnet`). Haiku e Opus também foram testados e
  resolveram todos os cenários; a variável `NETSENTINEL_MODEL` troca o modelo.
- **MCP (Model Context Protocol)**: nossas ferramentas de rede viram um servidor MCP em Python
  (pacote `mcp`), e o Claude Code chama essas ferramentas.
- `requests` para os testes HTTP e `truststore` para validar certificados HTTPS com o repositório do
  sistema operacional. O resto é biblioteca padrão (`socket`, `subprocess`, `http.server`).
- Dependências em `requirements.txt`, instaladas num ambiente virtual (`.venv`).

**Quem precisa de quê:**
- Só **quem roda a parte de IA** (desenvolvimento do agente e a máquina da demo) precisa do Claude Code
  instalado e logado com uma assinatura. Os demais módulos são desenvolvidos e testados sem IA.
- **Não definir a variável `ANTHROPIC_API_KEY`**: se ela existir, o Claude Code passa a usar a API paga no lugar da assinatura.
- Usamos o **CLI** (`claude -p`), e **não** o *Claude Agent SDK*. Pela política da Anthropic, o Agent SDK
  exige API key e não pode usar o login da assinatura.
  ([docs](https://code.claude.com/docs/en/agent-sdk/overview), [headless](https://code.claude.com/docs/en/headless))

## 3. Arquitetura
```
 targets.json ──► monitor.py (loop sem IA, a cada 10 s)
                    │  detectou OK → FAIL
                    ▼
               agent.py ──subprocess──► claude -p  (Claude Code, assinatura)
                    ▲                        │ chama ferramentas via MCP
                    │ relatório               ▼
                    │                  mcp_server.py ──► net_tools.py
                    │                                   ping / dns_lookup / check_port /
          reports/<date>_<target>.md                   check_http / traceroute / restart_service
                                                                │
                                                                ▼
                                          lab.py (controlador dos serviços falsos)
```

### Estrutura de arquivos
```
netsentinel/
├── README.md              # how to install, run and test
├── requirements.txt       # mcp, requests, truststore
├── config/
│   └── targets.json       # monitored targets
├── src/
│   ├── monitor.py         # entry point: monitoring loop + triggers the agent
│   ├── agent.py           # runs `claude -p`, streams actions live, saves the report
│   ├── agent_prompt.md    # agent system prompt
│   ├── net_tools.py       # network checks (plain Python functions)
│   ├── mcp_server.py      # exposes net_tools.py functions as MCP tools
│   ├── lab.py             # lab controller: hosts the fake services, takes commands
│   └── paths.py           # project paths shared by the modules
├── docs/                  # plano, tutorial, material do relatório, exemplos por modelo
└── reports/               # reports written by the agent (not versioned)
```
A configuração MCP do Claude Code é gerada em tempo de execução pelo `agent.py`
(`.netsentinel/mcp_config.json`), apontando para o Python do `.venv`.

## 4. Componentes

| Componente | Arquivos | Como testar isoladamente |
|---|---|---|
| **Ferramentas de rede** | `net_tools.py` + `mcp_server.py` | `python src/net_tools.py ping 8.8.8.8` |
| **Laboratório** | `lab.py` + `config/targets.json` | `python src/lab.py run` e abrir http://127.0.0.1:8080 |
| **Agente de IA** | `agent.py` + `agent_prompt.md` | `python src/agent.py "<descrição do problema>"` |
| **Monitor** | `monitor.py` | `python src/monitor.py --once --no-agent` |

### Ferramentas de rede (`net_tools.py` + `mcp_server.py`)
- `net_tools.py` tem **funções Python puras**, sem nada de IA, que o monitor também usa:
  - `ping(host)`: `ping -n 4` (Windows) ou `-c 4` (Linux/Mac), detectar o SO com `platform.system()`
  - `dns_lookup(name)`: `socket.getaddrinfo`, retornar IPs e tempo
  - `check_port(host, port)`: `socket.create_connection` com timeout de 3 s
  - `check_http(url)`: `requests.get` com timeout de 10 s, retornar status e tempo
  - `traceroute(host)`: `tracert -d -h 10 -w 500` / `traceroute -n -m 10`, limitado para não demorar
  - `restart_service(name)`: **só aceita `web` e `db`** (lista fixa, por segurança) e chama `lab.restart(name)`
- `mcp_server.py` tem cerca de 15 linhas: cria um `FastMCP("netsentinel")` (pacote `mcp`), registra cada função
  com `mcp.tool()(net_tools.ping)` e chama `mcp.run()`.
  **A docstring de cada função vira a descrição que a IA lê**, então ela precisa ser clara (em inglês).

### Laboratório (`lab.py`)
- Serviço `web`: servidor HTTP na porta **8080** (`http.server`). No modo `slow`, cada resposta demora 5 s.
- Serviço `db`: servidor TCP na porta **6543** que só aceita conexões.
- Os serviços rodam dentro de um **processo controlador** (`python src/lab.py run`), que fica aberto num terminal
  e recebe comandos na porta local **8099**. Os comandos da CLI e o `restart_service` do agente só mandam
  ordens para ele. Isso é necessário porque o Claude Code encerra toda a árvore de processos ao terminar:
  um serviço iniciado diretamente pelo agente morreria junto. Bônus para a demo: o terminal do
  laboratório mostra quem fez cada ação (`web restarted (by agent)`).
- CLI: `python src/lab.py run|start|stop|slow|dns-fail|dns-ok|status [service]`
- `dns-fail`/`dns-ok` ligam e desligam o cenário de DNS (ativam/desativam em `config/targets.json` um alvo
  com domínio inexistente), para que todos os cenários sejam controlados pelo terminal.
- Montar o `config/targets.json` com os alvos do laboratório e 2 alvos reais (ex.: `8.8.8.8`, `https://www.ufrgs.br`)

### Agente de IA (`agent.py`)
- `agent.investigate(target, error)` monta a mensagem do alerta, envia pelo stdin e roda via `subprocess`:
  ```
  claude -p \
    --mcp-config .netsentinel/mcp_config.json --strict-mcp-config \
    --tools "" \
    --allowedTools "mcp__netsentinel" \
    --permission-mode dontAsk \
    --append-system-prompt-file agent_prompt.md \
    --output-format stream-json --verbose
  ```
  - `--strict-mcp-config` carrega só o nosso servidor MCP, e `--tools ""` desliga as ferramentas nativas.
  - `--allowedTools` + `--permission-mode dontAsk` fazem o agente **só poder usar as nossas ferramentas**:
    nada de mexer em arquivos ou rodar comandos soltos, e sem ficar pedindo permissão.
- Ler a saída **linha a linha** (cada linha é um JSON):
  - quando aparece um `tool_use`, imprimir `-> tool_name(args)` na hora (é o que aparece na apresentação);
  - o evento final `result` traz o relatório, que vai para `reports/YYYY-MM-DD_HHMM_<target>.md`.
- **`agent_prompt.md`** (a parte que mais influencia a qualidade):
  > You are a network management agent. You received an alert. Investigate using the available tools and
  > identify the most likely layer/cause (DNS, connectivity, port/service, application/latency).
  > Only use `restart_service` if the service belongs to the lab and is down.
  > Finish with a short report **in Brazilian Portuguese** with these sections: Resumo, Evidências,
  > Causa provável, Ação tomada, Recomendação.
- Tratar erros: `claude` não instalado ou não logado, e timeout (máx. 3 min por investigação).
- Teste manual do agente: `python src/agent.py "web-lab at http://127.0.0.1:8080/ is not responding (lab service: web)"`.

### Monitor (`monitor.py`)
- Ler o `config/targets.json` e testar cada alvo a cada 10 s, conforme o `type` (reusando as funções de `net_tools.py`)
- Mostrar um painel simples no console: `[OK]` / `[FAIL]` por alvo
- Guardar o estado anterior e **só acionar o agente na transição OK → FAIL**, para não gastar o limite da assinatura
- Depois que o agente agir, testar de novo e registrar se a correção funcionou
- Opções `--once` (um ciclo só), `--no-agent` (nunca chama a IA) e `--interval N`
- Alvos HTTP falham também por lentidão: `slow_threshold_ms` (padrão 2000 ms)

## 5. Interfaces entre os módulos
**Ferramentas:** todas recebem tipos simples e **retornam uma string JSON** que sempre tem a chave `ok`:
```python
ping("8.8.8.8")
# '{"ok": true, "loss_pct": 0, "latency_ms": 14}'
check_port("127.0.0.1", 8080)
# '{"ok": false, "state": "closed", "error": "connection refused"}'
check_http("http://127.0.0.1:8080/")
# '{"ok": true, "status": 200, "time_ms": 5012}'
```

**Laboratório:** funções importáveis, além da CLI (exigem o controlador rodando):
```python
lab.start(name: str) -> bool
lab.stop(name: str) -> bool
lab.slow(name: str) -> bool
lab.restart(name: str) -> bool
lab.status() -> dict   # {"web": "running", "db": "stopped"}
```

**Agente:** uma única função chamada pelo monitor:
```python
agent.investigate(target: dict, error: str) -> str   # returns the markdown report
```

**Alvo (`config/targets.json`):**
```json
{"name": "web-lab", "type": "http", "url": "http://127.0.0.1:8080/", "lab_service": "web"}
```
Tipos válidos: `ping` (usa `host`), `tcp` (usa `host` + `port`), `http` (usa `url`). `lab_service` é opcional.

## 6. Roteiro da demo (cerca de 5 min, 3 terminais)
1. T1: `python src/lab.py run`. T2: `python src/monitor.py`, com todos `[OK]`. T3: comandos dos cenários.
2. **Cenário 1, serviço caiu:** `python src/lab.py stop web`. O agente vê ping ok e porta fechada,
   reinicia o serviço, e no próximo ciclo o alvo volta a `[OK]`.
3. **Cenário 2, lentidão:** `python src/lab.py slow`. O agente vê DNS e porta ok e o HTTP com 5 s,
   conclui que o problema está na aplicação e não na rede, e não reinicia à toa.
4. **Cenário 3, DNS:** `python src/lab.py dns-fail` (e `dns-ok` para voltar). O agente identifica
   falha de resolução de nomes, faz um teste de controle com outro domínio e não reinicia nada.
5. Abrir os relatórios gerados em `reports/`.

**Plano B:** ter um vídeo gravado da demo, caso a internet ou o limite da assinatura falhe na hora.

## 7. Pontos para destacar na apresentação (ligação com a disciplina)
- **Gerência de falhas** (modelo FCAPS): detecção, diagnóstico e correção automáticos
- **Diagnóstico por camadas:** o agente vai de rede (ping/traceroute) para transporte (porta TCP) e depois para aplicação (HTTP/DNS)
- **Gerente vs. agente:** o monitor é o "gerente" que detecta, e o agente de IA decide e age
- **MCP:** protocolo aberto que padroniza como agentes de IA acessam ferramentas, um paralelo moderno ao papel do SNMP/MIB
- **Segurança:** o agente só pode executar ferramentas de uma lista permitida (princípio do menor privilégio)
- **Custo e eficiência:** a IA é usada só em incidentes, e o monitoramento rotineiro é barato e determinístico
