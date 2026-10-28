"""phonebench.firmware - Firmware Vault management.

Manages local firmware packages: registration, streaming SHA-256 computation,
model/codename hint parsing, manifest persistence, fast/full verification, and removal.

Privacy & Safety:
- Firmware binaries are stored under %LOCALAPPDATA%\\phonebench\\firmware\\ or referenced in place.
- Binaries are NEVER committed to the git repo.
- Tampered or hash-mismatched files block execution.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

from .core import APP_DIR

VAULT_DIR = APP_DIR / "firmware"
VAULT_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB streaming chunks


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def compute_sha256(filepath: Path | str) -> str:
    """Compute SHA-256 hash of a file using 8 MB streaming chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def parse_model_hint(filepath: Path | str) -> str:
    """Attempt to parse model/codename hint from firmware file content/filename."""
    path = Path(filepath)
    filename = path.name

    # 1. Content inspection (zip files: android-info.txt, IPSW plists)
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                for name in names:
                    if name.endswith("android-info.txt"):
                        with zf.open(name) as f:
                            content = f.read().decode("utf-8", errors="replace")
                            for line in content.splitlines():
                                if "=" in line:
                                    k, v = line.split("=", 1)
                                    k = k.strip()
                                    v = v.strip()
                                    if k in ("model", "require board", "product", "codename"):
                                        return v
                    if name.endswith(".plist") and ("BuildManifest" in name or "Restore" in name):
                        # iOS IPSW manifest
                        with zf.open(name) as f:
                            content = f.read().decode("utf-8", errors="replace")
                            m_prod = re.search(r"<key>ProductType</key>\s*<string>([^<]+)</string>", content)
                            if m_prod:
                                return m_prod.group(1)
        except Exception:
            pass

    # 2. Filename pattern checks
    # Samsung: AP_G991BXXU5EWA3_... or SM-G991B
    m_sam = re.search(r"\b(SM-[A-Z0-9]+)\b", filename, re.IGNORECASE)
    if m_sam:
        return m_sam.group(1).upper()

    m_ap = re.search(r"AP_([A-Z0-9]+)", filename)
    if m_ap:
        return m_ap.group(1)

    # iPhone/iPad IPSW: iPhone14,2_16.0_20A362_Restore.ipsw
    m_ipsw = re.search(r"^([A-Za-z0-9]+,\d+)", filename)
    if m_ipsw:
        return m_ipsw.group(1)

    # Xiaomi / generic codename in zip filename
    m_zip_code = re.search(r"([a-z0-9_]+)_(global|images|user|factory)", filename, re.IGNORECASE)
    if m_zip_code:
        return m_zip_code.group(1).lower()

    # Scatter files or plain text
    if path.suffix in (".txt", ".cfg") or "scatter" in filename.lower():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                m_scat = re.search(r"(platform|target|project)\s*:\s*(\S+)", line, re.IGNORECASE)
                if m_scat:
                    return m_scat.group(2)
        except Exception:
            pass

    return "generic"


def add_firmware(filepath: Path | str, copy: bool = True, model_hint: str | None = None) -> dict:
    """Register a firmware package into the local Vault."""
    src_path = Path(filepath).resolve()
    if not src_path.exists() or not src_path.is_file():
        return {"ok": False, "error": f"Firmware file not found: {filepath}"}

    try:
        sha256_hash = compute_sha256(src_path)
        stat = src_path.stat()
        file_size = stat.st_size
        file_mtime = stat.st_mtime

        extracted_hint = parse_model_hint(src_path)
        final_model = (model_hint or extracted_hint or "generic").strip()

        pkg_id = sha256_hash[:12]
        clean_model = re.sub(r"[^a-zA-Z0-9_\-]", "_", final_model)
        folder_name = f"{pkg_id}-{clean_model}"
        target_dir = VAULT_DIR / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        if copy:
            dest_path = target_dir / src_path.name
            if src_path != dest_path:
                shutil.copy2(src_path, dest_path)
            stored_path = str(dest_path.resolve())
            stored_mtime = dest_path.stat().st_mtime
        else:
            stored_path = str(src_path)
            stored_mtime = file_mtime

        manifest = {
            "id": pkg_id,
            "filename": src_path.name,
            "path": stored_path,
            "size": file_size,
            "mtime": stored_mtime,
            "sha256": sha256_hash,
            "model_hint": final_model,
            "copied": bool(copy),
            "added_at": _now(),
        }

        manifest_file = target_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        return {"ok": True, "firmware": manifest}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to register firmware: {exc}"}


def list_firmware() -> dict:
    """List all registered firmware manifests in the vault."""
    packages = []
    if not VAULT_DIR.exists():
        return {"ok": True, "packages": []}

    for child in VAULT_DIR.iterdir():
        if child.is_dir():
            mfile = child / "manifest.json"
            if mfile.exists():
                try:
                    m = json.loads(mfile.read_text(encoding="utf-8"))
                    packages.append(m)
                except Exception:
                    continue

    packages.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return {"ok": True, "packages": packages}


def get_firmware(pkg_id_prefix: str) -> dict:
    """Retrieve a firmware package by exact ID or prefix."""
    res = list_firmware()
    if not res.get("ok"):
        return res

    prefix = (pkg_id_prefix or "").strip().lower()
    if not prefix:
        return {"ok": False, "error": "No firmware package ID specified"}

    matches = [p for p in res.get("packages", []) if p.get("id", "").lower().startswith(prefix)]

    if not matches:
        return {"ok": False, "error": f"Firmware package '{pkg_id_prefix}' not found"}

    if len(matches) > 1:
        matched_ids = [p["id"] for p in matches]
        return {"ok": False, "error": f"Ambiguous package ID prefix '{pkg_id_prefix}' matches multiple packages: {', '.join(matched_ids)}"}

    return {"ok": True, "firmware": matches[0]}


def verify_firmware(pkg_id_prefix: str, full: bool = False) -> dict:
    """Verify package integrity against stored manifest (fast size/mtime or full sha256)."""
    res = get_firmware(pkg_id_prefix)
    if not res.get("ok"):
        return res

    manifest = res["firmware"]
    path_str = manifest.get("path", "")
    target_path = Path(path_str)

    if not target_path.exists() or not target_path.is_file():
        return {
            "ok": False,
            "error": f"Firmware file missing at '{path_str}'",
            "tampered": True,
            "firmware": manifest,
        }

    stat = target_path.stat()
    cur_size = stat.st_size
    cur_mtime = stat.st_mtime

    expected_size = manifest.get("size", 0)
    expected_mtime = manifest.get("mtime", 0)

    # Fast path verification if full is False and size/mtime match
    size_matches = (cur_size == expected_size)
    mtime_matches = (abs(cur_mtime - expected_mtime) < 0.001)

    if not full and size_matches and mtime_matches:
        return {
            "ok": True,
            "verified": True,
            "fast": True,
            "firmware": manifest,
        }

    # Full recompute SHA-256
    try:
        computed_hash = compute_sha256(target_path)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to compute hash for firmware file: {exc}",
            "tampered": True,
            "firmware": manifest,
        }

    if computed_hash.lower() != manifest.get("sha256", "").lower():
        return {
            "ok": False,
            "error": f"Hash mismatch for firmware package '{manifest['id']}': stored {manifest['sha256'][:12]}..., computed {computed_hash[:12]}...",
            "tampered": True,
            "firmware": manifest,
        }

    return {
        "ok": True,
        "verified": True,
        "fast": False,
        "firmware": manifest,
    }


def remove_firmware(pkg_id_prefix: str) -> dict:
    """Remove a firmware package and its vault directory."""
    res = get_firmware(pkg_id_prefix)
    if not res.get("ok"):
        return res

    manifest = res["firmware"]
    pkg_id = manifest["id"]

    # Locate package folder in VAULT_DIR
    for child in VAULT_DIR.iterdir():
        if child.is_dir():
            mfile = child / "manifest.json"
            if mfile.exists():
                try:
                    m = json.loads(mfile.read_text(encoding="utf-8"))
                    if m.get("id") == pkg_id:
                        shutil.rmtree(child)
                        return {"ok": True, "id": pkg_id}
                except Exception:
                    pass

    return {"ok": False, "error": f"Failed to locate vault folder for firmware package '{pkg_id}'"}
