"""Entry point.

  python -m phonebench              terminal app (default)
  python -m phonebench --web        local web UI on 127.0.0.1:8765
  python -m phonebench --doctor     toolchain + device state, then exit
  python -m phonebench --preview    render every screen as plain text (testing)
  python -m phonebench --self-test  run test suite with fake devices
  python -m phonebench firmware     firmware vault management (add/list/verify/rm)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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


def self_test() -> int:
    import unittest

    repo_root = Path(__file__).resolve().parent.parent
    tests_dir = repo_root / "tests"
    fakes_dir = tests_dir / "fakes"

    old_test_mode = os.environ.get("PHONEBENCH_TEST_MODE")
    old_fake_root = os.environ.get("PHONEBENCH_FAKE_ROOT")

    os.environ["PHONEBENCH_TEST_MODE"] = "1"
    os.environ["PHONEBENCH_FAKE_ROOT"] = str(fakes_dir.resolve())

    try:
        loader = unittest.TestLoader()
        suite = loader.discover(str(tests_dir))
        runner = unittest.TextTestRunner(verbosity=1)
        result = runner.run(suite)

        runs = result.testsRun
        failures = len(result.failures)
        errors = len(result.errors)
        passed = runs - failures - errors

        if result.wasSuccessful():
            print(f"\nself-test complete: {runs} tests run, {passed} passed (0 failures, 0 errors)")
            return 0
        else:
            print(f"\nself-test failed: {runs} tests run, {passed} passed ({failures} failures, {errors} errors)", file=sys.stderr)
            return 1
    finally:
        if old_test_mode is not None:
            os.environ["PHONEBENCH_TEST_MODE"] = old_test_mode
        else:
            os.environ.pop("PHONEBENCH_TEST_MODE", None)

        if old_fake_root is not None:
            os.environ["PHONEBENCH_FAKE_ROOT"] = old_fake_root
        else:
            os.environ.pop("PHONEBENCH_FAKE_ROOT", None)


def handle_dry_run(brand: str = "generic", intent: str = "diagnose", firmware_id: str | None = None) -> int:
    import json
    from . import server

    reg_file = core.APP_DIR / "registry.json"
    registry_data = json.loads(reg_file.read_text(encoding="utf-8")).get("tools", {}) if reg_file.exists() else {}
    dev = core.scan(registry_data)

    plan = core.plan(brand, intent, {
        "tools": core.tool_report(registry_data),
        "state": dev["state"],
        "firmware_id": firmware_id,
        "firmware": firmware_id,
    })

    print(f"DRY RUN PLAN: {plan['brand_label']} - {plan['intent_label']} [risk: {plan['risk']}]")
    if plan.get("blocked"):
        print(f"BLOCKED: {plan.get('block_reason')}", file=sys.stderr)

    print("-" * 70)
    cmds = server.plan_commands(plan, {"tools": registry_data})
    for cmd in cmds:
        num = cmd.get("n", 1)
        title = cmd.get("title", "")
        kind = cmd.get("kind", "guide")
        risk = cmd.get("risk", "safe")

        if kind in ("auto", "launch") and cmd.get("argv"):
            argv_str = " ".join(cmd["argv"])
            print(f"{num}. [{risk}] {title}\n   argv: {argv_str}")
        else:
            text = cmd.get("text") or "guide only - nothing to execute"
            print(f"{num}. [{risk}] {title}\n   text: {text}")

    print("-" * 70)
    print("executed: 0")
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
    p.add_argument("--self-test", action="store_true", help="run test suite with fake devices and exit")
    p.add_argument("--dry-run", action="store_true", help="render resolved plan and argv commands without executing")
    p.add_argument("--brand", default="generic", help="brand for dry-run plan")
    p.add_argument("--intent", default="diagnose", help="intent for dry-run plan")
    p.add_argument("--firmware", help="firmware ID or path for dry-run plan")

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

    if args.dry_run:
        return handle_dry_run(args.brand, args.intent, args.firmware)
    if args.self_test:
        return self_test()
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
