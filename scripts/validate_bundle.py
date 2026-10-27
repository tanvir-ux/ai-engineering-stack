"""Validate the Databricks bundle OFFLINE against a tiny local stub of the workspace API.

`databricks bundle validate` asks the workspace who the current user is. This script answers that
single call from a throw-away server on 127.0.0.1 so the bundle schema, variable interpolation and
resource references are checked in CI without any Databricks account. It proves the bundle is
well-formed. It does NOT prove it deploys or runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parent.parent / "databricks"


class Stub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = {"id": "1", "userName": "ci@example.com", "active": True}
        if "scim" not in self.path:
            body = {"object_type": "DIRECTORY", "object_id": 1, "path": "/stub"}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_: object) -> None:
        return


def main() -> int:
    cli = shutil.which("databricks")
    if not cli:
        print("databricks CLI not found on PATH", file=sys.stderr)
        return 2
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        **os.environ,
        "DATABRICKS_HOST": f"http://127.0.0.1:{server.server_port}",
        "DATABRICKS_TOKEN": "offline-validation-not-a-secret",
    }
    code = 0
    for target in ("dev", "prod"):
        r = subprocess.run(  # noqa: S603
            [cli, "bundle", "validate", "-t", target],
            cwd=BUNDLE_DIR, env=env, capture_output=True, text=True, check=False,
        )  # fmt: skip
        print(f"--- target {target}: exit {r.returncode}")
        print((r.stderr.strip() + "\n" + r.stdout.strip()).strip())
        code = code or r.returncode
    server.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
