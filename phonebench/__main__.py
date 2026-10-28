"""Entry point.

  python -m phonebench              terminal app (default)
  python -m phonebench --web        local web UI on 127.0.0.1:8765
  python -m phonebench --doctor     toolchain + device state, then exit
  python -m phonebench --preview    render every screen as plain text (testing)
"""
from __future__ import annotations

import argparse

from . import core, jobs


def doctor() -> int:
    print(f"phonebench {__import__('phonebench').__version__}")
    print(f"app dir : {core.APP_DIR}\n")
    print("tools:")
    for name, info in core.tool_report().items():
        mark = "OK " if info["found"] else "-- "
        print(f"  [{mark}] {name:<10} {info['path'] or ''}")
    print("\ndevice:")
    d = core.scan()
    print(f"  state : {d['state']}")
    print(f"  brand : {d['brand_guess'] or '-'}")
    for k, v in (d.get("props") or {}).items():
        if v:
            print(f"  {k:<32} {v}")
    print(f"\njobs    : {len(jobs.list_jobs())}")
    print(f"ledger  : {core.APP_DIR / 'ledger.jsonl'}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="phonebench", description="phone repair workbench")
    p.add_argument("--web", action="store_true", help="serve the browser UI instead of the TUI")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="(web) do not open a browser")
    p.add_argument("--doctor", action="store_true", help="print toolchain + device state and exit")
    p.add_argument("--preview", action="store_true", help="render all screens as text and exit")
    args = p.parse_args(argv)

    if args.doctor:
        return doctor()
    if args.preview:
        from .tui import preview
        return preview()
    if args.web:
        from .server import serve
        serve(args.port, open_browser=not args.no_open)
        return 0
    from .tui import main as tui_main
    return tui_main()


if __name__ == "__main__":
    raise SystemExit(main())
