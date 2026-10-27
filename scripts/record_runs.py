"""Record real runs of the full stack (mock IdP -> gateway -> LangGraph -> agent -> MCP -> data).

Start the stack first (`make dev-stack`), then:

    python scripts/record_runs.py --base http://localhost:8010 --out frontend/public/recordings

Each scenario signs in through the real OIDC authorization-code + PKCE flow, calls the API, and
stores every server-sent event with its arrival time. The static demo replays these files.
The events are exactly what the gateway streamed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

REDIRECT = "http://localhost:5173/callback"

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "holiday",
        "title": "Ask a policy question",
        "persona": "alice",
        "question": "How many days of paid holiday does a full-time employee get each year?",
        "blurb": "Retrieval-augmented answer with citations. Alice is an ordinary employee.",
    },
    {
        "id": "acl-denied",
        "title": "Same question, wrong role",
        "persona": "alice",
        "question": "What are the salary bands for Level 4?",
        "blurb": (
            "The answer lives in an HR-only document. Alice cannot read it, "
            "so it is never retrieved."
        ),
    },
    {
        "id": "acl-allowed",
        "title": "Same question, right role",
        "persona": "bob",
        "question": "What are the salary bands for Level 4?",
        "blurb": "Bob has the HR role, so the HR-only document is retrieved and cited.",
    },
    {
        "id": "ticket-approval",
        "title": "Take an action, with human approval",
        "persona": "alice",
        "question": "Create a ticket: VPN keeps disconnecting every hour, priority P2",
        "approve": True,
        "blurb": "The workflow pauses before a write action. A human approves, then it continues.",
    },
    {
        "id": "ticket-declined",
        "title": "Decline the action",
        "persona": "alice",
        "question": "Create a ticket: replace my broken keyboard, priority P3",
        "approve": False,
        "blurb": "If the human declines, nothing is written.",
    },
    {
        "id": "tool-denied",
        "title": "Per-user tool permission",
        "persona": "hugo",
        "question": "Create a ticket: need access to the shared drive, priority P3",
        "blurb": (
            "Hugo is an employee, but a per-user rule denies him ticket creation. "
            "It is refused before approval is even asked."
        ),
    },
    {
        "id": "security-stats",
        "title": "Role-gated analytics tool",
        "persona": "dave",
        "question": "Show me the ticket statistics",
        "blurb": (
            "Only the security role may call the ticket statistics tool, which is served over MCP."
        ),
    },
]


def login(client: httpx.Client, base: str, persona: str) -> str:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    q = {
        "response_type": "code",
        "client_id": "aistack-web",
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": secrets.token_hex(8),
        "login_hint": persona,
    }
    r = client.get(f"{base}/idp/authorize", params=q, follow_redirects=False)
    if r.status_code != 302:
        r.raise_for_status()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["code"][0]
    t = client.post(
        f"{base}/idp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "aistack-web",
            "redirect_uri": REDIRECT,
        },
    )
    t.raise_for_status()
    return str(t.json()["access_token"])


def stream(
    client: httpx.Client, url: str, token: str, body: dict[str, Any]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    headers = {"Authorization": f"Bearer {token}"}
    with client.stream("POST", url, json=body, headers=headers, timeout=60) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                ev["t_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                events.append(ev)
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8010")
    ap.add_argument("--out", default="frontend/public/recordings")
    ns = ap.parse_args()
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    with httpx.Client() as client:
        personas = {p["id"]: p for p in client.get(f"{ns.base}/idp/personas").json()}
        for sc in SCENARIOS:
            token = login(client, ns.base, sc["persona"])
            auth = {"Authorization": f"Bearer {token}"}
            me = client.get(f"{ns.base}/me", headers=auth).json()
            events = stream(client, f"{ns.base}/chat", token, {"message": sc["question"]})
            segments = [{"phase": "chat", "events": events}]
            if events[-1].get("status") == "awaiting_approval" and "approve" in sc:
                body = {"thread_id": events[0]["thread_id"], "approved": bool(sc["approve"])}
                more = stream(client, f"{ns.base}/approve", token, body)
                phase = "approve" if sc["approve"] else "decline"
                segments.append({"phase": phase, "events": more})
            rec = {
                "id": sc["id"],
                "title": sc["title"],
                "blurb": sc["blurb"],
                "persona": {
                    **personas[sc["persona"]],
                    "document_classes": me["document_classes"],
                    "tools": me["tools"],
                },
                "question": sc["question"],
                "segments": segments,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "note": "The model is the deterministic fake.",
            }
            (out / f"{sc['id']}.json").write_text(json.dumps(rec, indent=2))
            index.append(
                {k: rec[k] for k in ("id", "title", "blurb", "question")}
                | {"persona": sc["persona"]}
            )
            print(f"recorded {sc['id']}: {[s['phase'] for s in segments]}")
    (out / "index.json").write_text(json.dumps(index, indent=2))
    (out / "personas.json").write_text(json.dumps(list(personas.values()), indent=2))


if __name__ == "__main__":
    main()
