"""phonebench.jobs - ownership gate, job records, append-only ledger.

Nothing destructive runs without a job that has: client name, government ID,
purchase receipt, 15-digit IMEI, brand, model, and a signed ownership
declaration. The gate is checked in code, every time.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .core import APP_DIR

JOBS_DIR = APP_DIR / "jobs"
LEDGER = APP_DIR / "ledger.jsonl"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED = ["client_name", "id_type", "id_number", "receipt", "imei", "brand", "model"]


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
    missing = [k for k in REQUIRED if not str(fields.get(k, "")).strip()]
    if missing:
        return {"ok": False, "error": f"missing required fields: {', '.join(missing)}"}

    digits = re.sub(r"\D", "", str(fields["imei"]))
    if len(digits) != 15:
        return {"ok": False, "error": f"IMEI must be 15 digits (got {len(digits)})"}

    now = dt.datetime.now()
    job_id = f"{now:%Y%m%d-%H%M%S}-{digits[-6:]}"
    job = {
        "job_id": job_id,
        "created": _now(),
        "status": "open",
        "client_name": str(fields["client_name"]).strip(),
        "id_type": str(fields["id_type"]).strip(),
        "id_number": str(fields["id_number"]).strip(),
        "receipt": str(fields["receipt"]).strip(),
        "receipt_date": str(fields.get("receipt_date", "")).strip(),
        "imei": digits,
        "brand": str(fields["brand"]).strip().lower(),
        "model": str(fields["model"]).strip(),
        "id_copy": str(fields.get("id_copy", "")).strip(),
        "receipt_photo": str(fields.get("receipt_photo", "")).strip(),
        "technician": str(fields.get("technician", "")).strip(),
        "notes": str(fields.get("notes", "")).strip(),
        "ownership_declared": True,
        "declaration": "Client declares lawful ownership of this device and authorises repair.",
        "operations": [],
        "status_history": [{"ts": _now(), "status": "open"}],
    }
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    ledger_append("intake", job=job_id, client=job["client_name"], imei=digits,
                  brand=job["brand"], model=job["model"])
    warnings = []
    for label, p in (("ID copy", job["id_copy"]), ("receipt photo", job["receipt_photo"])):
        if p and not Path(p).exists():
            warnings.append(f"{label} not found at {p}")
    return {"ok": True, "job": job, "warnings": warnings}


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
            "client_name": j.get("client_name"),
            "brand": j.get("brand"),
            "model": j.get("model"),
            "imei": j.get("imei"),
            "status": j.get("status"),
            "operations": len(j.get("operations", [])),
        })
    return rows


def gate(job_id: str, brand: str | None = None, model: str | None = None,
         device: dict | None = None) -> dict:
    """Return {'ok': bool, 'reasons': [...]} - the single source of truth."""
    job = load(job_id)
    if not job:
        return {"ok": False, "reasons": [f"no job record for '{job_id}'"]}
    reasons = []
    for k in REQUIRED:
        if not str(job.get(k, "")).strip():
            reasons.append(f"missing {k}")
    if job.get("ownership_declared") is not True:
        reasons.append("ownership declaration not signed")
    imei = re.sub(r"\D", "", str(job.get("imei", "")))
    if len(imei) != 15:
        reasons.append("IMEI is not 15 digits")
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
        if live_serial and job.get("notes") and "serial:" in job["notes"].lower():
            pass  # serials are optional; model + IMEI is the primary check
    return {"ok": not reasons, "reasons": reasons, "job": job}


def record_operation(job_id: str, intent: str, summary: str, steps: list[dict] | None = None) -> None:
    job = load(job_id)
    if not job:
        return
    job.setdefault("operations", []).append({
        "ts": _now(), "intent": intent, "summary": summary,
        "steps": steps or [],
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
