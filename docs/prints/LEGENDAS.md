# Imagens para o relatório

Imagens geradas a partir de uma execução real do NetSentinel em 14/10/2026: Windows 11, Claude Code 2.1.300,
modelo Claude Sonnet 5.5. Cada imagem reproduz a saída exata do terminal, com as cores originais. A linha
de comando no topo mostra o que foi executado.

Organização dos terminais na demonstração:
- **T1:** laboratório;
- **T2:** monitor + agente;
- **T3:** comandos que provocam os incidentes.

| Arquivo | Legenda sugerida | Seção do relatório |
|---|---|---|
| `01_laboratorio_T1.png` | **Figura 1:** Controlador do laboratório com os serviços falsos `web` (HTTP, porta 8080) e `db` (TCP, porta 6543). O log registra quem executou cada ação: o usuário (`by cli`) ou o agente de IA (`by agent`). | 6.5 Laboratório |
| `02_monitor_tudo_ok_T2.png` | **Figura 2:** Monitor verificando os quatro alvos sem incidentes: dois serviços do laboratório e dois alvos reais da Internet. | 6.2 Monitor |
| `03_ferramentas_de_rede.png` | **Figura 3:** Ferramentas de rede executadas isoladamente, sem IA. Cada uma devolve um JSON com a chave `ok`. | 6.1 Ferramentas |
| `04_cenario1_servico_caiu_T2.png` | **Figura 4:** Cenário 1, queda do serviço web: o monitor detecta a falha, o agente investiga, reinicia o serviço e gera o relatório, e o monitor confirma a recuperação. | 9.1 Resultados |
| `05_comunicacao_agente_mcp.png` | **Figura 5:** Comunicação entre o agente (Claude Code, cliente MCP) e o servidor MCP do NetSentinel, em JSON-RPC 2.0 sobre stdio. Aparecem a negociação de versão (`server/discover`, `initialize`), a descoberta de ferramentas (`tools/list`) e cada chamada (`tools/call`) com sua resposta de mesmo `#id`. As linhas `[LLM]` mostram as decisões do modelo. | 4.5 MCP / 6.6 Observabilidade |
| `06_cenario2_lentidao_T2.png` | **Figura 6:** Cenário 2, lentidão: porta aberta e HTTP 200, mas com 5 s de resposta. O agente diagnostica um problema de aplicação e, seguindo a política, **não** reinicia o serviço. | 9.1 Resultados |
| `07_cenario3_dns_T2.png` | **Figura 7:** Cenário 3, falha de DNS: o agente consulta o domínio inexistente e um domínio de controle, conclui que o resolvedor funciona e que o problema é só daquele nome. | 9.1 Resultados |
| `08_comandos_T3.png` | **Figura 8:** Comandos que provocam e desfazem cada incidente (`stop`, `slow`, `start`, `dns-fail`, `dns-ok`) e o estado do laboratório após cada um. | 8 Metodologia |
| `09_mensagens_jsonrpc_completas.png` | **Figura 9:** Mensagens JSON-RPC reais registradas pelo proxy `mcp_tap.py`: a definição da ferramenta `check_port` anunciada em `tools/list`, a requisição `tools/call` (#4) e a resposta do servidor (#4). | 4.5 MCP / 6.6 Observabilidade |

Os arquivos completos desta execução (relatório e registro MCP do cenário 1) estão em
`docs/examples/mcp-trace/`.
