"""Project paths shared by every module."""

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SRC_DIR.parent

TARGETS_FILE = PROJECT_DIR / "config" / "targets.json"
REPORTS_DIR = PROJECT_DIR / "reports"
STATE_DIR = PROJECT_DIR / ".netsentinel"

PROMPT_FILE = SRC_DIR / "agent_prompt.md"
MCP_SERVER = SRC_DIR / "mcp_server.py"
MCP_TAP = SRC_DIR / "mcp_tap.py"
MCP_TRACE_FILE = STATE_DIR / "mcp_trace.jsonl"
