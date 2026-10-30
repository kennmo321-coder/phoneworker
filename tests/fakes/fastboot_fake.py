"""Fake Fastboot executable for testing."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def get_state() -> dict:
    state_file = os.environ.get("PHONEBENCH_FAKE_STATE_FILE")
    if not state_file:
        fake_root = os.environ.get("PHONEBENCH_FAKE_ROOT")
        if fake_root:
            state_file = str(Path(fake_root) / "state.json")
    if not state_file or not Path(state_file).exists():
        raise SystemExit(
            "fake fastboot: no state file. Set PHONEBENCH_FAKE_STATE_FILE or add "
            "state.json under PHONEBENCH_FAKE_ROOT. Refusing to invent a device."
        )
    try:
        return json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"fake fastboot: unreadable state file {state_file}: {exc}")


def main(argv: list[str]) -> int:
    args = argv[1:]
    state = get_state()
    st = state.get("state", "none")

    if not args:
        print("fastboot version 33.0.3")
        return 0

    cmd = args[0]

    if cmd == "devices":
        if st == "fastboot":
            serial = state.get("serial", "fake_fb_serial_456")
            print(f"{serial}\tfastboot")
        return 0

    if cmd in ("update", "flashall", "flashing"):
        print(f"fake fastboot {cmd} complete")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
