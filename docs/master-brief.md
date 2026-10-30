# phonebench - master brief

**This file is the authoritative roadmap.** `docs/jules-brief.md` is kept for
history only; its priority order is out of date and must not be followed.

Repository: `kennmo321-coder/phoneworker`
Target: a repair bench for one shop in Algeria. Terminal first, offline first,
free tooling only. Windows is the primary platform.

---

## 0. What this is

`phonebench` is the workbench an operator sits in front of while a customer's
phone is on the counter. It answers four questions, in this order:

1. What is this device, and what is wrong with it? (read-only, always allowed)
2. Is this device the customer's? (attestation gate, before anything writes)
3. What is the exact sequence of operations, with what risk? (plan, dry-run)
4. Do it, prove it, and leave a record. (execute, verify, ledger)

It is not a magic box. When the honest answer is "this cannot be recovered",
the app must say so in ten seconds instead of selling hope.

## 1. Hard rules

1. **No client personal data, ever.** No names, ID numbers, receipt numbers,
   addresses, phone numbers, photos of documents. A job is a *device* record.
   The operator looks at a government ID and proof of purchase in person and
   records only: attestation booleans, timestamp, operator initials.
2. **The gate is not negotiable.** Every write requires `jobs.gate()` to pass:
   a job exists, attestation is present, brand and model match the attached
   device, and any referenced firmware is hash-verified. Read-only diagnosis
   runs without it. Deleting a gate branch must break the test suite - see
   section 6.
3. **No circumvention.** No FRP bypass, no Apple ID unlock, no MDM removal,
   no screen-lock extraction, no IMEI/NV writing, no cracked or patched vendor
   software, no DRM circumvention. See section 2 for what replaces each of
   those requests.
4. **Suspect stolen - stop.** If the operator believes the device is stolen,
   the app refuses the job, records only `refused: suspected stolen` with no
   identifying data, and prompts the operator to advise a police report.
5. **Offline.** No telemetry, no analytics, no background network. The only
   network operations are explicit user actions (installing platform-tools,
   downloading a firmware the user asked for), and anything downloaded must be
   hash-verified before it is used.
6. **Standard library only**, Python 3.10+. A dependency needs an issue and an
   explicit approval in that issue first. Tests may use `unittest` only.
7. **Cross-platform.** Windows 10+ primary; Linux and macOS must import and run
   the TUI without crashing. Guard platform-specific paths.
8. **Keep the safety content accurate.** Brand rules in `core.py` are
   deliberate: MediaTek `Download Only`, Samsung `HOME_CSC` semantics,
   Qualcomm backup-before-write, FRP ordering. Do not generalise them into
   vague advice.

## 2. Permanent non-goals

These are refused, not deferred. Do not implement them, and do not implement
"research" versions of them.

| Request | Why it is refused | What the app offers instead |
| --- | --- | --- |
| FRP / Google account bypass | It is a theft-enablement tool; the account is the owner's proof | F11 Data Rescue: recover the owner's account, then the FRP screen is satisfied legitimately |
| Apple ID / activation lock removal | Same; activation lock is Apple's ownership proof | Recovery with the owner's Apple ID, or Apple service centre with receipt |
| Screen lock removal without the credential | The credential is the only thing protecting the data | Account recovery (F11), then wipe and restore; or vendor service centre |
| MDM / supervision removal | Usually a stolen corporate device | Return to the issuing organisation |
| IMEI repair or rewrite | Illegal in most jurisdictions, destroys the radio, enables trafficking | Report the fault; refer to the manufacturer's service |
| Cracked / patched vendor tools | Licence circumvention, and the patched builds are server-gated anyway | Call a licensed copy if the operator owns one; never supply or repair one |
| "Data recovery" from a wiped, encrypted device | Mathematically gone on FBE hardware | State it plainly, then F12 Safe Setup for the next phone |

If a customer's device falls in the left column and they cannot produce the
account or a receipt, the honest answer is a referral to a forensic lab, not a
promise. Write that refusal into the UI text so the operator is never tempted.

## 3. Where we are

On `main` (`911704a`):

- v1.0 core: `core.py` (16 tools, 7 brand families, 8 intents), `jobs.py`
  (attestation gate, append-only ledger), `tui.py` (6 screens),
  `server.py`/`ui.html` (optional local web), `__main__.py` (`--doctor`,
  `--preview`, `--web`).
- F1 Firmware Vault: `phonebench/firmware.py`, `pb firmware add|list|verify|rm`,
  streaming SHA-256, tamper blocks the plan and `execute()`. 12 tests pass.
  Mutation-verified: removing the `execute()` guard, the gate's firmware
  check, or the attestation branch breaks the suite - except the last one,
  see F3 below.

Known gaps in the current code, to be fixed in priority order:

- `fastboot update` for Pixel is rendered in the plan but never executed: the
  step has no `tool` field, so it falls through to the guide branch.
- `run_step` has a 180 s timeout, too short for a real 10-15 minute flash, and
  it does not stream output.
- `PHONEBENCH_FAKE_ROOT` is honoured unconditionally by `core.discover()`.
- `action_plan` reads the model from `self.job`, which is only set at intake;
  after a restart the model can be `None` and the gate comparison degrades.

## 4. Priority order

One feature per pull request, in this order. Do not start the next one until
the previous one is merged.

### P0 - make the bench trustworthy

**F3. Test harness with fake devices** (`tests/`, `--self-test`, CI)
*Status: in review on the F1 branch, one gap.*

The harness, fake `adb`/`fastboot`, `--self-test` runner and GitHub Actions
matrix are implemented and pass 19/19 from a clean clone. Before merge:

- The gate's attestation branch is untested. Deleting
  `if not att.get("id_checked"): reasons.append("ID not attested")` from
  `jobs.gate()` leaves the suite green, because `test_attestation_refusal`
  only exercises `jobs.create()`. Add a test that writes a job file with
  `attestation.id_checked = false` directly to disk, asserts `gate()` refuses
  with "ID not attested", repeats for `receipt_checked`, and asserts the job
  passes again when both are restored.
- Gate `PHONEBENCH_FAKE_ROOT` behind `PHONEBENCH_TEST_MODE=1`, set only by
  `--self-test`. When it is active, the bench header must show
  `SIMULATED DEVICES` so nobody mistakes fake hardware for real hardware.
- Rebase onto `main` (`911704a`) and open a fresh PR; the current PR is
  pinned to the pre-merge F1 branch.

Acceptance: `python -m phonebench --self-test` exits 0 on a clean clone on
Windows and Linux; deleting any of the four guard branches (plan blocked,
gate attestation, gate firmware hash, plan blocked at execute) exits 1. Paste
the mutation results in the PR body.

**F2. Dry-run mode** (`--dry-run`, TUI toggle)
Every plan renders the exact argv it would execute, with resolved tool paths,
and executes nothing.
Acceptance: the rendered log is identical in shape to a real run, ends with
`executed: 0`, and is produced by the same code path that builds the real
argv (not a copy).

### P1 - real flashing

This is the point of the app. Everything above is scaffolding for it.

**F1.5a. Pixel / fastboot flashing, executed for real**
- The flash plan for Google devices must carry `tool` + `argv`, so the
  existing `execute()` path actually runs `fastboot update <factory.zip>`.
- Per-step timeout becomes configurable (default 900 s for flash, 180 s for
  probe steps). Output is streamed line by line to the screen and appended to
  the job log with timestamps.
- Preconditions, enforced in code, not in prose: firmware is in the vault,
  full SHA-256 matches, ZIP contains `android-info.txt` whose `require board`
  and `require product` match the attached device, device is in fastboot mode.
- Abort on `FAILED`, `error:`, `Invalid sparse file` or a non-zero exit; no
  automatic retry. On abort, print the last 20 lines and the recovery path.
- Bootloader unlock stays a separate `caution` intent: it wipes data, the
  operator confirms it on the device screen, and the plan says so first.
Acceptance: a full flash on a real Pixel from the vault; the same plan under
`--dry-run` produces byte-identical argv; a modified firmware byte blocks the
run with a hash message; a wrong device blocks it with a model message.

**F1.5b. Samsung / Heimdall flashing**
- Detect download mode (`heimdall detect`, USB `04e8:685d`), read the PIT with
  `heimdall print-pit`, and compare the model from the PIT against the job.
- Map vault packages to `--AP`, `--BL`, `--CP`, `--CSC` (or `--HOME-CSC`).
  `HOME_CSC` preserves userdata; plain CSC wipes it. Say which one is about to
  happen, in the confirmation, not in the help text.
- Refuse `--repartition` unless a matching `.pit` is in the vault and the
  operator typed the extra confirmation. Never write `persist`, `efs`, `nvram`.
- Odin is GUI-only: launch it and guide, never claim to automate it.
Acceptance: dry-run argv matches the Odin field mapping; a real flash on a
spare device; a mismatched PIT or model aborts before any write.

**F4. Hardware health suite** (`intent: health`)
Read-only battery of checks over ADB: battery capacity/health/cycle count,
charging current, storage free space, RAM, SoC/board, sensor list, camera
enumeration, Wi-Fi/BT state, and an interactive screen test (solid colour
cycle, touch grid) in the TUI.
Each check returns pass/warn/fail with the raw value that produced it.
Acceptance: runs on a device with adb; every missing property degrades to a
clear "not reported by this device" line instead of an exception; never writes
to the device; result appended to the job.

### P2 - the work the shop actually sells

Most customers are not power users. They have no backup, no account they
remember, and photos they cannot lose. This phase exists for them.

**F11. Data Rescue** (`intent: rescue`, new screen)
Recover the account, then recover the data. No bypass, ever.
- Identify the account: read the FRP hint (`a•••@gmail.com`), or the accounts
  on a live device, and show it back to the customer so they can confirm it.
- Coach the recovery flow with the customer present: recovery phone, recovery
  email, Google account recovery. Script the questions; never store or log a
  password, a recovery code or an answer.
- Sync audit, before anything is touched: last Google Photos backup, last
  WhatsApp Drive backup, contacts sync state, Samsung/Apple cloud state.
  Render one screen: *412 photos, last backup 12 March* or *nothing synced
  since 2021*.
- Export what exists to a folder or USB stick: Google Photos album download,
  contacts (vCard), WhatsApp backup file. Verify the export is readable before
  the wipe is offered.
- "What will be lost" list, generated from the audit, shown before the wipe,
  and stored in the job as counts only.
- After the wipe, the FRP screen is satisfied by the owner's own account. That
  is the whole mechanism; do not add a shortcut for when they cannot sign in.
Acceptance: a job can run the audit and export with no credentials stored
anywhere on disk; the wipe is blocked until the operator acknowledges the
loss list; when the account is unrecoverable the app says so and offers F13
instead of a workaround.

**F12. Safe Setup** (post-repair checklist, printable)
The service that prevents the next disaster: add a recovery phone and email,
turn on photo backup, enable WhatsApp backup, write down the account in a
place the customer controls, set a lock screen they will remember, and note
the shop's number. Generate a one-page card in French and Arabic, printed or
saved as a file next to the job. No client data on the card except what the
customer writes by hand.
Acceptance: card renders in a terminal and as a standalone HTML/PDF-free text
file; contains no PII; offered automatically at job close.

**F13. Locked-Device Assistant** (`intent: locked`, decision tree)
Diagnose the lock, then route to the only legitimate path:
1. Which lock is it - FRP, Apple ID/activation, MDM, or screen lock?
2. Can the owner recover the account? -> F11.
3. Is there a receipt and a vendor service centre reachable? -> prepare the
   paperwork: device model, serial, receipt checklist, the centre's address.
4. Neither? -> say plainly that the data is unrecoverable without a forensic
   lab, name the limit, and offer F12 for the next device.
Every branch ends in a written outcome in the job: `rescued`, `referred`,
`refused`. No branch writes to the device.
Acceptance: the assistant cannot be navigated to any bypass step; each branch
produces a printable outcome; the referral branch includes the police-report
prompt when ownership is doubtful.

### P3 - custody of the data

**F6. Encrypted backup vault** (`phonebench/vault.py`)
*Requires a design decision before any code. Do not hand-roll a cipher.*
Open an issue comparing: (a) an approved dependency (`cryptography`, Apache-2.0
/ BSD) vendored as a wheel, (b) the `age` format via a user-installed `age`
binary, (c) deferring the feature. Whatever is chosen: scrypt or Argon2 KDF,
per-file nonce, authenticated encryption, passphrase never stored, wrong
passphrase fails cleanly without touching the container.
Acceptance: ciphertext is unreadable without the passphrase; a truncated file
is detected, not silently decrypted; the chosen primitive is documented in
README with its source and licence.

**F5. Guided unbrick wizard** (`intent: restore`, interactive)
State machine: detect current mode -> entry method per brand -> verify the
vault firmware matches -> flash -> verify boot -> post-checks. Each step shows
risk and waits for Enter. Refuses to reach the flash step without a matching,
hash-verified package.
Acceptance: cannot reach flash with an unverified or mismatched package;
resuming an interrupted wizard never skips the verification step.

**F7. Per-device history without identity**
Key history on a salted hash of the serial (salt local, never exported). Show
previous jobs for the same device: dates, intents, outcomes.
Acceptance: the stored key is a hash; deleting the salt breaks the link, by
design; no additional copy of the serial is persisted.

### P4 - parity and distribution

- **F8 Report export** - Markdown/plain-text per job (device, fault, checks,
  operations, timestamps, outcome), no client data. `pb report <job>`.
- **F14 Transfer** - device-to-device: `adb` file copy, contacts/app list
  export, launch Smart Switch / Apple transfer assistant and guide. Never
  promise what the platform does not allow.
- **F15 Eraser** - honest erase: factory reset, verify with a post-wipe probe,
  optional `blkdiscard` on unlocked devices. No "military grade" claims; on
  FBE, crypto-erase *is* the erase.
- **F16 Phone manager** - file browser over `adb push/pull`, app list with
  versions, contacts/SMS export where the OS permits, `scrcpy` launch for
  mirroring. Read-only by default; writes go through the gate.
- **F9 Tool adapter manifests** - move hard-coded tool knowledge to
  `phonebench/tools/*.json` (name, globs, brands, invocation shape, version
  command, GUI-only flag). Ship the current 16.
- **F10 Internationalisation** - `en`, `fr`, `ar` in `phonebench/i18n/*.json`.
  French first, Arabic second; RTL must align correctly and must not mirror
  box-drawing characters. No hard-coded English left in `tui.py`.

## 5. Tool matrix

Only these can be automated. Everything else is launch-and-guide.

| Tool | Licence / source | Automatable | Notes |
| --- | --- | --- | --- |
| `adb`, `fastboot` | Apache-2.0, Google platform-tools | yes | the workhorses |
| `heimdall` | MIT, open source | yes | Samsung download mode |
| `mtkclient` | MIT, open source | yes | MediaTek BROM/preloader |
| `edl` / `qdl` | BSD/MIT, open source | yes | Qualcomm Sahara/Firehose |
| `scrcpy` | Apache-2.0 | launch | mirroring, no writes |
| Odin | proprietary, free download | launch only | Samsung, GUI |
| MiFlash | proprietary, free download | launch only | Xiaomi, GUI |
| SP Flash Tool | proprietary, free download | launch only | MediaTek, GUI |
| QFIL | proprietary, free download | launch only | Qualcomm, GUI |
| 3uTools / iTunes | proprietary, free download | launch only | Apple, GUI |
| MSM / LGUP / HiSuite / Emma | proprietary, free download | launch only | vendor-specific |

Rule: the app may tell the operator that a tool is missing and where its
official download lives. It never bundles, patches, or repairs one.

## 6. Definition of done

A PR is mergeable when all of these are true:

1. `python -m phonebench --self-test` exits 0 on a clean clone, Windows and
   Linux, in CI.
2. **Every safety check added has a mutation proof.** Delete the check, run
   the suite, confirm exit 1, restore it, and paste both results in the PR
   body. A test that cannot fail is not a test.
3. `python -m phonebench --preview` renders every screen without an exception
   at 90x24 and at 120x40.
4. No new dependency; no network in the default path; no PII in code, tests,
   fixtures or logs.
5. README updated for any new command or screen.
6. The PR body states the trade-off made and anything deliberately left out.

## 7. Process

- One feature per PR, branched from `main`, in the order above.
- Do not start a feature while the previous PR is unmerged.
- Do not modify the safety model, the attestation gate, or the brand rules
  without an issue that discusses the change first.
- If something in this brief is ambiguous, open an issue with the ambiguity
  and your proposed resolution. Do not guess silently, and do not invent
  scope.
