# NetSentinel

Agente de IA autônomo para monitoramento de rede. Um monitor verifica periodicamente uma lista de
alvos (HTTP, TCP, ping). Quando um alvo passa de OK para FALHA, o agente de IA (Claude Code em
modo headless) investiga sozinho com ferramentas de rede expostas via MCP, identifica a causa,
corrige quando é seguro (reinicia serviços do laboratório) e grava um relatório em `reports/`.

**Documentos do projeto:**
- [`TUTORIAL.md`](TUTORIAL.md): passo a passo para testar cada cenário
- [`RELATORIO.md`](RELATORIO.md): material para o relatório (teoria, arquitetura, decisões, resultados)
- [`PLANO.md`](PLANO.md): plano original do trabalho
- [`examples/`](examples/): relatórios reais gerados pelo agente nos testes

## Requisitos
- Python 3.10+
- [Claude Code](https://code.claude.com) instalado e logado com uma assinatura Claude (Pro/Max).
  Só é necessário para a parte de IA; o monitor e o laboratório funcionam sem ele (`--no-agent`).
- **Não** defina `ANTHROPIC_API_KEY`: o agente remove essa variável ao chamar o Claude Code, para
  garantir que o uso saia da assinatura e não da API paga.

## Instalação
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

## Como rodar (3 terminais, todos com o venv ativado)
```bash
# Terminal 1: laboratório (serviços falsos web :8080 e db :6543)
python lab.py run

# Terminal 2: monitor + agente
python monitor.py

# Terminal 3: provocar incidentes
python lab.py stop web      # cenário 1: serviço caiu  -> agente reinicia
python lab.py slow          # cenário 2: lentidão      -> agente NÃO reinicia (problema de aplicação)
python lab.py start web     # volta ao normal
python lab.py status
```
Cenário 3 (DNS): em `targets.json`, troque `"enabled": false` para `true` no alvo `broken-dns`.
O monitor relê o arquivo a cada ciclo, então não precisa reiniciar nada.

## Comandos úteis
| Comando | O que faz |
|---|---|
| `python monitor.py --once` | roda um único ciclo de verificação |
| `python monitor.py --no-agent` | só monitora, nunca chama a IA |
| `python monitor.py --interval 30` | muda o intervalo entre ciclos (segundos) |
| `python agent.py "<descrição do problema>"` | aciona o agente manualmente |
| `python -c "import net_tools as t; print(t.ping('8.8.8.8'))"` | testa uma ferramenta isolada |

Variável opcional `NETSENTINEL_MODEL` (ex.: `sonnet`, `opus`) escolhe o modelo usado pelo Claude Code.

## Arquitetura
```
targets.json ──► monitor.py ──(OK → FAIL)──► agent.py ──► claude -p (assinatura)
                                                             │ MCP (stdio)
                                                             ▼
                                   lab.py ◄── net_tools.py ◄── mcp_server.py
```

| Arquivo | Papel |
|---|---|
| `monitor.py` | loop de monitoramento sem IA; aciona o agente só na transição OK → FAIL |
| `agent.py` | chama `claude -p` restrito às ferramentas do MCP, mostra as ações ao vivo e salva o relatório |
| `agent_prompt.md` | prompt de sistema do agente (regras de diagnóstico, remediação e formato do relatório) |
| `net_tools.py` | ferramentas de rede: `ping`, `dns_lookup`, `check_port`, `check_http`, `traceroute`, `restart_service` |
| `mcp_server.py` | expõe as funções de `net_tools.py` como ferramentas MCP |
| `lab.py` | controlador do laboratório: hospeda os serviços falsos e recebe comandos na porta 8099 |
| `targets.json` | alvos monitorados (`type`: `http`, `tcp` ou `ping`; `lab_service` e `slow_threshold_ms` opcionais) |

## Segurança do agente
O Claude Code é executado com `--tools ""` (nenhuma ferramenta nativa, como arquivos ou shell),
`--strict-mcp-config` (só o nosso servidor MCP), `--allowedTools mcp__netsentinel` e
`--permission-mode dontAsk`. Assim, o agente só consegue chamar as ferramentas de `net_tools.py`,
e `restart_service` só aceita os serviços do laboratório (`web`, `db`).

## Solução de problemas
- **`lab controller is not running`**: rode `python lab.py run` em outro terminal.
- **`cannot listen on port ...`**: a porta está em uso ou reservada pelo Windows
  (`netsh int ipv4 show excludedportrange protocol=tcp`); troque a porta em `lab.py` e `targets.json`.
- **`Claude Code CLI ('claude') not found`**: instale o Claude Code e rode `claude` uma vez para fazer login.
