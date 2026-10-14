"""Transparent stdio proxy between Claude Code (MCP client) and the NetSentinel MCP server.

Claude Code starts this script instead of mcp_server.py. It starts the real server,
forwards every message unchanged in both directions and appends each JSON-RPC
message to a trace file (one JSON object per line), so the monitor can show the
MCP communication live.

Usage (done by agent.py): python src/mcp_tap.py <trace_file>
"""

import json
import subprocess
import sys
import threading
import time

from paths import MCP_SERVER

CLIENT_TO_SERVER = "client->server"
SERVER_TO_CLIENT = "server->client"


def main(trace_path: str) -> int:
    server = subprocess.Popen(
        [sys.executable, str(MCP_SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        bufsize=0,
    )
    trace = open(trace_path, "a", encoding="utf-8")
    lock = threading.Lock()

    def record(direction: str, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            message = {"raw": line.decode("utf-8", errors="replace").strip()}
        with lock:
            trace.write(json.dumps({"time": time.time(), "direction": direction, "message": message}) + "\n")
            trace.flush()

    def pump(source, destination, direction: str) -> None:
        # MCP over stdio sends one JSON-RPC message per line.
        for line in iter(source.readline, b""):
            if line.strip():
                record(direction, line)
            destination.write(line)
            destination.flush()
        try:
            destination.close()
        except OSError:
            pass

    to_server = threading.Thread(target=pump, args=(sys.stdin.buffer, server.stdin, CLIENT_TO_SERVER), daemon=True)
    to_client = threading.Thread(target=pump, args=(server.stdout, sys.stdout.buffer, SERVER_TO_CLIENT), daemon=True)
    to_server.start()
    to_client.start()

    # The session ends when Claude Code closes stdin; then the server exits.
    to_server.join()
    server.wait()
    to_client.join(timeout=2)
    trace.close()
    return server.returncode or 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
