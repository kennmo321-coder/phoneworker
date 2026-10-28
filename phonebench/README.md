# phonebench

A local repair workbench for phones. Runs on 127.0.0.1, no internet needed
after your tools are installed, no third-party Python packages.

```
phonebench/
  core.py     tool discovery, USB/adb/fastboot scanning, brand knowledge, planner
  jobs.py     ownership gate, job records, append-only ledger
  server.py   local HTTP app (127.0.0.1 only)
  ui.html     single-page interface
  __main__.py CLI entry
  start.bat   double-click launcher
```

## Run

```powershell
cd "C:\Users\Administrator\Documents\Default Project"
python -m phonebench                 # opens http://127.0.0.1:8765
python -m phonebench --port 9000
python -m phonebench --doctor        # toolchain + device state, no server
```

Or double-click `phonebench\start.bat`.

## What it does

| Tab | Purpose |
|---|---|
| Bench | Live device state (adb / fastboot / EDL / preloader), toolchain status, one-click install of Google's official platform-tools, open-source resource directory |
| Intake | Ownership gate: client name, government ID, receipt, 15-digit IMEI, brand, model, signed declaration. Writes `jobs/<id>.json` |
| Workflow | Per-brand, per-intent plan with a risk rating and the safety rules that matter for that brand. `Run` is disabled until a job exists and the gate passes |
| Ledger | Every job and every operation, append-only, timestamped |

## Intents

`diagnose` · `backup` · `flash` · `restore` · `frp` · `wipe` · `bootloader` · `recovery`

## The gate

`Run` requires all of:

1. A job record with name, ID type + number, receipt, IMEI (15 digits), brand, model.
2. `ownership_declared = true` (set at intake).
3. Brand and model matching the request — and the attached device, when adb can read it.
4. Typing `RUN` in the confirmation dialog.

Read-only diagnosis steps execute automatically. Any step that writes goes
through the gate. Nothing wipes a phone because a button was clicked.

## Data

```
%LOCALAPPDATA%\phonebench\
  jobs\<job-id>.json     one file per job
  ledger.jsonl           append-only audit trail
  registry.json          optional manual tool pins
  tool_index.json        24h tool discovery cache
  platform-tools\        adb/fastboot if bootstrapped from Google
  backups\<job>\         device backups
```

## Tools it drives

Odin, Heimdall, MiFlash, SP Flash Tool, mtkclient, QFIL, edl, LGUP, HiSuite,
Emma, 3uTools, scrcpy, adb, fastboot.

Register a path manually by writing `registry.json`:

```json
{ "tools": { "odin": "C:\\Odin3\\Odin3.exe" } }
```

## Notes

- The app never downloads firmware. It tells you which build to get and which
  rule will bite you if you get it wrong.
- FRP is an ordered path: owner credentials → vendor service → server-side
  unlock with a licence → combination firmware as a last resort. It never
  recommends writing `persist`, `efs`, or `nvram`.
- Bind address is hard-coded to 127.0.0.1.
