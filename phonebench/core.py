"""phonebench.core - tool discovery, device scanning, brand knowledge, planning.

No third-party dependencies. Everything here is read-only unless a caller
explicitly executes a step.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "phonebench"
APP_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

# ---------------------------------------------------------------- tool catalog

TOOL_SPECS = {
    "adb": {"glob": ["adb.exe"], "sub": "platform-tools", "bundle": "platform-tools"},
    "fastboot": {"glob": ["fastboot.exe"], "sub": "platform-tools", "bundle": "platform-tools"},
    "odin": {"glob": ["odin3*.exe", "odin.exe"]},
    "heimdall": {"glob": ["heimdall.exe"]},
    "miflash": {"glob": ["xiaomiflash.exe"]},
    "spflash": {"glob": ["flash_tool.exe"]},
    "mtkclient": {"glob": ["mtk.bat", "mtkclient.exe"]},
    "qfil": {"glob": ["qfil.exe"]},
    "edl": {"glob": ["edl.py", "edl.exe"]},
    "msm": {"glob": ["msmdownloadtool.exe"]},
    "lgup": {"glob": ["lgup.exe"]},
    "hisuite": {"glob": ["hisuite.exe"]},
    "emma": {"glob": ["emma.exe"]},
    "3utools": {"glob": ["3utools.exe"]},
    "itunes": {"glob": ["itunes.exe"]},
    "scrcpy": {"glob": ["scrcpy.exe"]},
}

EXPLICIT_PATHS = {
    "adb": [r"C:\platform-tools\adb.exe", r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"],
    "fastboot": [r"C:\platform-tools\fastboot.exe", r"%LOCALAPPDATA%\Android\Sdk\platform-tools\fastboot.exe"],
    "3utools": [r"C:\Program Files (x86)\3uTools\3uTools.exe", r"C:\Program Files\3uTools\3uTools.exe"],
}

_SEARCH_ROOTS = [
    (Path(os.environ.get("ProgramFiles", r"C:\Program Files")), 2),
    (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")), 2),
    (Path.home() / "Downloads", 3),
    (Path.home() / "Desktop", 3),
    (Path.home() / "Documents", 3),
    (Path("D:/"), 2),
]

VID_MAP = {
    0x04E8: "samsung", 0x18D1: "google", 0x2717: "xiaomi", 0x22B8: "motorola",
    0x2A70: "oneplus", 0x12D1: "huawei", 0x0BB4: "htc", 0x0FCE: "sony",
    0x1004: "lg", 0x05C6: "qualcomm", 0x0E8D: "mediatek", 0x22D9: "oppo",
    0x2D95: "vivo", 0x1E4E: "vivo", 0x1D45: "oppo", 0x04DD: "sharp",
    0x0B05: "asus", 0x1EBF: "lenovo", 0x2916: "lenovo", 0x05AC: "apple",
}

# ---------------------------------------------------------------- brand model

BRANDS = {
    "samsung": {
        "label": "Samsung",
        "tools": ["odin", "heimdall", "adb", "fastboot", "scrcpy"],
        "firmware": [".tar.md5", ".tar", ".zip"],
        "firmware_hint": "AP + BL + CP + CSC (or HOME_CSC) for the exact model and region.",
        "sources": ["SamFW", "Frija", "SamMobile"],
        "rules": [
            "Match model AND CSC/region exactly - wrong CSC kills carrier features.",
            "HOME_CSC keeps userdata; plain CSC wipes it.",
            "Never tick Nand Erase All or Re-Partition without the correct .pit.",
            "Never hand-write persist / efs / nvram - Wi-Fi and IMEI live there.",
            "First boot after flash can take 10+ minutes. Do not unplug.",
        ],
    },
    "google": {
        "label": "Google Pixel",
        "tools": ["adb", "fastboot"],
        "firmware": [".zip"],
        "firmware_hint": "Factory image image-<codename>-<build>.zip, or full OTA.",
        "sources": ["developers.google.com/android/images", "flash.android.com"],
        "rules": [
            "adb kill-server before flashing (Google's own guidance).",
            "Factory image must match device codename and build.",
            "Do not relock the bootloader until the device boots clean.",
            "No hubs or extension cables; rear USB-A preferred.",
        ],
    },
    "xiaomi": {
        "label": "Xiaomi / Redmi / POCO",
        "tools": ["miflash", "adb", "fastboot"],
        "firmware": [".tgz", ".zip"],
        "firmware_hint": "Fastboot ROM for the exact codename (alioth, raven, ...).",
        "sources": ["xiaomifirmwareupdater.com", "miui.com"],
        "rules": [
            "ROM must match the codename, not the marketing name.",
            "Choose 'clean all', never 'clean all and lock', unless returning to full stock.",
            "Never lock the bootloader on modified firmware.",
        ],
    },
    "mediatek": {
        "label": "MediaTek (generic)",
        "tools": ["spflash", "mtkclient"],
        "firmware": [".txt", ".bin"],
        "firmware_hint": "scatter file + preloader + images for the exact board.",
        "sources": ["firmware dump from a donor device"],
        "rules": [
            "SP Flash Tool: Download Only. NEVER 'Format All + Download' - it wipes calibration and IMEI.",
            "Read a full backup with mtkclient before writing anything.",
            "Scatter and preloader must match the exact board.",
        ],
    },
    "qualcomm": {
        "label": "Qualcomm EDL",
        "tools": ["qfil", "edl"],
        "firmware": [".xml", ".mbn", ".elf"],
        "firmware_hint": "rawprogram*.xml + patch*.xml + programmer for the exact chipset.",
        "sources": ["vendor service package"],
        "rules": [
            "Firehose programmer must match the chipset - a wrong one can brick.",
            "Back up partitions (edl rl) before any write.",
            "rawprogram/patch must come from the same package as the programmer.",
        ],
    },
    "apple": {
        "label": "Apple iPhone / iPad",
        "tools": ["3utools", "itunes"],
        "firmware": [".ipsw"],
        "firmware_hint": "IPSW that is still signed for that exact model.",
        "sources": ["ipsw.me"],
        "rules": [
            "Only signed IPSW. Never downgrade to an unsigned build.",
            "Retain data unless a wipe is required.",
            "There is no passcode bypass on modern iOS - only erase/restore.",
            "Activation Lock can only be removed by the original owner's Apple ID.",
        ],
    },
    "generic": {
        "label": "Generic Android",
        "tools": ["adb", "fastboot"],
        "firmware": [".zip", ".img"],
        "firmware_hint": "Factory image or OTA for the exact model.",
        "sources": ["vendor support site"],
        "rules": [
            "Back up user data before anything destructive.",
            "Match the model exactly; never flash a similar model's image.",
        ],
    },
}

BRAND_ALIASES = {
    "redmi": "xiaomi", "poco": "xiaomi", "mi": "xiaomi",
    "pixel": "google", "nexus": "google",
    "galaxy": "samsung",
    "oneplus": "generic", "oppo": "generic", "realme": "generic",
    "vivo": "generic", "huawei": "generic", "honor": "generic",
    "sony": "generic", "lg": "generic", "motorola": "generic",
    "iphone": "apple", "ipad": "apple", "ios": "apple",
    "mtk": "mediatek", "mediatek": "mediatek",
    "qualcomm": "qualcomm", "edl": "qualcomm",
}

GENERIC_RULES = [
    "Ownership verified before any destructive step: ID + receipt + IMEI match.",
    "Back up user data first. Keep the backup with the job record.",
    "Verify the firmware hash and that the model string matches the device.",
    "Battery above 50%, stable power, no hubs, do not interrupt.",
    "Keep an untouched copy of the original firmware on the bench.",
]

# Open-source and vendor resources the bench actually uses. Verified projects.
RESOURCES = [
    {"name": "mtkclient", "url": "https://github.com/bkerler/mtkclient",
     "note": "MediaTek BROM/preloader: read backup, unlock, flash", "brand": "mediatek"},
    {"name": "edl", "url": "https://github.com/bkerler/edl",
     "note": "Qualcomm EDL: Sahara/Firehose read and write", "brand": "qualcomm"},
    {"name": "Heimdall", "url": "https://github.com/Benjamin-Dobell/Heimdall",
     "note": "Cross-platform Samsung flasher (Odin alternative)", "brand": "samsung"},
    {"name": "PixelFlasher", "url": "https://github.com/badabing2005/PixelFlasher",
     "note": "Pixel factory-image GUI with slot handling", "brand": "google"},
    {"name": "scrcpy", "url": "https://github.com/Genymobile/scrcpy",
     "note": "Screen mirroring and control over ADB", "brand": "generic"},
    {"name": "libimobiledevice", "url": "https://github.com/libimobiledevice/libimobiledevice",
     "note": "iOS device protocol library", "brand": "apple"},
    {"name": "pymobiledevice3", "url": "https://github.com/doronz88/pymobiledevice3",
     "note": "Pure-python iOS tooling", "brand": "apple"},
    {"name": "platform-tools", "url": "https://developer.android.com/tools/releases/platform-tools",
     "note": "Official adb + fastboot", "brand": "generic"},
    {"name": "SamFW", "url": "https://samfw.com",
     "note": "Samsung firmware by model + CSC", "brand": "samsung"},
    {"name": "ipsw.me", "url": "https://ipsw.me",
     "note": "Signed IPSW status per device", "brand": "apple"},
]

# ---------------------------------------------------------------- tool discovery

_lock = threading.Lock()
_mem_cache: dict[str, str | None] = {}
_index_cache: dict[str, str] | None = None
INDEX_FILE = APP_DIR / "tool_index.json"


def _walk_index() -> dict[str, str]:
    """Single bounded pass over likely roots -> {filename_lower: path}."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    with _lock:
        if _index_cache is not None:
            return _index_cache
        if INDEX_FILE.exists():
            try:
                raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                if time.time() - raw.get("_ts", 0) < 86400:
                    _index_cache = {k: v for k, v in raw.items() if k != "_ts"}
                    return _index_cache
            except Exception:
                pass
        wanted = {g for spec in TOOL_SPECS.values() for g in spec["glob"]}
        idx: dict[str, str] = {}
        deadline = time.monotonic() + 8.0
        for root, maxd in _SEARCH_ROOTS:
            if not root.exists():
                continue
            try:
                base = len(root.parts)
                for dirpath, dirnames, filenames in os.walk(root):
                    if time.monotonic() > deadline:
                        break
                    if len(Path(dirpath).parts) - base > maxd:
                        dirnames[:] = []
                        continue
                    for f in filenames:
                        key = f.lower()
                        if key in wanted and key not in idx:
                            idx[key] = str(Path(dirpath) / f)
            except (PermissionError, OSError):
                continue
        idx["_ts"] = time.time()  # type: ignore[assignment]
        try:
            INDEX_FILE.write_text(json.dumps(idx, indent=2), encoding="utf-8")
        except OSError:
            pass
        idx.pop("_ts", None)
        _index_cache = idx
        return idx


def discover(tool: str, registry: dict | None = None) -> str | None:
    """Resolve a tool path. Registry (manual pins) wins, then PATH, then index."""
    if registry and registry.get(tool):
        p = Path(registry[tool])
        if p.exists():
            return str(p)
    if tool in _mem_cache:
        return _mem_cache[tool]
    hit = shutil.which(tool) or shutil.which(tool + ".exe")
    if hit:
        _mem_cache[tool] = hit
        return hit
    for cand in EXPLICIT_PATHS.get(tool, []):
        c = Path(os.path.expandvars(cand))
        if c.exists():
            _mem_cache[tool] = str(c)
            return str(c)
    idx = _walk_index()
    # bundled platform-tools live next to the app if bootstrapped
    local = APP_DIR / "platform-tools" / f"{tool}.exe"
    if local.exists():
        _mem_cache[tool] = str(local)
        return str(local)
    for g in TOOL_SPECS.get(tool, {}).get("glob", []):
        if g in idx:
            _mem_cache[tool] = idx[g]
            return idx[g]
    _mem_cache[tool] = None
    return None


def tool_report(registry: dict | None = None) -> dict:
    out = {}
    for name, spec in TOOL_SPECS.items():
        path = discover(name, registry)
        out[name] = {"path": path, "found": bool(path), "bundle": spec.get("bundle")}
    return out


def bootstrap_platform_tools() -> dict:
    """Download Google's official platform-tools into the app dir."""
    dest = APP_DIR / "platform-tools"
    if (dest / "adb.exe").exists():
        return {"ok": True, "path": str(dest), "note": "already installed"}
    tmp = APP_DIR / "platform-tools.zip"
    try:
        urllib.request.urlretrieve(PLATFORM_TOOLS_URL, tmp)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(APP_DIR)
        tmp.unlink(missing_ok=True)
        if (dest / "adb.exe").exists():
            _mem_cache.pop("adb", None)
            _mem_cache.pop("fastboot", None)
            return {"ok": True, "path": str(dest), "note": "installed"}
        return {"ok": False, "error": "archive did not contain adb.exe"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- device scan

def _run(argv, timeout=25):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 1, "", str(exc)


def scan_usb() -> list[dict]:
    if os.name != "nt":
        return []
    ps = (
        "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_[0-9A-Fa-f]{4}' } | "
        "ForEach-Object { \"$($_.Status)|$($_.Class)|$($_.FriendlyName)|$($_.InstanceId)\" }"
    )
    _, out, _ = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=40)
    devs = []
    for line in out.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) != 4:
            continue
        status, cls, name, inst = parts
        m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", inst)
        if not m:
            continue
        vid, pid = int(m.group(1), 16), int(m.group(2), 16)
        devs.append({"status": status, "class": cls, "name": name,
                     "vid": vid, "pid": pid, "brand": VID_MAP.get(vid), "instance": inst})
    return devs


def adb_devices(registry=None) -> list[dict]:
    adb = discover("adb", registry)
    if not adb:
        return []
    code, out, _ = _run([adb, "devices", "-l"])
    rows = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        p = line.split()
        if len(p) >= 2:
            rows.append({"serial": p[0], "state": p[1],
                         "props": dict(x.split(":", 1) for x in p[2:] if ":" in x)})
    return rows


def fastboot_devices(registry=None) -> list[str]:
    fb = discover("fastboot", registry)
    if not fb:
        return []
    _, out, _ = _run([fb, "devices"])
    return [l.split()[0] for l in out.splitlines() if l.strip()]


def adb_props(registry=None, keys=None) -> dict:
    adb = discover("adb", registry)
    if not adb:
        return {}
    keys = keys or ["ro.product.manufacturer", "ro.product.model", "ro.product.device",
                    "ro.build.version.release", "ro.build.version.sdk", "ro.serialno",
                    "ro.build.fingerprint"]
    out = {}
    for k in keys:
        _, val, _ = _run([adb, "shell", "getprop", k], timeout=10)
        out[k] = val.strip()
    _, bat, _ = _run([adb, "shell", "dumpsys", "battery"], timeout=10)
    m = re.search(r"level:\s*(\d+)", bat)
    if m:
        out["battery"] = m.group(1)
    return out


def scan(registry=None) -> dict:
    usb = scan_usb()
    adb = adb_devices(registry)
    fb = fastboot_devices(registry)
    state = "none"
    brand = None
    if adb:
        state = "adb"
    elif fb:
        state = "fastboot"
    else:
        for d in usb:
            if d["vid"] == 0x05C6 and d["pid"] in (0x9008, 0x9006):
                state, brand = "edl", "qualcomm"
                break
            if d["vid"] == 0x0E8D:
                state, brand = "preloader", "mediatek"
                break
        if state == "none":
            for d in usb:
                if d["brand"]:
                    state, brand = "usb", d["brand"]
                    break
    if brand is None and adb:
        brand = next((d["brand"] for d in usb if d["brand"]), None)
    props = adb_props(registry) if state == "adb" else {}
    return {"state": state, "brand_guess": brand, "usb": usb, "adb": adb,
            "fastboot": fb, "props": props, "ts": time.time()}


# ---------------------------------------------------------------- planning

def normalise_brand(value: str) -> str:
    v = (value or "").strip().lower()
    if v in BRANDS:
        return v
    for token, brand in BRAND_ALIASES.items():
        if token in v:
            return brand
    return "generic"


def _step(sid, title, detail="", kind="guide", risk="safe", cmd=None, tool=None):
    return {"id": sid, "title": title, "detail": detail, "kind": kind,
            "risk": risk, "cmd": cmd or [], "tool": tool}


INTENTS = {
    "diagnose": "Diagnose",
    "backup": "Back up",
    "flash": "Flash stock firmware",
    "restore": "Restore / unbrick",
    "frp": "Remove FRP (ownership verified)",
    "wipe": "Wipe / factory reset",
    "bootloader": "Bootloader unlock",
    "recovery": "Data recovery",
}

# Minimum risk each intent carries, independent of which tools are installed.
INTENT_RISK = {
    "diagnose": "safe",
    "backup": "safe",
    "recovery": "caution",
    "bootloader": "caution",
    "frp": "caution",
    "flash": "destructive",
    "restore": "destructive",
    "wipe": "destructive",
}


def plan(brand: str, intent: str, ctx: dict) -> dict:
    brand = normalise_brand(brand)
    ctx = ctx or {}
    tools = ctx.get("tools") or {}
    state = ctx.get("state") or "unknown"
    adb = tools.get("adb", {}).get("path")
    fb = tools.get("fastboot", {}).get("path")
    steps: list[dict] = []

    if intent == "diagnose":
        if adb:
            for k in ("ro.product.manufacturer", "ro.product.model", "ro.product.device",
                      "ro.build.version.release", "ro.build.version.sdk", "ro.serialno"):
                steps.append(_step(f"prop:{k}", k, "", "auto", "safe", [adb, "shell", "getprop", k]))
            steps.append(_step("battery", "Battery level", "", "auto", "safe", [adb, "shell", "dumpsys", "battery"]))
            steps.append(_step("storage", "Storage usage", "", "auto", "safe", [adb, "shell", "df", "-h", "/data"]))
            steps.append(_step("pkgs", "Installed package count", "", "auto", "safe",
                               [adb, "shell", "pm", "list", "packages"]))
        else:
            steps.append(_step("no-adb", "Start ADB", "Enable USB debugging, authorise the prompt, then rescan.",
                               "guide", "safe"))
        steps.append(_step("visual", "Physical check",
                           "Screen, touch, charge port, buttons, water indicators, IMEI on the tray vs *#06#.",
                           "guide", "safe"))

    elif intent == "backup":
        if adb:
            steps.append(_step("pull", "Pull /sdcard", "Photos, downloads, WhatsApp media, documents.",
                               "auto", "safe", [adb, "pull", "/sdcard/", str(APP_DIR / "backups" / "sdcard")]))
            steps.append(_step("apk", "Inventory installed apps", "", "auto", "safe",
                               [adb, "shell", "pm", "list", "packages", "-3"]))
            steps.append(_step("contacts", "Export contacts", "adb shell content query --uri content://contacts/people",
                               "auto", "caution",
                               [adb, "shell", "content", "query", "--uri", "content://contacts/people/"]))
        else:
            steps.append(_step("no-adb", "ADB required", "Enable debugging and authorise this PC.",
                               "guide", "safe"))

    elif intent == "flash":
        fam = ctx.get("firmware")
        if brand == "samsung":
            if tools.get("odin", {}).get("found"):
                steps.append(_step("odin", "Launch Odin",
                                   "AP / BL / CP / CSC into matching slots. HOME_CSC keeps data.",
                                   "launch", "destructive", tool="odin"))
            else:
                steps.append(_step("odin-missing", "Odin not installed",
                                   "Install Odin3 or Heimdall, then register the path.", "guide", "safe"))
            steps.append(_step("samfw", "Get firmware",
                               "SamFW or Frija: exact model + CSC. Verify the hash before flashing.",
                               "guide", "safe"))
        elif brand in ("google", "generic"):
            if adb:
                steps.append(_step("kill", "Stop adb server", "", "auto", "safe", [adb, "kill-server"]))
            if fb:
                steps.append(_step("fb", "Confirm fastboot", "", "auto", "safe", [fb, "devices"]))
                if fam and fam.lower().endswith(".zip"):
                    steps.append(_step("update", "fastboot update", fam, "launch", "destructive",
                                       [fb, "update", fam]))
                else:
                    steps.append(_step("flashall", "fastboot flashall", "Choose the factory image folder.",
                                       "guide", "destructive"))
            else:
                steps.append(_step("no-fb", "fastboot missing", "Install platform-tools.", "guide", "safe"))
        elif brand == "xiaomi":
            if tools.get("miflash", {}).get("found"):
                steps.append(_step("miflash", "Launch MiFlash", "Select the ROM folder, 'clean all'. Never lock.",
                                   "launch", "destructive", tool="miflash"))
            else:
                steps.append(_step("miflash-missing", "MiFlash not installed", "Install XiaoMiFlash.",
                                   "guide", "safe"))
        elif brand == "mediatek":
            if tools.get("spflash", {}).get("found"):
                steps.append(_step("spflash", "Launch SP Flash Tool",
                                   "Download Only. Never Format All + Download.", "launch", "destructive",
                                   tool="spflash"))
            if tools.get("mtkclient", {}).get("found"):
                steps.append(_step("mtk-backup", "Backup partitions first",
                                   "mtkclient r boot recovery", "guide", "caution"))
            if not (tools.get("spflash", {}).get("found") or tools.get("mtkclient", {}).get("found")):
                steps.append(_step("mtk-missing", "MTK tools missing",
                                   "Install SP Flash Tool or bkerler/mtkclient.", "guide", "safe"))
        elif brand == "qualcomm":
            if tools.get("edl", {}).get("found"):
                steps.append(_step("edl-backup", "Backup before writing", "edl rl boot recovery", "guide", "caution"))
            if tools.get("qfil", {}).get("found"):
                steps.append(_step("qfil", "Launch QFIL", "Flat build, matching programmer, rawprogram + patch.",
                                   "launch", "destructive", tool="qfil"))
            else:
                steps.append(_step("qc-missing", "QFIL/edl missing",
                                   "Install QFIL or bkerler/edl.", "guide", "safe"))
        elif brand == "apple":
            if tools.get("3utools", {}).get("found"):
                steps.append(_step("3u", "Launch 3uTools", "Flash & JB > Easy Flash. Signed IPSW only.",
                                   "launch", "destructive", tool="3utools"))
            else:
                steps.append(_step("3u-missing", "3uTools not installed",
                                   "Free, current, covers iOS restore and IPSW download.", "guide", "safe"))

    elif intent == "restore":
        steps.append(_step("power", "Force off first",
                           "Hold power 10-15 s (or power + volume down). Then enter the boot mode "
                           "for this brand.", "guide", "safe"))
        if adb:
            steps.append(_step("reboot-bl", "Reboot to bootloader", "", "auto", "caution",
                               [adb, "reboot", "bootloader"]))
            steps.append(_step("reboot-dl", "Or reboot to download mode",
                               "Samsung: adb reboot download", "guide", "caution"))
        steps.append(_step("flash", "Flash stock firmware",
                           "Unbrick = full stock image for the exact model. Never a partial write.",
                           "guide", "destructive"))
        steps.append(_step("verify", "Verify after boot",
                           "IMEI (*#06#), Wi-Fi, calls, camera, sensors, battery health.", "guide", "safe"))

    elif intent == "frp":
        steps.append(_step("owner", "Owner signs in",
                           "The bound Google/Samsung account, or the screen-lock PIN. Zero risk.",
                           "guide", "safe"))
        steps.append(_step("receipt", "Vendor service",
                           "Samsung/Google service centre with the receipt and ID. Zero risk.",
                           "guide", "safe"))
        steps.append(_step("server", "Server-side unlock",
                           "Paid but clean: UnlockTool / Chimera / TFT with a valid licence.",
                           "guide", "caution"))
        steps.append(_step("combo", "Combination firmware (last resort)",
                           "Must match model + region + CSC exactly, then re-flash stock. "
                           "Wrong region = dead radio.", "guide", "destructive"))
        steps.append(_step("never", "Never hand-write persist/efs/nvram",
                           "That is what kills IMEI and Wi-Fi, permanently.", "guide", "destructive"))

    elif intent == "wipe":
        steps.append(_step("confirm", "Confirm authority",
                           "Wipe destroys data. Only with a signed job record.", "guide", "destructive"))
        if adb:
            steps.append(_step("wipe-adb", "Factory reset via ADB", "", "auto", "destructive",
                               [adb, "shell", "am", "broadcast", "-a", "android.intent.action.MASTER_CLEAR"]))
        steps.append(_step("recovery", "Or recovery mode",
                           "Volume up + power > Wipe data/factory reset.", "guide", "destructive"))

    elif intent == "bootloader":
        if adb:
            steps.append(_step("reboot", "Reboot to bootloader", "", "auto", "caution",
                               [adb, "reboot", "bootloader"]))
        if fb:
            steps.append(_step("unlock", "fastboot flashing unlock",
                               "Wipes userdata and voids some warranties. Pixel/Google only by default.",
                               "launch", "destructive", [fb, "flashing", "unlock"]))
        steps.append(_step("vendor", "Vendor-specific unlock",
                           "Xiaomi: Mi Unlock + 7-day wait. Samsung: Knox trips permanently.",
                           "guide", "caution"))

    elif intent == "recovery":
        steps.append(_step("stop", "Stop using the device",
                           "Every write reduces the chance of recovery.", "guide", "safe"))
        steps.append(_step("backup", "Image the storage first",
                           "Rooted: dd the userdata partition. Otherwise use a chip-off or "
                           "a professional lab.", "guide", "caution"))
        steps.append(_step("tools", "Recovery tools",
                           "PhotoRec/TestDisk on a raw image; commercial labs for NAND failures.",
                           "guide", "safe"))

    if not steps:
        steps.append(_step("none", "Nothing planned", "Pick a valid intent.", "guide", "safe"))

    # An intent carries its own floor: "flash" is destructive even when the
    # flashing tool is missing, so the UI never labels it safe.
    RISK_ORDER = {"safe": 0, "caution": 1, "destructive": 2}
    risk = INTENT_RISK.get(intent, "safe")
    for s in steps:
        if RISK_ORDER[s["risk"]] > RISK_ORDER[risk]:
            risk = s["risk"]

    return {
        "brand": brand,
        "brand_label": BRANDS[brand]["label"],
        "intent": intent,
        "intent_label": INTENTS.get(intent, intent),
        "risk": risk,
        "steps": steps,
        "rules": BRANDS[brand]["rules"] + GENERIC_RULES,
        "firmware_hint": BRANDS[brand]["firmware_hint"],
        "sources": BRANDS[brand]["sources"],
        "state": state,
    }
