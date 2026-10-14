# NetSentinel

Agente de IA autônomo para monitoramento de rede. Um monitor verifica periodicamente uma lista de
alvos (HTTP, TCP, ping). Quando um alvo passa de OK para FALHA, o agente de IA (Claude Code em
modo headless) investiga sozinho com ferramentas de rede expostas via MCP, identifica a causa,
corrige quando é seguro (reinicia serviços do laboratório) e grava um relatório em `reports/`.

**Documentos do projeto:**
- [`docs/TUTORIAL.md`](docs/TUTORIAL.md): passo a passo para testar cada cenário
- [`docs/RELATORIO.md`](docs/RELATORIO.md): material para o relatório (teoria, arquitetura, decisões, resultados)
- [`docs/PLANO.md`](docs/PLANO.md): plano original do trabalho
- [`docs/examples/`](docs/examples/): relatórios reais gerados pelo agente nos testes, separados por modelo
- [`docs/prints/`](docs/prints/): imagens de uma execução real para o relatório, com legendas em `LEGENDAS.md`

## Requisitos
- Python 3.10+
- [Claude Code](https://code.claude.com) instalado e logado com uma assinatura Claude (Pro/Max).
  Só é necessário para a parte de IA; o monitor e o laboratório funcionam sem ele (`--no-agent`).
- **Não** defina `ANTHROPIC_API_KEY`: o agente remove essa variável ao chamar o Claude Code, para
  garantir que o uso saia da assinatura e não da API paga.

## Instalação
```bash
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

## Como rodar (3 terminais, todos com o venv ativado)
```bash
# Terminal 1: laboratório (serviços falsos web :8080 e db :6543)
python src/lab.py run

# Terminal 2: monitor + agente
python src/monitor.py

# Terminal 3: provocar incidentes
python src/lab.py stop web      # cenário 1: serviço caiu      -> agente reinicia
python src/lab.py start web     #   volta ao normal
python src/lab.py slow          # cenário 2: lentidão          -> agente NÃO reinicia (problema de aplicação)
python src/lab.py start web     #   volta ao normal
python src/lab.py dns-fail      # cenário 3: domínio não resolve -> agente diagnostica DNS
python src/lab.py dns-ok        #   volta ao normal
python src/lab.py status
```
O passo a passo completo, com as saídas esperadas, está em [`docs/TUTORIAL.md`](docs/TUTORIAL.md).

## Comandos úteis
| Comando | O que faz |
|---|---|
| `python src/monitor.py --once` | roda um único ciclo de verificação |
| `python src/monitor.py --no-agent` | só monitora, nunca chama a IA |
| `python src/monitor.py --interval 30` | muda o intervalo entre ciclos (segundos) |
| `python src/monitor.py --mcp-trace raw` | mostra o JSON completo de cada mensagem MCP (`compact` é o padrão; `off` desliga) |
| `python src/agent.py "<descrição do problema>"` | aciona o agente manualmente |
| `python src/net_tools.py ping 8.8.8.8` | testa uma ferramenta isolada |

### Modelo de IA
O padrão é o **Claude Sonnet**. Nos testes, Sonnet, Haiku e Opus resolveram todos os cenários; o Haiku
é o que menos consome o limite da assinatura. Para usar outro modelo, defina `NETSENTINEL_MODEL`
(`haiku`, `opus`):

| Terminal | Comando |
|---|---|
| PowerShell | `$env:NETSENTINEL_MODEL = "haiku"` |
| cmd | `set NETSENTINEL_MODEL=haiku` |
| Bash | `export NETSENTINEL_MODEL=haiku` |

O modelo usado aparece no console no início de cada investigação (`[agent] model: ...`).

## Comunicação agente ↔ MCP
Durante cada investigação, o monitor mostra ao vivo as duas camadas da conversa:
- **`[LLM]`:** o que o modelo decidiu fazer (qual ferramenta chamar, com quais argumentos);
- **`[MCP]`:** as mensagens **JSON-RPC 2.0** trocadas por stdio entre o Claude Code (cliente MCP) e
  o nosso servidor MCP: negociação do protocolo, catálogo de ferramentas, cada `tools/call` e sua resposta.

```
[MCP] client → server  #0 initialize       protocol 2025-11-25, client claude-code 2.1.300
[MCP] server → client  #0 result           server netsentinel 1.30.0, capabilities: experimental, prompts, resources, tools
[MCP] client → server     notifications/initialized
[MCP] client → server  #1 tools/list
[MCP] server → client  #1 result           6 tools: ping, dns_lookup, check_port, check_http, traceroute, restart_service
[LLM] decides to call check_port('127.0.0.1', 8080)
[MCP] client → server  #4 tools/call       check_port {"host": "127.0.0.1", "port": 8080}
[MCP] server → client  #4 result           {"ok": false, "host": "127.0.0.1", "port": 8080, "state": "closed", ...}
```

Como funciona: o Claude Code não inicia o `mcp_server.py` diretamente, e sim o `src/mcp_tap.py`, um
proxy transparente que repassa as mensagens sem alterá-las e grava cada uma num arquivo. O monitor lê esse
arquivo enquanto o agente trabalha. A conversa completa de cada incidente é salva em
`reports/<data>_<alvo>_mcp.jsonl`, ao lado do relatório. Há um exemplo em
[`docs/examples/mcp-trace/`](docs/examples/mcp-trace/).

## Estrutura
```
README.md
requirements.txt
config/targets.json      # alvos monitorados
src/                     # código-fonte
docs/                    # plano, tutorial, material do relatório e exemplos
reports/                 # relatórios gerados (criada ao rodar; fora do git)
```

## Arquitetura
```
config/targets.json ──► monitor.py ──(OK → FAIL)──► agent.py ──► claude -p (assinatura)
                           ▲                                        │ MCP / JSON-RPC (stdio)
                           │ mensagens MCP ao vivo                   ▼
                     mcp_view.py ◄── .netsentinel/mcp_trace.jsonl ◄── mcp_tap.py (proxy)
                                                                    │
                                                                    ▼
                                          lab.py ◄── net_tools.py ◄── mcp_server.py
```

| Arquivo | Papel |
|---|---|
| `src/monitor.py` | loop de monitoramento sem IA; aciona o agente só na transição OK → FAIL |
| `src/agent.py` | chama `claude -p` restrito às ferramentas do MCP, mostra as ações ao vivo e salva o relatório |
| `src/agent_prompt.md` | prompt de sistema do agente (regras de diagnóstico, remediação e formato do relatório) |
| `src/net_tools.py` | ferramentas de rede: `ping`, `dns_lookup`, `check_port`, `check_http`, `traceroute`, `restart_service` |
| `src/mcp_server.py` | expõe as funções de `net_tools.py` como ferramentas MCP |
| `src/mcp_tap.py` | proxy transparente entre o Claude Code e o servidor MCP que registra cada mensagem JSON-RPC |
| `src/mcp_view.py` | mostra no console, ao vivo, as mensagens registradas pelo proxy |
| `src/lab.py` | controlador do laboratório: hospeda os serviços falsos, recebe comandos na porta 8099 e liga/desliga o cenário de DNS |
| `src/paths.py` | caminhos do projeto usados por todos os módulos |
| `config/targets.json` | alvos monitorados (`type`: `http`, `tcp` ou `ping`; `lab_service` e `slow_threshold_ms` opcionais) |

## Segurança do agente
O Claude Code é executado com `--tools ""` (nenhuma ferramenta nativa, como arquivos ou shell),
`--strict-mcp-config` (só o nosso servidor MCP), `--allowedTools mcp__netsentinel` e
`--permission-mode dontAsk`. Assim, o agente só consegue chamar as ferramentas de `net_tools.py`,
e `restart_service` só aceita os serviços do laboratório (`web`, `db`).

## Solução de problemas
- **`lab controller is not running`**: rode `python src/lab.py run` em outro terminal.
- **`cannot listen on port ...`**: a porta está em uso ou reservada pelo Windows
  (`netsh int ipv4 show excludedportrange protocol=tcp`); troque a porta em `src/lab.py`, `src/agent_prompt.md` e `config/targets.json`.
- **`Claude Code CLI ('claude') not found`**: instale o Claude Code e rode `claude` uma vez para fazer login.
