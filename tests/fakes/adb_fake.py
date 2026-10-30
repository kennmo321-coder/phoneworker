"""Fake ADB executable for testing."""
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
            "fake adb: no state file. Set PHONEBENCH_FAKE_STATE_FILE or add "
            "state.json under PHONEBENCH_FAKE_ROOT. Refusing to invent a device."
        )
    try:
        return json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"fake adb: unreadable state file {state_file}: {exc}")


def main(argv: list[str]) -> int:
    args = argv[1:]
    state = get_state()
    st = state.get("state", "none")

    if not args:
        print("Android Debug Bridge version 1.0.41")
        return 0

    cmd = args[0]

    if cmd == "devices":
        print("List of devices attached")
        if st == "adb":
            serial = state.get("serial", "fake_serial_123")
            dev_st = state.get("device_state", "device")
            model = (state.get("props") or {}).get("ro.product.model", "Pixel_6a").replace(" ", "_")
            dev = (state.get("props") or {}).get("ro.product.device", "bluejay")
            print(f"{serial} {dev_st} product:{dev} model:{model} device:{dev} transport_id:1")
        elif st == "unauthorized":
            serial = state.get("serial", "fake_serial_123")
            print(f"{serial} unauthorized usb:1-1 product:unknown model:unknown device:unknown transport_id:1")
        return 0

    if cmd == "kill-server":
        return 0

    if cmd == "shell":
        sub = args[1] if len(args) > 1 else ""
        if sub == "getprop":
            prop = args[2] if len(args) > 2 else ""
            val = (state.get("props") or {}).get(prop, "")
            print(val)
            return 0
        if sub == "dumpsys" and len(args) > 2 and args[2] == "battery":
            bat = (state.get("props") or {}).get("battery", "85")
            print(f"""Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 500000
  Max charging voltage: 5000000
  Charge counter: 2500000
  status: 2
  health: 2
  present: true
  level: {bat}
  scale: 100
  voltage: 4120
  temperature: 285
  technology: Li-ion""")
            return 0
        if sub == "df":
            print("Filesystem           1K-blocks      Used Available Use% Mounted on")
            print("/dev/block/dm-5       59230588  12345678  46884910  21% /data")
            return 0
        if sub == "pm" and len(args) > 2 and args[2] == "list":
            print("package:com.android.settings")
            print("package:com.android.systemui")
            return 0

    if cmd == "pull":
        print("fake adb pull complete")
        return 0

    if cmd == "reboot":
        print("rebooting fake device")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
