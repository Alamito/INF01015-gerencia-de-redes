# Tutorial: testando o NetSentinel cenário por cenário

Este guia mostra como preparar o ambiente e provocar cada incidente, e o que deve aparecer na tela
em cada passo. As saídas abaixo vêm de execuções reais; os números (tempos, latências) e o texto
do relatório mudam um pouco a cada execução, porque o relatório é escrito pela IA.

---

## 0. Preparação (uma vez só)

### 0.1 Pré-requisitos
- **Python 3.10+**: confira com `python --version`.
- **Claude Code** instalado e logado: rode `claude` uma vez, faça o login com a conta da assinatura e saia com `/exit`.
  Só é necessário para os cenários com IA (seção 2 em diante).
- A variável `ANTHROPIC_API_KEY` **não** deve estar definida. Se estiver, o agente ignora a variável e avisa no console.

### 0.2 Criar o ambiente virtual e instalar as dependências
Na pasta do projeto:

```bash
python -m venv .venv
```

Ative o ambiente. **Repita isso em cada terminal novo que abrir:**

| Terminal | Comando |
|---|---|
| PowerShell | `.venv\Scripts\Activate.ps1` |
| Prompt de Comando (cmd) | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| Linux / macOS | `source .venv/bin/activate` |

> Se o PowerShell bloquear o script de ativação, rode uma vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` ou use o cmd.

Depois instale as dependências:

```bash
pip install -r requirements.txt
```

### 0.3 Organização dos terminais
Todos os cenários usam **3 terminais** abertos na pasta do projeto, com o venv ativado:

| Terminal | Papel | Comando |
|---|---|---|
| **T1** | Laboratório (serviços falsos) | `python src/lab.py run` |
| **T2** | Monitor + agente de IA | `python src/monitor.py` |
| **T3** | "Sabotador": provoca os incidentes | comandos de cada cenário |

---

## 1. Teste rápido sem IA (não consome a assinatura)

Serve para validar a instalação e para quem não tem o Claude Code.

**T1:**
```bash
python src/lab.py run
```
Saída esperada:
```
[13:45:58] web listening on 127.0.0.1:8080
[13:45:58] db listening on 127.0.0.1:6543
[13:45:58] lab controller ready on 127.0.0.1:8099 (Ctrl+C to quit)
```

**T2:**
```bash
python src/monitor.py --once --no-agent
```
Saída esperada (todos `[OK]`):
```
[13:43:37] checking 4 targets...
  [OK]   web-lab      HTTP 200 in 5 ms
  [OK]   db-lab       port 6543 open
  [OK]   google-dns   50.8 ms, 0% loss
  [OK]   ufrgs        HTTP 200 in 501 ms
```

Também dá para testar cada ferramenta isoladamente:
```bash
python src/net_tools.py ping 8.8.8.8
python src/net_tools.py dns_lookup www.ufrgs.br
python src/net_tools.py check_port 127.0.0.1 8080
python src/net_tools.py check_http http://127.0.0.1:8080/
```

Para ver o estado do laboratório a qualquer momento (**T3**):
```bash
python src/lab.py status
```
```
  web  127.0.0.1:8080  running
  db   127.0.0.1:6543  running
  dns  broken-dns      ok (target disabled)
```

✅ **Deu certo se:** os 4 alvos aparecem `[OK]` e cada ferramenta retorna um JSON com `"ok": true`.

---

## 2. Iniciando o monitoramento com IA

Com o T1 rodando (`python src/lab.py run`), inicie o monitor contínuo no **T2**:
```bash
python src/monitor.py
```
A cada 10 segundos aparece um novo ciclo com todos `[OK]`. Deixe o T2 rodando durante todos os cenários.

### Qual modelo de IA é usado
O padrão é o **Claude Sonnet** (definido em `src/agent.py`). O modelo aparece no início de cada
investigação (`[agent] model: claude-sonnet-...`). Para testar com outro modelo, defina a variável
`NETSENTINEL_MODEL` **no T2, antes** de iniciar o monitor:

| Terminal | Haiku (consome menos a assinatura) | Opus |
|---|---|---|
| PowerShell | `$env:NETSENTINEL_MODEL = "haiku"` | `$env:NETSENTINEL_MODEL = "opus"` |
| cmd | `set NETSENTINEL_MODEL=haiku` | `set NETSENTINEL_MODEL=opus` |
| Bash | `export NETSENTINEL_MODEL=haiku` | `export NETSENTINEL_MODEL=opus` |

Nos testes, os três modelos resolveram todos os cenários. As saídas abaixo são do Sonnet; com outro
modelo, a ordem e a quantidade de chamadas de ferramenta podem mudar um pouco.

### O que aparece durante uma investigação
Cada investigação mostra duas camadas, uma linha por evento:
- **`[LLM]`** (roxo): a decisão do modelo de chamar uma ferramenta;
- **`[MCP]`** (ciano): as mensagens JSON-RPC trocadas entre o Claude Code (`client`) e o nosso servidor
  MCP (`server`). Uma requisição e sua resposta têm o mesmo número (`#4` → `#4`).

A seção 6 explica essa comunicação em detalhes.

> **Regra importante:** o agente só é acionado quando um alvo **passa de OK para FAIL**. Se um alvo
> continuar falhando, ele não é investigado de novo. Por isso, **antes de cada cenário confirme que tudo
> voltou a `[OK]`** no T2.

---

## 3. Cenário 1: serviço caiu (o agente corrige)

**Objetivo:** mostrar o agente detectando um serviço fora do ar, reiniciando sozinho e confirmando a recuperação.

### Passo 1: derrubar o serviço web (T3)
```bash
python src/lab.py stop web
```

### Passo 2: acompanhar o T2
No próximo ciclo (até 10 s) o monitor detecta a falha e aciona o agente:
```
  [FAIL] web-lab      GET http://127.0.0.1:8080/ failed: connection error: connection refused
[monitor] ALERT: web-lab: GET http://127.0.0.1:8080/ failed: connection error: connection refused
[agent] investigating web-lab...
[agent] model: claude-sonnet-5-5
[LLM] decides to call check_port('127.0.0.1', 8080)
[MCP] client → server  #4 tools/call       check_port {"host": "127.0.0.1", "port": 8080}
[LLM] decides to call ping('127.0.0.1')
[MCP] server → client  #4 result           {"ok": false, "host": "127.0.0.1", "port": 8080, "state": "closed", "error": "connection refused"}
[MCP] client → server  #5 tools/call       ping {"host": "127.0.0.1"}
[MCP] server → client  #5 result           {"ok": true, "host": "127.0.0.1", "loss_pct": 0, "latency_ms": 1.0}
[LLM] decides to call restart_service('web')
[MCP] client → server  #6 tools/call       restart_service {"name": "web"}
[MCP] server → client  #6 result           {"ok": true, "name": "web", "state": "running", "port": 8080}
[LLM] decides to call check_http('http://127.0.0.1:8080/')
[MCP] client → server  #7 tools/call       check_http {"url": "http://127.0.0.1:8080/"}
[MCP] server → client  #7 result           {"ok": true, "url": "http://127.0.0.1:8080/", "status": 200, "time_ms": 29}
```
(as mensagens iniciais de conexão MCP, explicadas na seção 6, foram omitidas)

O agente testa a porta e a rede: o host responde (`ping` ok), mas a porta está fechada, então o serviço caiu.
Em seguida aparece o relatório (seções Resumo, Evidências, Causa provável, Ação tomada e
Recomendação), e no final:
```
[monitor] verification: OK (HTTP 200 in 27 ms)
[monitor] report saved to reports\2026-10-14_180742_web-lab.md
```

### Passo 3: conferir o T1
O laboratório registra quem fez cada ação:
```
[18:07:17] web stopped (by cli)
[18:07:36] web restarted (by agent)
```

✅ **Deu certo se:** o agente chamou `restart_service('web')`, a verificação do monitor deu `OK` e o
`web-lab` voltou a `[OK]` nos ciclos seguintes.

**Variação com o banco:** `python src/lab.py stop db`. O agente verifica a porta 6543, reinicia o
serviço `db` e confirma com `check_port`:
```
[LLM] decides to call check_port('127.0.0.1', 6543)
[MCP] client → server  #4 tools/call       check_port {"host": "127.0.0.1", "port": 6543}
[LLM] decides to call ping('127.0.0.1')
[MCP] server → client  #4 result           {"ok": false, "host": "127.0.0.1", "port": 6543, "state": "closed", "error": "connection refused"}
[MCP] client → server  #5 tools/call       ping {"host": "127.0.0.1"}
[MCP] server → client  #5 result           {"ok": true, "host": "127.0.0.1", "loss_pct": 0, "latency_ms": 1.0}
[LLM] decides to call restart_service('db')
[MCP] client → server  #6 tools/call       restart_service {"name": "db"}
[MCP] server → client  #6 result           {"ok": true, "name": "db", "state": "running", "port": 6543}
[LLM] decides to call check_port('127.0.0.1', 6543)
[MCP] client → server  #7 tools/call       check_port {"host": "127.0.0.1", "port": 6543}
[MCP] server → client  #7 result           {"ok": true, "host": "127.0.0.1", "port": 6543, "state": "open", "time_ms": 17.2}
[monitor] verification: OK (port 6543 open)
```

---

## 4. Cenário 2: lentidão (o agente NÃO reinicia)

**Objetivo:** mostrar que o agente diferencia "serviço fora do ar" de "serviço lento" e não toma uma
ação desnecessária.

### Passo 1: confirmar que tudo está `[OK]` no T2

### Passo 2: deixar o web lento (T3)
```bash
python src/lab.py slow
```
Cada resposta HTTP passa a demorar 5 s, acima do limite de 2000 ms configurado no monitor.

### Passo 3: acompanhar o T2
```
  [FAIL] web-lab      GET http://127.0.0.1:8080/ too slow: 5005 ms (threshold 2000 ms)
[monitor] ALERT: web-lab: GET http://127.0.0.1:8080/ too slow: 5005 ms (threshold 2000 ms)
[agent] investigating web-lab...
[agent] model: claude-sonnet-5-5
[LLM] decides to call ping('127.0.0.1')
[MCP] client → server  #4 tools/call       ping {"host": "127.0.0.1"}
[LLM] decides to call check_port('127.0.0.1', 8080)
[LLM] decides to call check_http('http://127.0.0.1:8080/')
[MCP] server → client  #4 result           {"ok": true, "host": "127.0.0.1", "loss_pct": 0, "latency_ms": 1.0}
[MCP] client → server  #5 tools/call       check_port {"host": "127.0.0.1", "port": 8080}
[MCP] server → client  #5 result           {"ok": true, "host": "127.0.0.1", "port": 8080, "state": "open", "time_ms": 9.5}
[MCP] client → server  #6 tools/call       check_http {"url": "http://127.0.0.1:8080/"}
[MCP] server → client  #6 result           {"ok": true, "url": "http://127.0.0.1:8080/", "status": 200, "time_ms": 5020}
```
(as mensagens iniciais de conexão MCP, explicadas na seção 6, foram omitidas)

O modelo pede as três camadas de uma vez (rede, porta e HTTP), e o Claude Code executa as chamadas MCP
uma após a outra. Resultado: rede ok, porta aberta, HTTP 200, mas em 5 s.
O relatório deve dizer que a porta está aberta e o HTTP responde (status 200), mas devagar, ou seja,
um **problema na camada de aplicação**, e que **nenhuma ação foi tomada**. No final:
```
[monitor] verification: still failing (GET http://127.0.0.1:8080/ too slow: 5017 ms (threshold 2000 ms))
```
Isso é o esperado: o agente não corrigiu, porque a política só permite reiniciar serviços fora do ar.

### Passo 4: voltar ao normal (T3)
```bash
python src/lab.py start web
```
O serviço volta ao modo normal e, em até 10 s, o `web-lab` volta a `[OK]` no T2.

✅ **Deu certo se:** o agente **não** chamou `restart_service` e o relatório aponta problema de aplicação.

---

## 5. Cenário 3: falha de DNS (domínio inexistente)

**Objetivo:** mostrar o diagnóstico por camadas: sem resolução de nome, não adianta testar rede nem porta.

### Passo 1: provocar a falha de DNS (T3)
```bash
python src/lab.py dns-fail
```
```
  dns-fail: ok
  web  127.0.0.1:8080  running
  db   127.0.0.1:6543  running
  dns  broken-dns      failing (target enabled)
```
Esse comando ativa, em `config/targets.json`, o alvo `broken-dns`, um site cujo domínio
(`netsentinel-nonexistent-domain.xyz`) não existe. O monitor relê esse arquivo a cada ciclo,
então **não precisa reiniciar o T2**.

### Passo 2: acompanhar o T2
```
  [FAIL] broken-dns   GET http://netsentinel-nonexistent-domain.xyz/ failed: connection error: name resolution failed
[monitor] ALERT: broken-dns: GET http://netsentinel-nonexistent-domain.xyz/ failed: connection error: name resolution failed
[agent] investigating broken-dns...
[agent] model: claude-sonnet-5-5
[LLM] decides to call dns_lookup('netsentinel-nonexistent-domain.xyz')
[LLM] decides to call dns_lookup('www.ufrgs.br')
[MCP] client → server  #4 tools/call       dns_lookup {"name": "netsentinel-nonexistent-domain.xyz"}
[MCP] server → client  #4 result           {"ok": false, "name": "netsentinel-nonexistent-domain.xyz", "error": "resolution failed: [Errno 11001] getaddrinfo failed"}
[MCP] client → server  #5 tools/call       dns_lookup {"name": "www.ufrgs.br"}
[MCP] server → client  #5 result           {"ok": true, "name": "www.ufrgs.br", "addresses": ["143.54.2.20", "2804:1f20:0:1::20"], "time_ms": 2.0}
```
(as mensagens iniciais de conexão MCP, explicadas na seção 6, foram omitidas)

O agente decide as duas consultas de uma vez: o domínio com problema e um domínio de controle.
Se o controle resolve, o servidor DNS está funcionando e o problema é só daquele nome.
O relatório deve apontar **falha de DNS** (domínio inexistente ou sem registro A/AAAA) e dizer que
nada foi reiniciado, porque o alvo não é do laboratório.

### Passo 3: voltar ao normal (T3)
```bash
python src/lab.py dns-ok
```
O alvo `broken-dns` é desativado e some do painel no próximo ciclo. Dá para repetir o cenário com
`dns-fail` quantas vezes quiser: a cada reativação, o agente é acionado de novo.

✅ **Deu certo se:** o agente usou `dns_lookup`, não tentou `ping`/`check_port` (não há IP para testar)
e não chamou `restart_service`.

---

## 6. Vendo a comunicação entre o agente e o MCP

**Objetivo:** mostrar, mensagem por mensagem, como o agente (Claude Code) conversa com o nosso servidor
MCP pelo protocolo **JSON-RPC 2.0** sobre **stdio** (entrada e saída padrão do processo).

### 6.1 Onde ver
A comunicação já aparece no T2 em todos os cenários. Ela pode ser vista de três formas:

| Forma | Como |
|---|---|
| Resumida, ao vivo (padrão) | `python src/monitor.py` |
| JSON completo, ao vivo | `python src/monitor.py --mcp-trace raw` |
| Arquivo da investigação | `reports/<data>_<alvo>_mcp.jsonl` (uma mensagem por linha, com horário e direção) |
| Desligada | `python src/monitor.py --mcp-trace off` (mostra só as linhas `[LLM]` e os resultados) |

Um exemplo real completo está em `docs/examples/mcp-trace/`.

### 6.2 Lendo a conversa, linha por linha
Início de uma investigação real (cenário 1):
```
[MCP] JSON-RPC 2.0 over stdio · client = Claude Code · server = netsentinel (src/mcp_server.py)
[MCP] client → server  #server-discover-probe-1 server/discover  {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", ...
[MCP] server → client  #server-discover-probe-1 error            -32602 Invalid request parameters
[MCP] client → server  #0 initialize       protocol 2025-11-25, client claude-code 2.1.300
[MCP] server → client  #0 result           server netsentinel 1.30.0, capabilities: experimental, prompts, resources, tools
[MCP] client → server     notifications/initialized
[MCP] client → server  #1 tools/list
[MCP] client → server  #2 prompts/list
[MCP] client → server  #3 resources/list
[MCP] server → client  #1 result           6 tools: ping, dns_lookup, check_port, check_http, traceroute, restart_service
[MCP] server → client  #2 result           0 prompts
[MCP] server → client  #3 result           0 resources
[agent] model: claude-sonnet-5-5
[LLM] decides to call check_port('127.0.0.1', 8080)
[MCP] client → server  #4 tools/call       check_port {"host": "127.0.0.1", "port": 8080}
[MCP] server → client  #4 result           {"ok": false, "host": "127.0.0.1", "port": 8080, "state": "closed", "error": "connection refused"}
```

| Fase | Mensagens | O que acontece |
|---|---|---|
| 1. Negociação de versão | `server/discover` → `error -32602` | O Claude Code tenta primeiro uma versão mais nova do protocolo (2026-07-28). Nosso servidor (biblioteca `mcp` 1.30) não a conhece e responde com erro, então o cliente recua. |
| 2. Inicialização | `initialize` → `result`, `notifications/initialized` | Cliente e servidor combinam a versão `2025-11-25` e trocam nome, versão e capacidades. A notificação não tem `#id`, porque não espera resposta. |
| 3. Descoberta | `tools/list`, `prompts/list`, `resources/list` | O cliente pede o catálogo. O servidor anuncia as 6 ferramentas, com descrição e esquema dos parâmetros: é o que o modelo "lê" para decidir. |
| 4. Uso | `[LLM]` → `tools/call` → `result` | O modelo decide uma chamada; o Claude Code a envia como `tools/call` com nome e argumentos; o servidor executa a função Python e devolve o JSON. |
| 5. Encerramento | (fim do stdio) | Ao terminar o relatório, o Claude Code fecha a entrada do servidor e o processo termina. |

**Para observar:**
- **`#id` liga requisição e resposta:** `#4 tools/call` é respondido por `#4 result`. Isso é o JSON-RPC.
- **Quem decide e quem executa:** a linha `[LLM]` é a decisão do modelo; a linha `[MCP]` é o protocolo levando
  essa decisão até o servidor. O modelo nunca executa nada diretamente.
- **Paralelo vs. sequencial:** quando o modelo decide duas chamadas juntas (duas linhas `[LLM]` seguidas),
  o Claude Code ainda as envia ao servidor uma de cada vez (`#4` termina antes de `#5` começar).

### 6.3 Como a captura funciona
O Claude Code não inicia o `src/mcp_server.py` diretamente: ele inicia o `src/mcp_tap.py`, um proxy
que inicia o servidor real, **repassa cada mensagem sem alterá-la** e grava uma cópia em
`.netsentinel/mcp_trace.jsonl`. O `src/mcp_view.py` lê esse arquivo enquanto o agente trabalha e imprime
cada mensagem no T2. Ao final, o registro é copiado para `reports/`, ao lado do relatório.

```
Claude Code ⇄ mcp_tap.py (proxy) ⇄ mcp_server.py
                   │
                   └─► .netsentinel/mcp_trace.jsonl ─► mcp_view.py ─► console do monitor
```

✅ **Deu certo se:** no T2 aparecem as linhas `[MCP]` de `initialize`, `tools/list` e `tools/call`, e em
`reports/` existe um arquivo `_mcp.jsonl` para cada relatório.

---

## 7. Acionando o agente manualmente (sem o monitor)

Útil para testar o prompt ou mostrar o agente isolado. Com o T1 rodando:
```bash
python src/agent.py "web-lab at http://127.0.0.1:8080/ is not responding (lab service: web)"
```
O agente investiga a partir da descrição e salva o relatório como `reports/<data>_manual.md`.

---

## 8. Onde ver os resultados

- **Relatórios:** pasta `reports/`, um arquivo `.md` por incidente, com o relatório da IA e a
  verificação final do monitor, e um `_mcp.jsonl` com a comunicação MCP da investigação.
- **Log do laboratório:** terminal T1 (quem parou, iniciou ou reiniciou cada serviço).
- **Exemplos prontos:** `docs/examples/`, com relatórios reais dos 4 cenários gerados pelo Sonnet,
  pelo Haiku e pelo Opus.

---

## 9. Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `lab controller is not running (start it with: python src/lab.py run)` | O T1 não está rodando. Inicie `python src/lab.py run`. |
| `error: cannot open control port 8099 (is the lab already running?)` | Já existe um laboratório aberto em outro terminal. Use esse ou feche-o com Ctrl+C. |
| `web: cannot listen on port 8080` | A porta está ocupada por outro programa ou reservada pelo Windows (`netsh int ipv4 show excludedportrange protocol=tcp`). Troque a porta em `src/lab.py`, `config/targets.json` e `src/agent_prompt.md`. |
| `Claude Code CLI ('claude') not found in PATH` | Instale o Claude Code e abra um terminal novo. |
| `agent finished without a report: ...` | Rode `claude` uma vez para conferir se o login está ativo e se o limite da assinatura não acabou. |
| O agente não foi acionado | O alvo já estava em `[FAIL]` antes. Restaure o serviço, espere voltar a `[OK]` e provoque a falha de novo. |
| `target 'broken-dns' not found in targets.json` | O alvo do cenário 3 foi apagado de `config/targets.json`. Restaure com `git checkout config/targets.json`. |
| Modelo diferente do esperado em `[agent] model:` | A variável `NETSENTINEL_MODEL` está definida nesse terminal. Remova-a ou abra um terminal novo. |
| `ufrgs` ou `google-dns` em `[FAIL]` | Sem internet, ou a rede bloqueia ICMP/HTTPS. O agente vai investigar esse alvo também (é um incidente real). |
| Caracteres estranhos ou cores não aparecem | Use o Windows Terminal ou o PowerShell mais recente. |

Para encerrar tudo: **Ctrl+C** no T2 (monitor) e no T1 (laboratório).
