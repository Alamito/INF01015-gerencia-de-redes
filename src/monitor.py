"""NetSentinel monitor: checks every target periodically and calls the AI agent
when a target goes from OK to FAIL.

Usage:
    python src/monitor.py                 run forever (every 10 s)
    python src/monitor.py --once          run a single cycle
    python src/monitor.py --no-agent      only monitor, never call the AI
    python src/monitor.py --interval 30   change the check interval (seconds)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import agent
import net_tools
from paths import PROJECT_DIR, TARGETS_FILE

DEFAULT_SLOW_THRESHOLD_MS = 2000

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def load_targets() -> list[dict]:
    # Reloaded every cycle, so targets can be enabled/disabled while the monitor runs.
    targets = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return [target for target in targets if target.get("enabled", True)]


def check_target(target: dict) -> tuple[bool, str]:
    """Run the health check for a target. Returns (ok, short description)."""
    kind = target["type"]
    if kind == "ping":
        data = json.loads(net_tools.ping(target["host"]))
        if data["ok"]:
            return True, f"{data['latency_ms']} ms, {data['loss_pct']}% loss"
        return False, f"ping to {target['host']} failed: {data.get('error')}"

    if kind == "tcp":
        data = json.loads(net_tools.check_port(target["host"], target["port"]))
        if data["ok"]:
            return True, f"port {target['port']} open"
        return False, f"TCP {target['host']}:{target['port']} is {data['state']}: {data.get('error')}"

    if kind == "http":
        data = json.loads(net_tools.check_http(target["url"]))
        if not data["ok"]:
            detail = f"HTTP {data['status']}" if "status" in data else data.get("error")
            return False, f"GET {target['url']} failed: {detail}"
        threshold = target.get("slow_threshold_ms", DEFAULT_SLOW_THRESHOLD_MS)
        if data["time_ms"] > threshold:
            return False, f"GET {target['url']} too slow: {data['time_ms']} ms (threshold {threshold} ms)"
        return True, f"HTTP {data['status']} in {data['time_ms']} ms"

    return False, f"unknown target type '{kind}'"


def handle_incident(target: dict, error: str) -> None:
    print(f"{YELLOW}[agent] investigating {target['name']}...{RESET}", flush=True)
    try:
        report = agent.investigate(target, error)
    except agent.AgentError as exc:
        print(f"{RED}[agent] {exc}{RESET}")
        return

    ok, detail = check_target(target)
    verification = f"OK ({detail})" if ok else f"still failing ({detail})"
    report += f"\n\n### Verificação do monitor\n{verification}"
    path = agent.save_report(target["name"], report)

    print(f"\n{report}\n")
    print(f"{GREEN if ok else RED}[monitor] verification: {verification}{RESET}")
    print(f"{DIM}[monitor] report saved to {path.relative_to(PROJECT_DIR)}{RESET}\n")


def run_cycle(previous: dict[str, bool], use_agent: bool) -> None:
    targets = load_targets()
    # Forget disabled targets, so re-enabling one counts as a fresh start.
    active_names = {target["name"] for target in targets}
    for name in list(previous):
        if name not in active_names:
            del previous[name]
    print(f"{DIM}[{datetime.now():%H:%M:%S}] checking {len(targets)} targets...{RESET}")
    incidents = []
    for target in targets:
        ok, detail = check_target(target)
        label = f"{GREEN}[OK]  {RESET}" if ok else f"{RED}[FAIL]{RESET}"
        print(f"  {label} {target['name']:<12} {detail}")
        # Only a transition OK -> FAIL triggers the agent (unknown counts as OK).
        if not ok and previous.get(target["name"], True):
            incidents.append((target, detail))
        previous[target["name"]] = ok

    for target, detail in incidents:
        print(f"{RED}[monitor] ALERT: {target['name']}: {detail}{RESET}")
        if use_agent:
            handle_incident(target, detail)
            previous[target["name"]] = check_target(target)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="NetSentinel network monitor")
    parser.add_argument("--once", action="store_true", help="run a single check cycle")
    parser.add_argument("--no-agent", action="store_true", help="never call the AI agent")
    parser.add_argument("--interval", type=int, default=10, help="seconds between cycles")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        os.system("")  # enables ANSI colors in the classic Windows console

    previous: dict[str, bool] = {}
    try:
        while True:
            run_cycle(previous, use_agent=not args.no_agent)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[monitor] stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
