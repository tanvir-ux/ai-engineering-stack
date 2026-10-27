"""Generate the synthetic IT ticket extract (seeded, so it is byte-identical on every run).

It deliberately contains a few duplicate rows and invalid rows so the PySpark pipeline has real
cleaning and quarantine work to do.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "tickets.csv"
REQUESTERS = [
    "alice.nguyen@meridian.example",
    "bob.fischer@meridian.example",
    "carol.silva@meridian.example",
    "dave.okafor@meridian.example",
    "eve.contractor@meridian.example",
    "farid.rahman@meridian.example",
    "grace.lee@meridian.example",
    "hugo.martin@meridian.example",
]
CATEGORIES = {
    "hardware": ["Laptop battery drains in two hours", "Docking station not detected", "Monitor flickers"],
    "access": ["Cannot sign in after password change", "Need access to shared drive", "MFA token lost"],
    "software": ["Request for diagramming tool licence", "Spreadsheet add-in crashes", "Email client sync error"],
    "network": ["VPN disconnects every hour", "Wi-Fi slow in meeting room 3", "Cannot reach warehouse portal"],
}
PRIORITIES = ["P1", "P2", "P3", "P4"]
STATUSES = ["open", "in_progress", "resolved", "closed"]


def main() -> None:
    rnd = random.Random(20261027)
    base = datetime(2026, 7, 1, 8, 0)
    rows: list[dict[str, str]] = []
    for i in range(300):
        cat = rnd.choice(list(CATEGORIES))
        created = base + timedelta(hours=rnd.randint(0, 24 * 100))
        status = rnd.choices(STATUSES, weights=[2, 2, 3, 4])[0]
        resolved = ""
        if status in ("resolved", "closed"):
            resolved = (created + timedelta(hours=rnd.randint(1, 96))).isoformat(sep=" ")
        rows.append(
            {
                "ticket_id": f"INC-{1001 + i}",
                "requester": rnd.choice(REQUESTERS),
                "category": cat,
                "priority": rnd.choices(PRIORITIES, weights=[1, 3, 5, 3])[0],
                "status": status,
                "created_at": created.isoformat(sep=" "),
                "resolved_at": resolved,
                "summary": rnd.choice(CATEGORIES[cat]),
            }
        )
    rows += [dict(r) for r in rows[10:14]]  # exact duplicates
    bad = dict(rows[20])
    bad.update(ticket_id="INC-9001", priority="P9")  # invalid priority
    rows.append(bad)
    bad2 = dict(rows[21])
    bad2.update(ticket_id="", summary="")  # missing id
    rows.append(bad2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
