# phonebench

A local repair workbench for phones. Terminal first, optional browser UI on
127.0.0.1, no internet needed after your tools are installed, no third-party
Python packages.

```
phonebench/
  core.py      tool discovery, USB/adb/fastboot scanning, brand knowledge, planner
  firmware.py  firmware vault: register, hash, verify, tamper detection
  jobs.py      attestation gate, device records, append-only ledger
  tui.py       full-screen terminal UI
  server.py    optional local HTTP app (127.0.0.1 only)
  ui.html      single-page interface for --web
  __main__.py  CLI entry
  start.bat    double-click launcher
```

## Run

```powershell
cd path\to\phoneworker
python -m phonebench                 # terminal UI
python -m phonebench --web           # browser UI on http://127.0.0.1:8765
python -m phonebench --doctor        # toolchain + device state, then exit
python -m phonebench --self-test     # test suite against fake devices
python -m phonebench --dry-run --brand google --intent flash   # argv only
```

Or double-click `phonebench\start.bat`.

## Screens

| Screen | Purpose |
|---|---|
| Bench | Live device state (adb / fastboot / EDL / preloader), toolchain status, one-click install of Google's official platform-tools, open-source resource directory |
| Intake | Device record: brand, model, serial, fault, note. Ownership is **attested, not stored** - you look at the ID and the receipt in person and tick two boxes. No name, no ID number, no receipt number, no scan is written anywhere |
| Workflow | Per-brand, per-intent plan with a risk rating and the safety rules that matter for that brand. `x` runs only with a job, a passing gate, and a typed confirmation |
| Vault | Firmware library: packages with model, size, SHA-256, and a match indicator against the attached device. A tampered file blocks the plan |
| Ledger | Every job and every operation, append-only, timestamped |
| Help | Keys, gate rules, per-brand safety |

## Intents

`diagnose` - `backup` - `flash` - `restore` - `frp` - `wipe` - `bootloader` - `recovery`

## The gate

`x` (execute) requires all of:

1. A job record with a brand and a model - a device record, nothing about the client.
2. Your attestation that you saw a government-issued ID and a proof of purchase, in person, with no copies retained. Stored as two booleans, a timestamp and optional operator initials.
3. Brand and model matching the request, and the attached device when adb can read it.
4. The referenced firmware verified against its registered SHA-256, when a vault package is selected.
5. Typing `RUN` in the confirmation dialog.

Read-only diagnosis runs without any of this. Anything that writes goes
through the gate.

## Data

```
%LOCALAPPDATA%\phonebench\
  jobs\<job-id>.json     one file per device job
  ledger.jsonl           append-only audit trail
  firmware\<id>-<model>\  registered firmware packages
  registry.json          optional manual tool pins
  tool_index.json        24h tool discovery cache
  platform-tools\        adb/fastboot if bootstrapped from Google
```

## Tools it drives

Odin, Heimdall, MiFlash, SP Flash Tool, mtkclient, QFIL, edl, LGUP, HiSuite,
Emma, 3uTools, scrcpy, adb, fastboot. Missing tools are reported, never faked.
Only `adb`, `fastboot`, `heimdall`, `mtkclient` and `edl` can be automated;
the GUI tools are launched and guided.

Register a path manually by writing `registry.json`:

```json
{ "tools": { "odin": "C:\\Odin3\\Odin3.exe" } }
```

## Notes

- The app never downloads firmware. It tells you which build to get and which
  rule will bite you if you get it wrong.
- FRP is an ordered path: owner credentials, vendor service, licensed
  server-side unlock, combination firmware as a last resort. It never
  recommends writing `persist`, `efs`, or `nvram`.
- Bind address is hard-coded to 127.0.0.1.
