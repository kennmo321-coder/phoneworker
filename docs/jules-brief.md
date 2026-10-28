# Brief for Jules — phoneworker roadmap

Copy everything below the line into Jules (jules.google) as the task prompt.
One feature per PR. Do not batch them.

---

You are working on **phoneworker** — a repair-bench application for a phone
repair shop. Repository: `kennmo321-coder/phoneworker`.

## What already exists

```
phonebench/
  core.py      tool discovery (16 vendor tools), USB/ADB/fastboot scanning,
               brand knowledge base (7 families), workflow planner (8 intents)
  jobs.py      attestation gate, device job records, append-only ledger
  tui.py       full-screen terminal UI (msvcrt on Windows, termios on POSIX)
  server.py    optional local web UI, bound to 127.0.0.1
  ui.html      web interface
  __main__.py  CLI: default TUI, --web, --doctor, --preview
```

Python 3.10+. **Standard library only** — no pip packages. Runtime data lives in
`%LOCALAPPDATA%\phonebench\`. Everything is offline.

## Non-negotiable constraints

1. **No client personal data, ever.** No names, ID numbers, receipt numbers,
   addresses, phone numbers, or scans. A job is a *device* record. The operator
   verifies identity documents visually and the app stores only an attestation
   boolean + timestamp + operator initials. Any feature you add must respect
   this. If a feature needs identity, it must store a hash or nothing.
2. **No circumvention of licensing or DRM.** Do not add integrations with
   cracked, patched, or keygen'd software. Commercial tools are called if the
   user installed a licensed copy; the app never supplies or repairs them.
3. **Never auto-execute a destructive step.** Read-only diagnosis may run
   automatically. Anything that writes requires the gate plus an explicit
   confirmation. Do not weaken `jobs.gate()`.
4. **Offline-first.** No telemetry, no background network calls, no analytics.
   The only network operation allowed is the existing explicit
   "install platform-tools" action, and any new download must be user-initiated
   and hash-verified.
5. **Standard library only.** If you believe a dependency is unavoidable, open
   an issue first and justify it — do not add one.
6. **Cross-platform.** Windows 10+ is the primary target; Linux and macOS must
   at least import and run the TUI without crashing. Guard platform-specific
   code paths.
7. **Keep the safety content accurate.** Brand rules in `core.py` are
   deliberate: MTK `Download Only`, Samsung `HOME_CSC` semantics, Qualcomm
   backup-before-write, FRP ordering. Do not simplify them into generic advice.

## What to build — priority order

### P0 — correctness and trust

**F1. Firmware vault** (`phonebench/firmware.py`)
Local library of firmware packages: register a file, compute SHA-256, parse
model/codename hints (`android-info.txt` in zips, filename patterns for
`AP_*.tar.md5`, scatter files, IPSW), store a manifest, and verify on use.
- `pb firmware add <path>` / `list` / `verify <id>` / `rm <id>`
- The TUI gains a Vault screen listing packages with model, size, hash, and a
  green/red model-match indicator against the attached device.
- Flashing steps in the planner must reference a registered firmware id, and
  `run` refuses if the hash changed since registration.
- Acceptance: a tampered file is detected and blocks execution.

**F2. Dry-run mode** (`--dry-run` and a TUI toggle)
Every plan renders the exact argv it *would* execute, with the resolved tool
paths, and executes nothing. `--preview` stays as-is. Acceptance: dry-run
produces a log identical in shape to a real run, with `executed: 0`.

**F3. Test harness with fake devices** (`tests/`)
`pytest`-free is preferred but pytest is acceptable for tests only. Provide
fake `adb`/`fastboot` executables (Python scripts) that emit canned
`devices -l`, `getprop`, and `fastboot devices` output, plus a device state
matrix. Cover: gate pass/fail paths, brand/model mismatch, attestation refusal,
plan risk floors, modal confirmation, ledger append, firmware hash mismatch.
- Acceptance: `python -m phonebench --self-test` runs the suite with no
  external tools installed and exits non-zero on failure.

### P1 — bench capability

**F4. Hardware health suite** (`intent: health`)
A scripted read-only battery of checks over ADB: battery capacity/health/cycle
count (from `dumpsys battery` and sysfs where available), storage free space,
RAM, CPU/board, sensor list, camera enumeration (`dumpsys media.camera`),
charging current, Wi-Fi/BT state, and an interactive screen test (solid colour
cycle for dead pixels, touch grid, which the TUI can run full-screen).
- Produces a pass/warn/fail table per check and appends the result to the job.
- Acceptance: runs on a device with adb; degrades to a clear message on any
  missing property; never writes to the device.

**F5. Guided unbrick wizard** (`intent: restore`, interactive)
Step-by-step state machine: detect current mode → choose entry method for the
brand → verify firmware matches the model → flash → verify boot → post-checks.
Each step shows the risk and waits for Enter. Refuses to continue if the
firmware model does not match the device.
- Acceptance: cannot reach the flash step without a matching, hash-verified
  firmware from the vault.

**F6. Encrypted backup vault** (`phonebench/vault.py`)
Backups produced by the `backup` intent are written into an encrypted container
(AES-GCM via `hashlib`/`hmac` primitives is not enough — use a documented,
self-contained construction, e.g. scrypt-derived key + ChaCha20-Poly1305
implemented in pure Python, or a bundled single-file reference implementation
in the repo). Key from a passphrase entered at run time, never stored.
- `pb vault list` / `vault extract <id>` with passphrase
- Retention policy: warn when total size exceeds a configured cap.
- Acceptance: the ciphertext is not readable without the passphrase; a wrong
  passphrase fails cleanly without corrupting anything.

**F7. Per-device history without identity**
Key history on a salted hash of the serial number (salt stored locally, never
exported). Show previous jobs for the same device: dates, intents, outcomes.
- Acceptance: the stored key is a hash; the serial itself is not persisted a
  second time beyond the job record the operator already created.

### P2 — polish and distribution

**F8. Report export** — generate a Markdown/plain-text repair report per job
(device, fault, checks, operations, timestamps, outcome) with no client data.
`pb report <job>` and a key in the Ledger screen. Acceptance: contains no
personal data and renders correctly in a terminal.

**F9. Tool adapter manifests** — replace hard-coded tool knowledge in
`core.py` with JSON manifests in `phonebench/tools/*.json` describing each
vendor tool: name, discovery globs, supported brands, invocation shape, version
command, whether it is GUI-only. Ship manifests for the current 16 tools.
Acceptance: discovery still finds everything the old code found; adding a new
tool needs only a JSON file.

**F10. Internationalisation** — externalise UI strings to `phonebench/i18n/*.json`
for `en`, `fr`, `ar`. The TUI must handle right-to-left text gracefully
(at minimum: correct alignment, no mirrored box drawing). Language selection
via `--lang` and a config field. Acceptance: no hard-coded English left in
`tui.py`; missing keys fall back to English.

## Process

- One feature per pull request, in the priority order above.
- Each PR: implementation + tests + README update + a short note in the PR body
  explaining any trade-off you made.
- Do not modify the safety model, the attestation gate, or the brand rules
  without an explicit issue discussing it first.
- Run `python -m phonebench --preview` and `--self-test` before opening the PR;
  paste the output into the PR body.
- If something in this brief is ambiguous, open an issue stating the ambiguity
  and your proposed resolution rather than guessing silently.
