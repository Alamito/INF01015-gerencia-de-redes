"""Fake lab services used to simulate network incidents.

The services live inside a controller process that you keep running in its own
terminal; the other commands (and the agent's restart_service tool) send orders
to it over a local control port.

Usage:
    python src/lab.py run                start the controller with every service up (Ctrl+C to quit)
    python src/lab.py start [web|db]     start a service (all if omitted)
    python src/lab.py stop [web|db]      stop a service (all if omitted)
    python src/lab.py slow               put the web service in slow mode (5 s per response)
    python src/lab.py dns-fail           enable the target whose domain does not resolve
    python src/lab.py dns-ok             disable that target again
    python src/lab.py status             show the state of every service and of the DNS scenario
"""

import json
import socket
import socketserver
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from paths import TARGETS_FILE

HOST = "127.0.0.1"
SERVICES = {"web": 8080, "db": 6543}
CONTROL_PORT = 8099
SLOW_DELAY_S = 5
# Target in config/targets.json used by the DNS scenario (its domain does not exist).
DNS_TARGET = "broken-dns"

# On Windows, SO_REUSEADDR lets two sockets bind the same port, so keep it off there.
REUSE_ADDRESS = sys.platform != "win32"


class LabControllerError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public API (used by net_tools.py and the CLI)
# ---------------------------------------------------------------------------

def start(name: str, slow: bool = False, source: str = "cli") -> bool:
    """Start a lab service. Returns True when the service is accepting connections."""
    return _send({"cmd": "start", "name": name, "slow": slow, "source": source})["ok"]


def stop(name: str, source: str = "cli") -> bool:
    """Stop a lab service. Returns True when the service is no longer listening."""
    return _send({"cmd": "stop", "name": name, "source": source})["ok"]


def slow(name: str, source: str = "cli") -> bool:
    """Restart a lab service in slow mode (only the web service supports it)."""
    if name != "web":
        return False
    return start(name, slow=True, source=source)


def restart(name: str, source: str = "cli") -> bool:
    """Stop and start a lab service in normal mode."""
    return _send({"cmd": "restart", "name": name, "source": source})["ok"]


def status() -> dict:
    """Return the state of each lab service, e.g. {"web": "running", "db": "stopped"}."""
    return {
        name: "running" if _is_port_open(port) else "stopped"
        for name, port in SERVICES.items()
    }


def is_slow(name: str) -> bool:
    try:
        return name in _send({"cmd": "slow_services"})["slow"]
    except LabControllerError:
        return False


def set_dns_failure(active: bool) -> bool:
    """Enable or disable the DNS scenario target. Works without the controller,
    because the monitor reloads config/targets.json on every cycle."""
    targets = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    target = next((t for t in targets if t.get("name") == DNS_TARGET), None)
    if target is None:
        return False
    target["enabled"] = active
    # One target per line, the same layout used in the file.
    lines = ",\n".join("  " + json.dumps(t, ensure_ascii=False) for t in targets)
    TARGETS_FILE.write_text(f"[\n{lines}\n]\n", encoding="utf-8", newline="\n")
    return True


def is_dns_failure_active() -> bool:
    targets = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return any(t.get("name") == DNS_TARGET and t.get("enabled", True) for t in targets)


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------

def _send(request: dict) -> dict:
    name = request.get("name")
    if name is not None and name not in SERVICES:
        raise ValueError(f"unknown lab service '{name}' (valid: {', '.join(SERVICES)})")
    try:
        with socket.create_connection((HOST, CONTROL_PORT), timeout=10) as conn:
            conn.sendall((json.dumps(request) + "\n").encode())
            response = conn.makefile("r", encoding="utf-8").readline()
    except OSError as exc:
        raise LabControllerError("lab controller is not running (start it with: python src/lab.py run)") from exc
    return json.loads(response)


def _is_port_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

class _WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.server.slow_mode:
            time.sleep(SLOW_DELAY_S)
        body = b"<html><body><h1>NetSentinel lab web service: OK</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class _WebServer(ThreadingHTTPServer):
    allow_reuse_address = REUSE_ADDRESS
    daemon_threads = True
    slow_mode = False


class _DbHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"NETSENTINEL-DB READY\r\n")


class _DbServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = REUSE_ADDRESS
    daemon_threads = True
    slow_mode = False


# ---------------------------------------------------------------------------
# Controller (python src/lab.py run)
# ---------------------------------------------------------------------------

class _Controller:
    def __init__(self):
        self.servers: dict[str, socketserver.BaseServer] = {}
        self.lock = threading.Lock()

    def start(self, name: str, slow_mode: bool = False) -> bool:
        with self.lock:
            current = self.servers.get(name)
            if current and current.slow_mode == slow_mode:
                return True
            if current:
                self._shutdown(name)
            server_class, handler = (_WebServer, _WebHandler) if name == "web" else (_DbServer, _DbHandler)
            try:
                server = server_class((HOST, SERVICES[name]), handler)
            except OSError as exc:
                _log(f"{name}: cannot listen on port {SERVICES[name]}: {exc}")
                return False
            server.slow_mode = slow_mode
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers[name] = server
            return True

    def stop(self, name: str) -> bool:
        with self.lock:
            self._shutdown(name)
            return True

    def _shutdown(self, name: str) -> None:
        server = self.servers.pop(name, None)
        if server:
            server.shutdown()
            server.server_close()

    def handle(self, request: dict) -> dict:
        cmd, name, source = request.get("cmd"), request.get("name"), request.get("source", "cli")
        if cmd == "slow_services":
            return {"ok": True, "slow": [n for n, s in self.servers.items() if s.slow_mode]}
        if name not in SERVICES:
            return {"ok": False, "error": f"unknown service {name!r}"}
        if cmd == "start":
            slow_mode = bool(request.get("slow"))
            ok = self.start(name, slow_mode)
            _log(f"{name} {'started in SLOW mode' if slow_mode else 'started'} (by {source})" if ok else f"{name} failed to start")
        elif cmd == "stop":
            ok = self.stop(name)
            _log(f"{name} stopped (by {source})")
        elif cmd == "restart":
            self.stop(name)
            ok = self.start(name)
            _log(f"{name} restarted (by {source})" if ok else f"{name} failed to restart")
        else:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        return {"ok": ok}


class _ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline())
            response = self.server.controller.handle(request)
        except ValueError:
            response = {"ok": False, "error": "invalid request"}
        self.wfile.write((json.dumps(response) + "\n").encode())


class _ControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = REUSE_ADDRESS
    daemon_threads = True


def _log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def run_controller() -> int:
    controller = _Controller()
    try:
        control = _ControlServer((HOST, CONTROL_PORT), _ControlHandler)
    except OSError as exc:
        print(f"error: cannot open control port {CONTROL_PORT} (is the lab already running?): {exc}")
        return 1
    control.controller = controller
    threading.Thread(target=control.serve_forever, daemon=True).start()

    for name in SERVICES:
        if controller.start(name):
            _log(f"{name} listening on {HOST}:{SERVICES[name]}")
    _log(f"lab controller ready on {HOST}:{CONTROL_PORT} (Ctrl+C to quit)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _log("shutting down lab")
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_status() -> None:
    for name, state in status().items():
        mode = " (slow)" if state == "running" and is_slow(name) else ""
        print(f"  {name:<4} {HOST}:{SERVICES[name]:<5} {state}{mode}")
    dns_state = "failing (target enabled)" if is_dns_failure_active() else "ok (target disabled)"
    print(f"  dns  {DNS_TARGET:<15} {dns_state}")


def main(argv: list[str]) -> int:
    commands = ("run", "start", "stop", "slow", "dns-fail", "dns-ok", "status")
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 1

    command = argv[0]
    if command == "run":
        return run_controller()
    if command == "status":
        _print_status()
        return 0
    if command in ("dns-fail", "dns-ok"):
        ok = set_dns_failure(command == "dns-fail")
        print(f"  {command}: {'ok' if ok else f'target {DNS_TARGET!r} not found in {TARGETS_FILE.name}'}")
        _print_status()
        return 0 if ok else 1

    names = argv[1:] or (["web"] if command == "slow" else list(SERVICES))
    success = True
    for name in names:
        try:
            ok = {"start": start, "stop": stop, "slow": slow}[command](name)
        except (ValueError, LabControllerError) as exc:
            print(f"error: {exc}")
            return 1
        if command == "slow" and name != "web":
            print(f"  {name}: slow mode is only supported by the web service")
        else:
            print(f"  {command} {name}: {'ok' if ok else 'failed'}")
        success = success and ok
    _print_status()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
