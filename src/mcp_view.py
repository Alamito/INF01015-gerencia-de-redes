"""Live console view of the MCP communication recorded by mcp_tap.py.

Each JSON-RPC message between Claude Code (MCP client) and the NetSentinel MCP
server is printed as one line, either summarized ("compact") or as the full
JSON ("raw").
"""

import json
import threading
import time
from pathlib import Path

MCP_COLOR, LLM_COLOR, DIM, RESET = "\033[36m", "\033[35m", "\033[2m", "\033[0m"
MAX_LINE = 160

_print_lock = threading.Lock()


def emit(line: str) -> None:
    """Print a line without mixing it with lines printed by another thread."""
    with _print_lock:
        try:
            print(line, flush=True)
        except UnicodeEncodeError:  # console without UTF-8: degrade instead of failing
            print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)


def emit_llm(text: str) -> None:
    emit(f"{LLM_COLOR}[LLM]{RESET} {text}")


class McpTraceViewer:
    """Follows the trace file in a background thread and prints new messages."""

    def __init__(self, trace_file: Path, raw: bool = False):
        self.trace_file = trace_file
        self.raw = raw
        self.pending: dict = {}  # request id -> method, to describe the responses
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._follow, daemon=True)

    def start(self) -> None:
        emit(f"{MCP_COLOR}[MCP]{RESET} {DIM}JSON-RPC 2.0 over stdio · client = Claude Code · "
             f"server = netsentinel (src/mcp_server.py){RESET}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _follow(self) -> None:
        with open(self.trace_file, encoding="utf-8") as trace:
            while True:
                line = trace.readline()
                if line.strip():
                    try:
                        self._show(json.loads(line))
                    except Exception:  # a bad line must never stop the live view
                        pass
                elif self._stop.is_set():
                    return  # stopped and everything already shown
                else:
                    time.sleep(0.05)

    def _show(self, entry: dict) -> None:
        to_server = entry.get("direction") == "client->server"
        arrow = "client → server" if to_server else "server → client"
        message = entry.get("message", {})
        if self.raw:  # full message, never truncated
            text = json.dumps(message, ensure_ascii=False)
        else:
            text = _truncate(self._summarize(message))
        emit(f"{MCP_COLOR}[MCP] {arrow}{RESET}  {text}")

    def _summarize(self, message: dict) -> str:
        msg_id = message.get("id")
        method = message.get("method")
        tag = f"#{msg_id}" if msg_id is not None else "  "

        if method and msg_id is not None:  # request
            self.pending[msg_id] = method
            return f"{tag} {method:<16} {_describe_request(method, message.get('params') or {})}"
        if method:  # notification
            return f"{tag} {method}"

        # response
        method = self.pending.pop(msg_id, "?")
        if "error" in message:
            error = message["error"]
            return f"{tag} {'error':<16} {error.get('code')} {error.get('message')}"
        return f"{tag} {'result':<16} {_describe_result(method, message.get('result') or {})}"


def _describe_request(method: str, params: dict) -> str:
    if method == "initialize":
        client = params.get("clientInfo", {})
        return f"protocol {params.get('protocolVersion')}, client {client.get('name')} {client.get('version', '')}"
    if method == "tools/call":
        return f"{params.get('name')} {json.dumps(params.get('arguments', {}), ensure_ascii=False)}"
    return json.dumps(params, ensure_ascii=False) if params else ""


def _describe_result(method: str, result: dict) -> str:
    if method == "initialize":
        server = result.get("serverInfo", {})
        capabilities = ", ".join(result.get("capabilities", {}))
        return f"server {server.get('name')} {server.get('version', '')}, capabilities: {capabilities}"
    if method == "tools/list":
        names = [tool.get("name") for tool in result.get("tools", [])]
        return f"{len(names)} tools: {', '.join(names)}"
    if method == "tools/call":
        text = " ".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
        try:
            data = json.loads(text)
            data.pop("output", None)  # traceroute output is too long for one line
            text = json.dumps(data, ensure_ascii=False)
        except (ValueError, AttributeError):
            pass
        return ("[isError] " if result.get("isError") else "") + text
    for key in ("tools", "prompts", "resources", "resourceTemplates"):
        if key in result:
            return f"{len(result[key])} {key}"
    return json.dumps(result, ensure_ascii=False)


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_LINE else text[:MAX_LINE - 3] + "..."
