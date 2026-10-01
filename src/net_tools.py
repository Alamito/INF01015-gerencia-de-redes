"""Network diagnostic tools.

Plain Python functions used by both the monitor and the AI agent (through the MCP
server). Every function returns a JSON string that always contains the key "ok".
The docstrings are what the AI reads to decide which tool to use, so keep them clear.
"""

import json
import platform
import re
import socket
import subprocess
import sys
import time

import requests
import truststore

import lab

# Use the operating system certificate store (some sites, like ufrgs.br, send an
# incomplete certificate chain that only the OS store can complete).
truststore.inject_into_ssl()

IS_WINDOWS = platform.system() == "Windows"
CONSOLE_ENCODING = "oem" if IS_WINDOWS else "utf-8"
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-:]*$")
REPLY_TIME_PATTERN = re.compile(r"[=<]\s*([\d.,]+)\s*ms", re.IGNORECASE)
PING_COUNT = 4


def _result(ok: bool, **fields) -> str:
    return json.dumps({"ok": ok, **fields}, ensure_ascii=False)


def _invalid_host(host: str) -> str | None:
    if not HOST_PATTERN.match(host or ""):
        return _result(False, error=f"invalid host: {host!r}")
    return None


def _run(args: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding=CONSOLE_ENCODING,
        errors="replace",
        timeout=timeout_s,
        stdin=subprocess.DEVNULL,
    )


def ping(host: str) -> str:
    """Send 4 ICMP echo requests to a host (network layer reachability).

    Returns packet loss percentage and average latency. Use it to check whether
    a host is reachable at all, before testing ports or applications.

    Args:
        host: Hostname or IP address, e.g. "8.8.8.8" or "www.ufrgs.br".
    """
    if error := _invalid_host(host):
        return error
    if IS_WINDOWS:
        args = ["ping", "-n", str(PING_COUNT), "-w", "1000", host]
    else:
        args = ["ping", "-c", str(PING_COUNT), "-W", "1", host]
    try:
        completed = _run(args, timeout_s=20)
    except subprocess.TimeoutExpired:
        return _result(False, host=host, error="ping timed out")

    # Reply lines contain "TTL" in every locale; parsing them avoids depending on
    # the language of the summary lines.
    reply_lines = [line for line in completed.stdout.splitlines() if "ttl" in line.lower()]
    times = []
    for line in reply_lines:
        match = REPLY_TIME_PATTERN.search(line)
        if match:
            times.append(float(match.group(1).replace(",", ".")))

    received = len(reply_lines)
    loss_pct = round(100 * (PING_COUNT - received) / PING_COUNT)
    if received == 0:
        return _result(False, host=host, loss_pct=100, error="no replies received")
    latency_ms = round(sum(times) / len(times), 1) if times else None
    return _result(True, host=host, loss_pct=loss_pct, latency_ms=latency_ms)


def dns_lookup(name: str) -> str:
    """Resolve a hostname to IP addresses using the system DNS resolver.

    Use it to check whether name resolution works. A failure here means the
    problem is DNS, not the network or the service.

    Args:
        name: Hostname to resolve, e.g. "www.ufrgs.br".
    """
    if error := _invalid_host(name):
        return error
    start = time.perf_counter()
    try:
        infos = socket.getaddrinfo(name, None)
    except socket.gaierror as exc:
        return _result(False, name=name, error=f"resolution failed: {exc}")
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    addresses = sorted({info[4][0] for info in infos})
    return _result(True, name=name, addresses=addresses, time_ms=elapsed_ms)


def check_port(host: str, port: int) -> str:
    """Try to open a TCP connection to host:port (transport layer).

    Returns state "open", "closed" (connection refused: host is up but nothing
    listens on the port, i.e. the service is down), "timeout" (filtered or host
    unreachable) or "error".

    Args:
        host: Hostname or IP address.
        port: TCP port number, e.g. 80, 443, 8080.
    """
    if error := _invalid_host(host):
        return error
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=3):
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            return _result(True, host=host, port=port, state="open", time_ms=elapsed_ms)
    except ConnectionRefusedError:
        return _result(False, host=host, port=port, state="closed", error="connection refused")
    except socket.timeout:
        return _result(False, host=host, port=port, state="timeout", error="no answer within 3 s")
    except OSError as exc:
        return _result(False, host=host, port=port, state="error", error=str(exc))


def check_http(url: str) -> str:
    """Send an HTTP GET request to a URL (application layer).

    Returns the HTTP status code and the total response time in milliseconds.
    A slow response with DNS and port working points to an application problem.

    Args:
        url: Full URL, e.g. "http://127.0.0.1:8080/" or "https://www.ufrgs.br/".
    """
    if not url.startswith(("http://", "https://")):
        return _result(False, url=url, error="url must start with http:// or https://")
    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.Timeout:
        return _result(False, url=url, error="request timed out after 10 s")
    except requests.exceptions.ConnectionError as exc:
        return _result(False, url=url, error=_describe_connection_error(exc))
    except requests.exceptions.RequestException as exc:
        return _result(False, url=url, error=str(exc))
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return _result(response.status_code < 400, url=url, status=response.status_code, time_ms=elapsed_ms)


def _describe_connection_error(exc: Exception) -> str:
    # requests nests the real cause in a long message; keep only what matters.
    text = str(exc)
    if "getaddrinfo" in text or "NameResolution" in text:
        return "connection error: name resolution failed"
    if "10061" in text or "refused" in text.lower():
        return "connection error: connection refused"
    if "SSL" in text:
        return "connection error: TLS/SSL failure"
    return f"connection error: {text[:150]}"


def traceroute(host: str) -> str:
    """Trace the route (up to 10 hops) to a host.

    Slow (can take up to a minute). Use it only when ping fails for a remote
    host, to find where along the path packets are lost.

    Args:
        host: Hostname or IP address.
    """
    if error := _invalid_host(host):
        return error
    if IS_WINDOWS:
        args = ["tracert", "-d", "-h", "10", "-w", "500", host]
    else:
        args = ["traceroute", "-n", "-m", "10", "-w", "1", host]
    try:
        completed = _run(args, timeout_s=90)
    except FileNotFoundError:
        return _result(False, host=host, error="traceroute command not available")
    except subprocess.TimeoutExpired:
        return _result(False, host=host, error="traceroute timed out")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return _result(completed.returncode == 0, host=host, output="\n".join(lines))


def restart_service(name: str) -> str:
    """Restart a lab service. Only the lab services "web" and "db" are allowed.

    Use it only when a lab service is down (port closed). It also resets the
    web service to normal (non-slow) mode.

    Args:
        name: Lab service name: "web" or "db".
    """
    if name not in lab.SERVICES:
        return _result(False, name=name, error=f"not allowed: only {list(lab.SERVICES)} can be restarted")
    try:
        restarted = lab.restart(name, source="agent")
    except lab.LabControllerError as exc:
        return _result(False, name=name, error=str(exc))
    if not restarted:
        return _result(False, name=name, error="service did not come back up")
    return _result(True, name=name, state="running", port=lab.SERVICES[name])


ALL_TOOLS = [ping, dns_lookup, check_port, check_http, traceroute, restart_service]


def main(argv: list[str]) -> int:
    """Run one tool from the terminal, e.g. python src/net_tools.py check_port 127.0.0.1 8080"""
    tools = {tool.__name__: tool for tool in ALL_TOOLS}
    if not argv or argv[0] not in tools:
        print(f"usage: python src/net_tools.py <tool> <args...>\ntools: {', '.join(tools)}")
        return 1
    print(tools[argv[0]](*argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
