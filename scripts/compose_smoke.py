"""End-to-end smoke test against a running stack (compose or local).

    python scripts/compose_smoke.py --base http://localhost:8000 [--web http://localhost:8080]

It signs in through the real PKCE flow, asks a policy question, and runs an approval round
trip through MCP. Exit status 1 means something is broken.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from record_runs import login, stream  # noqa: E402


def wait_ready(client: httpx.Client, base: str, seconds: int = 90) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if client.get(f"{base}/ready", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"gateway at {base} never became ready")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--web", default="")
    ns = ap.parse_args()
    with httpx.Client() as c:
        wait_ready(c, ns.base)
        token = login(c, ns.base, "alice")
        events = stream(c, f"{ns.base}/chat", token, {"message": "How many days of paid holiday?"})
        answer = "".join(e.get("text", "") for e in events if e["type"] == "token")
        assert "24" in answer, answer
        events = stream(
            c, f"{ns.base}/chat", token, {"message": "Create a ticket: broken chair, priority P4"}
        )
        assert events[-1]["status"] == "awaiting_approval", events[-1]
        body = {"thread_id": events[0]["thread_id"], "approved": True}
        more = stream(c, f"{ns.base}/approve", token, body)
        assert any(e["type"] == "tool_result" for e in more), more
        if ns.web:
            page = c.get(ns.web)
            assert page.status_code == 200 and "AI Engineering Stack" in page.text
    print("smoke test passed")


if __name__ == "__main__":
    main()
