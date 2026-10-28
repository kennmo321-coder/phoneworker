"""Entry point.

  python -m phonebench              terminal app (default)
  python -m phonebench --web        local web UI on 127.0.0.1:8765
  python -m phonebench --doctor     toolchain + device state, then exit
  python -m phonebench --preview    render every screen as plain text (testing)
  python -m phonebench firmware     firmware vault management (add/list/verify/rm)
"""
from __future__ import annotations

import argparse
import sys

from . import core, firmware, jobs


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


def handle_firmware_cli(args: argparse.Namespace) -> int:
    cmd = args.fw_command
    if cmd == "add":
        res = firmware.add_firmware(args.path, copy=not args.no_copy, model_hint=args.model)
        if res.get("ok"):
            fw = res["firmware"]
            print(f"Added firmware package {fw['id']} ({fw['model_hint']}) - {fw['size']} bytes")
            print(f"Path: {fw['path']}")
            return 0
        else:
            print(f"Error: {res.get('error')}", file=sys.stderr)
            return 1

    elif cmd == "list":
        res = firmware.list_firmware()
        if not res.get("ok"):
            print(f"Error: {res.get('error')}", file=sys.stderr)
            return 1
        pkgs = res.get("packages", [])
        if not pkgs:
            print("No firmware packages registered in vault.")
            return 0
        print(f"{'ID':<14} {'MODEL':<16} {'SIZE':<12} {'COPIED':<8} {'FILENAME'}")
        print("-" * 70)
        for p in pkgs:
            copied_str = "yes" if p.get("copied") else "no"
            print(f"{p['id']:<14} {p.get('model_hint',''):<16} {p.get('size',0):<12} {copied_str:<8} {p.get('filename','')}")
        return 0

    elif cmd == "verify":
        res = firmware.verify_firmware(args.id, full=args.full)
        if res.get("ok"):
            method = "fast check (size + mtime)" if res.get("fast") else "full SHA-256 hash"
            print(f"OK: Package '{args.id}' verified ({method}).")
            return 0
        else:
            print(f"FAIL: {res.get('error')}", file=sys.stderr)
            return 1

    elif cmd == "rm":
        res = firmware.remove_firmware(args.id)
        if res.get("ok"):
            print(f"Removed firmware package {res['id']}.")
            return 0
        else:
            print(f"Error: {res.get('error')}", file=sys.stderr)
            return 1

    print("Usage: python -m phonebench firmware {add|list|verify|rm} ...", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="phonebench", description="phone repair workbench")
    p.add_argument("--web", action="store_true", help="serve the browser UI instead of the TUI")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="(web) do not open a browser")
    p.add_argument("--doctor", action="store_true", help="print toolchain + device state and exit")
    p.add_argument("--preview", action="store_true", help="render all screens as text and exit")

    subparsers = p.add_subparsers(dest="subcommand")

    fw_p = subparsers.add_parser("firmware", help="firmware vault management")
    fw_sub = fw_p.add_subparsers(dest="fw_command")

    add_p = fw_sub.add_parser("add", help="register a firmware package")
    add_p.add_argument("path", help="path to firmware package")
    add_p.add_argument("--no-copy", action="store_true", help="reference file in place without copying")
    add_p.add_argument("--model", help="explicit model/codename hint")

    list_p = fw_sub.add_parser("list", help="list registered firmware packages")

    verify_p = fw_sub.add_parser("verify", help="verify package integrity")
    verify_p.add_argument("id", help="firmware package ID or prefix")
    verify_p.add_argument("--full", action="store_true", help="force full SHA-256 calculation")

    rm_p = fw_sub.add_parser("rm", help="remove a firmware package")
    rm_p.add_argument("id", help="firmware package ID or prefix")

    args = p.parse_args(argv)

    if args.subcommand == "firmware":
        return handle_firmware_cli(args)
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
