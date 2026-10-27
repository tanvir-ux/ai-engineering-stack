"""Command line entry point: `aistack <command>`.

aistack serve   run the API gateway (and the mock IdP) on :8000
aistack mcp     run the MCP server on :8001
aistack data    run the PySpark pipeline (needs the `spark` extra)
aistack eval    run the retrieval evaluation and write the report
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="aistack", description=__doc__)
    ap.add_argument("command", choices=["serve", "mcp", "data", "eval"])
    ns, rest = ap.parse_known_args(args)
    if ns.command == "serve":
        import uvicorn

        sp = argparse.ArgumentParser(prog="aistack serve")
        sp.add_argument("--host", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=8000)
        a = sp.parse_args(rest)
        uvicorn.run("aistack.gateway.app:create_app", factory=True, host=a.host, port=a.port)
    elif ns.command == "mcp":
        from aistack.mcp_tools.server import main as mcp_main

        sys.argv = ["aistack mcp", *rest]
        mcp_main()
    elif ns.command == "data":
        from aistack.data.spark_pipeline import main as data_main

        sys.argv = ["aistack data", *rest]
        data_main()
    else:
        from aistack.eval.rag_eval import main as eval_main

        sys.argv = ["aistack eval", *rest]
        eval_main()


if __name__ == "__main__":
    main()
