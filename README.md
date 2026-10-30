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
| **Intake** | Device record: brand, model, serial, fault, note. Ownership is **attested, not stored** — you check the identity document and the proof of purchase in person; the app records only that you did, when, and by whom |
| **Workflow** | 8 intents × 7 brands. Every step tagged `safe` / `caution` / `destructive`, with the rules that matter for that brand |
| **Vault** | Local firmware library: packages with model, size, hash, and green/red model-match indicators against attached device |
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

1. A device job with brand and model.
2. Your attestation that you checked a government ID and a proof of purchase, in person.
3. Brand and model matching the request — and the attached device, when adb can read it.
4. Typing `RUN` in the confirmation dialog.

Read-only diagnosis runs freely. Nothing that writes executes silently.

## Privacy

The bench stores **no client data**: no names, no ID numbers, no receipt
numbers, no scans, no addresses. A job is a device record. The attestation is a
boolean plus a timestamp — enough to show due diligence, worthless to a thief.

Runtime data lives in `%LOCALAPPDATA%\phonebench\` and holds device models,
serials, faults and operation logs. Keep it that way.

## Firmware Vault

Local library of stock firmware packages. Firmware binaries are registered locally and stored under `%LOCALAPPDATA%\phonebench\firmware\`. Binaries are **never** committed to the repository.

```
pb firmware add <path> [--no-copy] [--model <model>]   # register firmware
pb firmware list                                       # list vault packages
pb firmware verify <id> [--full]                      # verify hash integrity
pb firmware rm <id>                                   # remove package from vault
```

Features:
- Streaming SHA-256 computation in 8 MB chunks (handles multi-GB packages without loading into RAM).
- Automatic model and codename extraction from `android-info.txt` in zips, `AP_*.tar.md5` filenames, scatter files, and IPSW files.
- `--no-copy` option to reference packages in place.
- Fast verification via size and mtime checks, with full SHA-256 recalculation on demand or on file change.
- Execution block: flashing steps verify package hash integrity and refuse to execute if a package was tampered with or modified.

## Layout

```
phonebench/
  core.py      tool discovery · USB/adb/fastboot scan · brand model · planner
  firmware.py  firmware vault · SHA-256 hashing · manifest management
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

## Roadmap

The authoritative plan - priorities, hard rules, non-goals and the definition
of done - is [`docs/master-brief.md`](docs/master-brief.md). `docs/jules-brief.md`
is kept for history only.

## License

MIT for the code in this repository.
