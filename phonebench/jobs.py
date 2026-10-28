"""phonebench.jobs - attestation gate, device records, append-only ledger.

Privacy stance: **no client data is stored.** No names, no ID numbers, no
receipt numbers, no scans. The operator verifies identity and proof of
purchase visually, at the counter, and records only that the check happened,
by whom, and when.

A job is a *device* record: brand, model, serial (optional), fault, note.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path

from .core import APP_DIR

JOBS_DIR = APP_DIR / "jobs"
LEDGER = APP_DIR / "ledger.jsonl"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED = ["brand", "model"]

ATTESTATION_STATEMENT = (
    "I visually verified a government-issued ID and a proof of purchase for this "
    "device, in person. No copies were retained."
)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def ledger_append(kind: str, **fields) -> None:
    entry = {"ts": _now(), "kind": kind, **fields}
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ledger_read(limit: int = 300) -> list[dict]:
    if not LEDGER.exists():
        return []
    lines = LEDGER.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(out))


def create(fields: dict) -> dict:
    """Create a device job. Requires a signed attestation, not client data."""
    missing = [k for k in REQUIRED if not str(fields.get(k, "")).strip()]
    if missing:
        return {"ok": False, "error": f"missing: {', '.join(missing)}"}

    att = fields.get("attestation")
    if isinstance(att, bool):
        att = {"id_checked": att, "receipt_checked": att}
    att = att or {}
    if not (att.get("id_checked") and att.get("receipt_checked")):
        return {"ok": False,
                "error": "ownership not attested: ID and receipt must be checked in person"}

    now = dt.datetime.now()
    job_id = f"{now:%Y%m%d}-{secrets.token_hex(3)}"
    job = {
        "job_id": job_id,
        "created": _now(),
        "status": "open",
        "brand": str(fields["brand"]).strip().lower(),
        "model": str(fields["model"]).strip(),
        "serial": str(fields.get("serial", "")).strip(),
        "fault": str(fields.get("fault", "")).strip(),
        "note": str(fields.get("note", "")).strip(),
        "attestation": {
            "id_checked": True,
            "receipt_checked": True,
            "by": str(fields.get("operator", "")).strip(),
            "at": _now(),
            "statement": ATTESTATION_STATEMENT,
        },
        "operations": [],
        "status_history": [{"ts": _now(), "status": "open"}],
    }
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    ledger_append("intake", job=job_id, brand=job["brand"], model=job["model"],
                  serial=job["serial"])
    return {"ok": True, "job": job, "warnings": []}


def load(job_id: str) -> dict | None:
    p = JOBS_DIR / f"{job_id}.json"
    if not p.exists():
        hits = list(JOBS_DIR.glob(f"*{job_id}*.json"))
        if len(hits) == 1:
            p = hits[0]
        else:
            return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(job: dict) -> None:
    (JOBS_DIR / f"{job['job_id']}.json").write_text(
        json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")


def list_jobs() -> list[dict]:
    rows = []
    for f in sorted(JOBS_DIR.glob("*.json"), reverse=True):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "job_id": j.get("job_id"),
            "created": j.get("created"),
            "brand": j.get("brand"),
            "model": j.get("model"),
            "serial": j.get("serial"),
            "fault": j.get("fault"),
            "status": j.get("status"),
            "operations": len(j.get("operations", [])),
        })
    return rows


def gate(job_id: str, brand: str | None = None, model: str | None = None,
         device: dict | None = None, firmware_id: str | None = None) -> dict:
    """Single source of truth for whether a job may execute a write."""
    job = load(job_id)
    if not job:
        return {"ok": False, "reasons": [f"no job record for '{job_id}'"]}

    reasons = []
    for k in REQUIRED:
        if not str(job.get(k, "")).strip():
            reasons.append(f"missing {k}")

    att = job.get("attestation") or {}
    if not att.get("id_checked"):
        reasons.append("ID not attested")
    if not att.get("receipt_checked"):
        reasons.append("proof of purchase not attested")

    if brand and job.get("brand") and brand.lower() != job["brand"].lower():
        reasons.append(f"job brand '{job['brand']}' does not match request '{brand}'")
    if model and job.get("model"):
        a, b = model.lower(), job["model"].lower()
        if a not in b and b not in a:
            reasons.append(f"job model '{job['model']}' does not match device '{model}'")

    if device:
        live_model = (device.get("props") or {}).get("ro.product.model", "")
        if live_model and job.get("model"):
            a, b = live_model.lower(), job["model"].lower()
            if a not in b and b not in a:
                reasons.append(f"attached device reports '{live_model}', job says '{job['model']}'")
        live_serial = (device.get("props") or {}).get("ro.serialno", "")
        if live_serial and job.get("serial"):
            if live_serial.lower() != job["serial"].lower():
                reasons.append(f"attached serial '{live_serial}' != job serial '{job['serial']}'")

    if firmware_id:
        from . import firmware
        v = firmware.verify_firmware(firmware_id)
        if not v.get("ok"):
            reasons.append(f"firmware verification failed: {v.get('error')}")

    return {"ok": not reasons, "reasons": reasons, "job": job}


def record_operation(job_id: str, intent: str, summary: str,
                     steps: list[dict] | None = None) -> None:
    job = load(job_id)
    if not job:
        return
    job.setdefault("operations", []).append({
        "ts": _now(), "intent": intent, "summary": summary, "steps": steps or [],
    })
    save(job)
    ledger_append("operation", job=job_id, intent=intent, summary=summary)


def close(job_id: str, resolution: str = "done") -> dict:
    job = load(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    job["status"] = resolution
    job.setdefault("status_history", []).append({"ts": _now(), "status": resolution})
    save(job)
    ledger_append("close", job=job_id, status=resolution)
    return {"ok": True, "job": job}


def purge_job(job_id: str) -> dict:
    """Delete a job record entirely. The ledger keeps only the id and action."""
    p = JOBS_DIR / f"{job_id}.json"
    if not p.exists():
        return {"ok": False, "error": "not found"}
    p.unlink()
    ledger_append("purge", job=job_id)
    return {"ok": True}
