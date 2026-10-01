"""AI agent that investigates incidents using Claude Code in headless mode.

Claude Code runs with the logged-in Claude subscription (no API key) and may only
use the NetSentinel MCP tools defined in mcp_server.py.

Manual test:
    python agent.py "web-lab at http://127.0.0.1:8080/ is not responding (lab service: web)"
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PROMPT_FILE = PROJECT_DIR / "agent_prompt.md"
MCP_SERVER = PROJECT_DIR / "mcp_server.py"
STATE_DIR = PROJECT_DIR / ".netsentinel"
REPORTS_DIR = PROJECT_DIR / "reports"

MCP_SERVER_NAME = "netsentinel"
TOOL_PREFIX = f"mcp__{MCP_SERVER_NAME}__"
# Optional Claude Code model alias ("sonnet", "opus", ...); None uses the account default.
MODEL = os.environ.get("NETSENTINEL_MODEL") or None
TIMEOUT_S = 180


class AgentError(Exception):
    pass


def investigate(target: dict, error: str) -> str:
    """Run the agent for a failed target and return the markdown report."""
    claude = shutil.which("claude")
    if not claude:
        raise AgentError("Claude Code CLI ('claude') not found in PATH. Install it and run 'claude' once to log in.")

    command = [
        claude, "-p",
        "--mcp-config", str(_write_mcp_config()),
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", "mcp__" + MCP_SERVER_NAME,
        "--permission-mode", "dontAsk",
        "--append-system-prompt-file", str(PROMPT_FILE),
        "--output-format", "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    if MODEL:
        command += ["--model", MODEL]

    env = os.environ.copy()
    if env.pop("ANTHROPIC_API_KEY", None):
        print("[agent] ANTHROPIC_API_KEY ignored: using the Claude subscription instead of the paid API")

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=PROJECT_DIR,
        env=env,
    )
    # The alert goes through stdin so it cannot be confused with CLI options.
    process.stdin.write(_build_alert(target, error))
    process.stdin.close()

    # Drain stderr in the background so a full pipe never blocks the agent.
    stderr_chunks: list[str] = []
    stderr_reader = threading.Thread(target=lambda: stderr_chunks.append(process.stderr.read()), daemon=True)
    stderr_reader.start()

    timer = threading.Timer(TIMEOUT_S, process.kill)
    timer.start()
    try:
        result = _consume_stream(process.stdout)
        process.wait()
    finally:
        timer.cancel()
    stderr_reader.join(timeout=5)

    if result is None:
        stderr = "".join(stderr_chunks).strip()
        if process.returncode not in (0, None) and not stderr:
            stderr = f"exit code {process.returncode} (timeout after {TIMEOUT_S} s?)"
        raise AgentError(f"agent finished without a report: {stderr or 'no output'}")
    if result.get("is_error"):
        raise AgentError(f"agent error: {result.get('result') or result.get('subtype')}")
    return (result.get("result") or "").strip()


def save_report(target_name: str, report: str) -> Path:
    """Save a report as reports/YYYY-MM-DD_HHMM_<target>.md and return its path."""
    REPORTS_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in target_name)
    path = REPORTS_DIR / f"{now:%Y-%m-%d_%H%M%S}_{safe_name}.md"
    header = f"# Incidente: {target_name}\n\n_{now:%Y-%m-%d %H:%M:%S}_\n\n"
    path.write_text(header + report + "\n", encoding="utf-8")
    return path


def _write_mcp_config() -> Path:
    # Generated at runtime so the MCP server uses this same interpreter (the venv).
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / "mcp_config.json"
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {"type": "stdio", "command": sys.executable, "args": [str(MCP_SERVER)]}
        }
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def _build_alert(target: dict, error: str) -> str:
    lab_service = target.get("lab_service")
    lab_line = f"This target is the lab service '{lab_service}'." if lab_service else "This target is NOT a lab service."
    return (
        "ALERT from the NetSentinel monitor.\n"
        f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Target: {json.dumps(target, ensure_ascii=False)}\n"
        f"Observed failure: {error}\n"
        f"{lab_line}\n"
        "Investigate, remediate if appropriate, and write the incident report."
    )


def _consume_stream(stdout) -> dict | None:
    """Print the agent's tool calls live and return the final 'result' event."""
    result = None
    for line in stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue

        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            for server in event.get("mcp_servers", []):
                if server.get("name") == MCP_SERVER_NAME and server.get("status") != "connected":
                    print(f"[agent] warning: MCP server status is '{server.get('status')}'")
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    print(f"  -> {_format_call(block)}", flush=True)
        elif kind == "user":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    print(f"     {_format_tool_result(block)}", flush=True)
        elif kind == "result":
            result = event
    return result


def _format_call(block: dict) -> str:
    name = block.get("name", "?").removeprefix(TOOL_PREFIX)
    args = ", ".join(f"{value!r}" if isinstance(value, str) else str(value)
                     for value in (block.get("input") or {}).values())
    return f"{name}({args})"


def _format_tool_result(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = str(content or "").strip()
    try:
        data = json.loads(text)
        # FastMCP wraps string return values as {"result": "<our JSON>"}.
        if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
            data = json.loads(data["result"])
        status = "ok" if data.pop("ok", False) else "FAIL"
        data.pop("output", None)
        text = f"{status} {json.dumps(data, ensure_ascii=False)}"
    except (ValueError, AttributeError):
        pass
    return "<- " + (text if len(text) <= 140 else text[:137] + "...")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 1
    alert = " ".join(argv)
    print("[agent] investigating...")
    try:
        report = investigate({"name": "manual"}, alert)
    except AgentError as exc:
        print(f"[agent] {exc}")
        return 1
    path = save_report("manual", report)
    print("\n" + report + f"\n\n[agent] report saved to {path.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
