# phoneworker

A phone repair workbench for a shop counter. Diagnostics, stock firmware
flashing, restore/unbrick, backups, and FRP — behind a mandatory ownership gate.

Terminal first. No dependencies, no cloud, no telemetry. Python 3.10+.

```
python -m phonebench            # terminal app
python -m phonebench --web      # same thing in a browser at 127.0.0.1:8765
python -m phonebench --doctor   # toolchain + device state, then exit
```

## Screens

| Screen | What it does |
|---|---|
| **Bench** | Live device state — `adb` / `fastboot` / EDL / preloader — model, Android version, battery, serial. Toolchain status for 16 tools. `i` installs Google's official platform-tools. Resource directory for the open-source stack |
| **Intake** | Ownership gate: client name, ID type + number, receipt, 15-digit IMEI, brand, model, signed declaration. Writes `jobs/<id>.json` |
| **Workflow** | 8 intents × 7 brands. Every step tagged `safe` / `caution` / `destructive`, with the rules that matter for that brand |
| **Ledger** | Every job and every operation, append-only, timestamped |
| **Help** | Keys, gate rules, per-brand safety |

Intents: `diagnose` · `backup` · `flash` · `restore` · `frp` · `wipe` · `bootloader` · `recovery`

## Keys

```
↑ ↓       move            ← →    change brand
tab       next screen     enter  next field / build plan
x         execute         r      rescan
i         install platform-tools  q  quit
```

## The gate

Execution requires all of:

1. A job with name, ID type + number, receipt, IMEI (15 digits), brand, model.
2. `ownership_declared = true`, set at intake.
3. Brand and model matching the request — and the attached device, when adb can read it.
4. Typing `RUN` in the confirmation dialog.

Read-only diagnosis runs freely. Nothing that writes executes silently.

## Layout

```
phonebench/
  core.py      tool discovery · USB/adb/fastboot scan · brand model · planner
  jobs.py      ownership gate · job records · ledger
  tui.py       terminal interface
  server.py    optional web interface (same rules)
  ui.html      web UI
  __main__.py  CLI entry
```

Runtime data lives in `%LOCALAPPDATA%\phonebench\` — jobs, ledger, backups,
tool index. Nothing is written into the checkout.

## Tools it drives

Odin · Heimdall · MiFlash · SP Flash Tool · mtkclient · QFIL · edl · LGUP ·
HiSuite · Emma · 3uTools · scrcpy · adb · fastboot

Missing tools are reported, not faked. Pin a path manually in
`%LOCALAPPDATA%\phonebench\registry.json`:

```json
{ "tools": { "odin": "C:\\Odin3\\Odin3.exe" } }
```

## Safety model

- The app never downloads firmware. It tells you which build to get and which
  rule will bite if you get it wrong.
- FRP is an ordered path: owner credentials → vendor service → licensed
  server-side unlock → combination firmware as a last resort.
- It never recommends writing `persist`, `efs`, or `nvram`.
- MTK: `Download Only`, never `Format All + Download`.
- Qualcomm: back up with `edl` before writing.

## License

MIT for the code in this repository.
