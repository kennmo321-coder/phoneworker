"""phonebench.tui - full-screen terminal app, no dependencies.

Windows: uses msvcrt + ANSI via the console VT flag.
POSIX:   uses termios/tty raw mode.

Keys
  up/down    move            left/right   change brand (workflow)
  tab        next screen     enter        act / next field
  r          rescan          x            execute plan
  q / esc    quit / back     ?            help
"""
from __future__ import annotations

import os
import shutil
import sys
import textwrap

from . import core, jobs

# ---------------------------------------------------------------- terminal io

IS_WIN = os.name == "nt"

STYLES = {
    "": "",
    "dim": "\x1b[38;5;245m",
    "accent": "\x1b[38;5;214m",
    "ok": "\x1b[38;5;42m",
    "bad": "\x1b[38;5;203m",
    "warn": "\x1b[38;5;179m",
    "bold": "\x1b[1m",
    "title": "\x1b[1m\x1b[38;5;214m",
    "inv": "\x1b[7m",
}
RESET = "\x1b[0m"


def enable_vt() -> None:
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


def size() -> tuple[int, int]:
    s = shutil.get_terminal_size((100, 30))
    return max(s.columns, 60), max(s.lines, 18)


class Canvas:
    """Cell grid with per-cell style, flushed in one write."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.buf = [[(" ", "") for _ in range(w)] for _ in range(h)]

    def put(self, x: int, y: int, text: str, style: str = "") -> int:
        if y < 0 or y >= self.h:
            return x
        for ch in text:
            if 0 <= x < self.w:
                self.buf[y][x] = (ch, style)
            x += 1
            if x >= self.w:
                break
        return x

    def fill(self, x: int, y: int, w: int, h: int, style: str = "") -> None:
        for yy in range(y, min(y + h, self.h)):
            for xx in range(x, min(x + w, self.w)):
                if xx >= 0 and yy >= 0:
                    self.buf[yy][xx] = (" ", style)

    def hline(self, x: int, y: int, w: int, ch: str = "─", style: str = "dim") -> None:
        self.put(x, y, ch * w, style)

    def box(self, x: int, y: int, w: int, h: int, title: str = "", style: str = "dim") -> None:
        if w < 2 or h < 2:
            return
        self.put(x, y, "┌" + "─" * (w - 2) + "┐", style)
        for yy in range(y + 1, y + h - 1):
            self.put(x, yy, "│", style)
            self.put(x + w - 1, yy, "│", style)
        self.put(x, y + h - 1, "└" + "─" * (w - 2) + "┘", style)
        if title:
            self.put(x + 2, y, f" {title} ", "title")

    def flush(self) -> None:
        out = ["\x1b[H"]
        for row in self.buf:
            cur = None
            for ch, st in row:
                if st != cur:
                    out.append(RESET + (STYLES.get(st, "") if st else ""))
                    cur = st
                out.append(ch)
            out.append(RESET + "\n")
        out.append("\x1b[J")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def to_text(self) -> str:
        return "\n".join("".join(c for c, _ in row).rstrip() for row in self.buf)


def read_key() -> str:
    if IS_WIN:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right",
                    "S": "delete"}.get(code, "")
        if ch == "\r":
            return "enter"
        if ch == "\t":
            return "tab"
        if ch == "\x1b":
            return "esc"
        if ch == "\x08":
            return "backspace"
        if ch == "\x13":
            return "save"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\t":
            return "tab"
        if ch in ("\x7f", "\x08"):
            return "backspace"
        if ch == "\x13":
            return "save"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------- form model

FIELDS = [
    ("brand", "Brand"),
    ("model", "Model"),
    ("serial", "Serial"),
    ("fault", "Fault"),
    ("note", "Note"),
]
ATTEST_ROW = len(FIELDS)

BRAND_ORDER = ["samsung", "google", "xiaomi", "apple", "mediatek", "qualcomm", "generic"]


class App:
    def __init__(self):
        self.screens = ["bench", "intake", "workflow", "vault", "ledger", "help"]
        self.titles = {"bench": "Bench", "intake": "Intake", "workflow": "Workflow",
                       "vault": "Vault", "ledger": "Ledger", "help": "Help"}
        self.screen = 0
        self.msg = ""
        self.msg_style = "dim"

        self.registry = self._load_registry()
        self.device = {"state": "none", "props": {}}
        self.tools = {}
        self.resources = core.RESOURCES

        self.form = {k: "" for k, _ in FIELDS}
        self.form["brand"] = "samsung"
        self.attested = False
        self.field = 0
        self.job = None

        self.intent_idx = 0
        self.intents = list(core.INTENTS.items())
        self.brand_idx = 0
        self.vault_idx = 0
        self.selected_firmware_id = None
        self.plan = None
        self.jobs_cache = []
        self.ledger_cache = []
        self.modal = None
        self.modal_buf = ""

        self.rescan()

    # ------------------------------------------------------------ data
    def _load_registry(self) -> dict:
        import json
        p = core.APP_DIR / "registry.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("tools", {})
            except Exception:
                pass
        return {}

    def rescan(self):
        self.device = core.scan(self.registry)
        self.tools = core.tool_report(self.registry)
        found = sum(1 for t in self.tools.values() if t["found"])
        self.say(f"scanned - {self.device['state']}, {found} tools", "dim")

    def say(self, text: str, style: str = "dim"):
        self.msg = text
        self.msg_style = style

    def current_job_id(self) -> str:
        return (self.job or {}).get("job_id", "")

    # ------------------------------------------------------------ draw
    def draw(self) -> Canvas:
        w, h = size()
        c = Canvas(w, h)
        self.draw_header(c, w, h)
        body_y = 2
        body_h = h - 3
        if self.screen == 0:
            self.draw_bench(c, 0, body_y, w, body_h)
        elif self.screen == 1:
            self.draw_intake(c, 0, body_y, w, body_h)
        elif self.screen == 2:
            self.draw_workflow(c, 0, body_y, w, body_h)
        elif self.screen == 3:
            self.draw_vault(c, 0, body_y, w, body_h)
        elif self.screen == 4:
            self.draw_ledger(c, 0, body_y, w, body_h)
        else:
            self.draw_help(c, 0, body_y, w, body_h)
        self.draw_status(c, w, h)
        if self.modal:
            self.draw_modal(c, w, h)
        return c

    def draw_header(self, c: Canvas, w: int, h: int):
        dev = self.device
        state = dev.get("state", "none")
        model = (dev.get("props") or {}).get("ro.product.model", "")
        brand = dev.get("brand_guess") or ""
        found = sum(1 for t in self.tools.values() if t["found"])

        c.fill(0, 0, w, 1, "inv")
        c.put(1, 0, " phonebench ", "title")
        dot = "●" if state != "none" else "○"
        c.put(15, 0, f"{dot} {state}", "ok" if state != "none" else "bad")
        sim_tag = " [SIMULATED DEVICES]" if core.simulation_active() else ""
        if model:
            c.put(15 + len(state) + 4, 0, f"{model}{sim_tag}", "warn" if sim_tag else "bold")
        elif brand:
            c.put(15 + len(state) + 4, 0, f"{brand}{sim_tag}", "warn" if sim_tag else "bold")
        elif sim_tag:
            c.put(15 + len(state) + 4, 0, f"{sim_tag.strip()}", "warn")
        c.put(w - 26, 0, f"{found} tools  {self.current_job_id() or 'no job'}"[:25], "dim")

        tabs = []
        for i, s in enumerate(self.screens):
            label = f" {self.titles[s]} "
            tabs.append(label)
        x = 1
        for i, label in enumerate(tabs):
            st = "accent" if i == self.screen else "dim"
            c.put(x, 1, label, st + ("\x1b[1m" if i == self.screen else ""))
            x += len(label) + 1

    def draw_status(self, c: Canvas, w: int, h: int):
        c.fill(0, h - 1, w, 1, "inv")
        hint = "↑↓ move  ←→ brand  tab screen  enter act  r rescan  q quit"
        c.put(1, h - 1, hint, "dim")
        if self.msg:
            m = self.msg[: max(0, w - len(hint) - 4)]
            c.put(w - len(m) - 2, h - 1, m, self.msg_style)

    def draw_bench(self, c: Canvas, x: int, y: int, w: int, h: int):
        lw = max(38, w // 2 - 1)
        c.box(x, y, lw, h, "device")
        d = self.device
        p = d.get("props") or {}
        rows = [
            ("state", d.get("state", "none")),
            ("brand", d.get("brand_guess") or "—"),
            ("model", p.get("ro.product.model") or "—"),
            ("android", p.get("ro.build.version.release") or "—"),
            ("sdk", p.get("ro.build.version.sdk") or "—"),
            ("serial", p.get("ro.serialno") or "—"),
            ("battery", (p.get("battery") + "%") if p.get("battery") else "—"),
        ]
        yy = y + 1
        for k, v in rows:
            c.put(x + 2, yy, f"{k:<10}", "dim")
            c.put(x + 13, yy, str(v)[: lw - 15], "bold" if k == "model" else "")
            yy += 1
        if d.get("state") == "none":
            yy += 1
            for line in textwrap.wrap(
                    "Nothing enumerating. Check the cable (data, not charge-only), the port, "
                    "and the phone's USB mode.", lw - 4):
                c.put(x + 2, yy, line, "warn")
                yy += 1

        rx = x + lw
        rw = w - lw
        c.box(rx, y, rw, h, "tools")
        yy = y + 1
        half = (len(self.tools) + 1) // 2
        items = list(self.tools.items())
        for i, (name, info) in enumerate(items):
            col, row = divmod(i, half)
            xx = rx + 2 + col * (rw // 2)
            st = "ok" if info["found"] else "dim"
            mark = "✓" if info["found"] else "·"
            c.put(xx, yy + row, f"{mark} {name}", st)

        ry = y + half + 2
        if ry < y + h - 2:
            c.hline(rx + 1, ry, rw - 2, "─", "dim")
            c.put(rx + 2, ry + 1, "resources", "dim")
            yy = ry + 2
            name_w = max((len(r["name"]) for r in self.resources), default=10) + 2
            for r in self.resources[: max(0, y + h - yy - 1)]:
                avail = max(4, rw - 4 - name_w)
                c.put(rx + 2, yy, r["name"], "accent")
                c.put(rx + 2 + name_w, yy, r["note"][:avail], "dim")
                yy += 1

    def draw_intake(self, c: Canvas, x: int, y: int, w: int, h: int):
        c.box(x, y, w, h, "intake - device only, no client data")
        c.put(x + 2, y + 1,
              "Check the ID and receipt yourself. Only the fact that you did is recorded."[: w - 4],
              "dim")
        yy = y + 3
        for i, (key, label) in enumerate(FIELDS):
            sel = i == self.field
            st = "inv" if sel else ""
            if sel:
                c.fill(x + 1, yy, w - 2, 1, "inv")
            c.put(x + 3, yy, ("› " if sel else "  ") + f"{label:<12}", st or "")
            val = self.form.get(key, "")
            shown = val if len(val) < w - 24 else val[: w - 27] + "..."
            c.put(x + 18, yy, shown, st or "bold")
            if sel:
                c.put(x + 18 + len(shown), yy, "▏", "accent")
            yy += 1

        yy += 1
        sel = self.field == ATTEST_ROW
        st = "inv" if sel else ""
        if sel:
            c.fill(x + 1, yy, w - 2, 3, "inv")
        mark = "[x]" if self.attested else "[ ]"
        c.put(x + 3, yy, f"{'› ' if sel else '  '}{mark} ownership verified", st or "")
        c.put(x + 3, yy + 1, "      ID + proof of purchase seen in person", st or "dim")
        c.put(x + 3, yy + 2, "      space toggles · nothing is copied or stored", st or "dim")

        if self.job:
            yy += 4
            c.put(x + 3, yy, f"job {self.job['job_id']} open", "ok")
            c.put(x + 3, yy + 1,
                  f"{self.job['brand']} {self.job['model']}"
                  + (f"  serial {self.job['serial']}" if self.job.get("serial") else ""), "dim")
            c.put(x + 3, yy + 2, "tab → Workflow to build the plan", "dim")

    def draw_workflow(self, c: Canvas, x: int, y: int, w: int, h: int):
        lw = 28
        c.box(x, y, lw, 14, "intent")
        for i, (k, label) in enumerate(self.intents):
            sel = i == self.intent_idx
            st = "accent" if sel else "dim"
            c.put(x + 2, y + 1 + i, ("› " if sel else "  ") + label[: lw - 5], st)

        bx = x + lw
        bw = w - lw
        c.box(bx, y, bw, 14, "brand")
        brand = BRAND_ORDER[self.brand_idx]
        c.put(bx + 2, y + 1, f"‹ {core.BRANDS[brand]['label']} ›", "bold")

        if self.selected_firmware_id:
            from . import firmware
            fw_res = firmware.get_firmware(self.selected_firmware_id)
            if fw_res.get("ok"):
                fw_label = f"firmware: {fw_res['firmware']['id']} ({fw_res['firmware']['model_hint']})"
            else:
                fw_label = f"firmware: {self.selected_firmware_id}"
            c.put(bx + bw - len(fw_label) - 2, y + 1, fw_label, "ok")
        else:
            c.put(bx + bw - 26, y + 1, "no firmware selected", "dim")

        c.put(bx + 2, y + 3, core.BRANDS[brand]["firmware_hint"][: bw - 4], "dim")
        yy = y + 5
        for rule in core.BRANDS[brand]["rules"][:5]:
            for line in textwrap.wrap("• " + rule, bw - 4)[:2]:
                if yy < y + 13:
                    c.put(bx + 2, yy, line, "dim")
                    yy += 1

        py = y + 14
        ph = h - 14
        if ph < 3:
            return
        title = "plan"
        if self.plan:
            title = (f"plan - {self.plan['brand_label']} - {self.plan['intent_label']} "
                     f"[{self.plan['risk']}]")
        c.box(x, py, w, ph, title)
        if not self.plan:
            c.put(x + 2, py + 1, "enter builds the plan · x executes (needs a job and RUN)", "dim")
            return
        risk_style = {"safe": "ok", "caution": "warn", "destructive": "bad"}[self.plan["risk"]]
        c.put(x + 2, py + 1, f"risk: {self.plan['risk']}", risk_style)
        gate = self.plan.get("gate")
        if gate and not gate["ok"]:
            c.put(x + 20, py + 1, "gate blocked: " + "; ".join(gate["reasons"])[: w - 26], "bad")
        elif not gate:
            c.put(x + 20, py + 1, "no job selected - execution disabled", "warn")
        yy = py + 3
        for i, s in enumerate(self.plan["steps"], 1):
            if yy >= py + ph - 1:
                break
            st = {"safe": "ok", "caution": "warn", "destructive": "bad"}[s["risk"]]
            c.put(x + 2, yy, f"{i}. {s['title']}"[: w - 14], "")
            c.put(w - 12, yy, f"[{s['risk']}]", st)
            yy += 1
            if s.get("detail") and yy < py + ph - 1:
                for line in textwrap.wrap(s["detail"], w - 6)[:2]:
                    if yy >= py + ph - 1:
                        break
                    c.put(x + 5, yy, line, "dim")
                    yy += 1

    def draw_vault(self, c: Canvas, x: int, y: int, w: int, h: int):
        from . import firmware
        res = firmware.list_firmware()
        pkgs = res.get("packages", []) if res.get("ok") else []

        sel_info = f"selected: {self.selected_firmware_id}" if self.selected_firmware_id else "none selected"
        c.box(x, y, w, h, f"vault - firmware library ({len(pkgs)}) [{sel_info}]")

        dev_model = (self.device.get("props") or {}).get("ro.product.model", "")
        dev_brand = self.device.get("brand_guess", "")
        dev_state = self.device.get("state", "none")
        has_device = dev_state != "none" and bool(dev_model or dev_brand)

        if not pkgs:
            c.put(x + 2, y + 1, "no packages in vault - use 'pb firmware add <path>' to register", "dim")
            return

        if self.vault_idx >= len(pkgs):
            self.vault_idx = max(0, len(pkgs) - 1)

        c.put(x + 2, y + 1, "↑↓ move cursor  enter select package  d / esc clear selection", "dim")
        c.put(x + 2, y + 2, f"{'':<3}{'ID':<14}{'MODEL HINT':<18}{'SIZE':<12}{'HASH':<14}{'MATCH':<12}{'FILENAME'}", "dim")

        for i, p in enumerate(pkgs[: h - 4]):
            pkg_id = p.get("id", "")
            model_hint = (p.get("model_hint") or "generic")[:16]
            size_mb = f"{p.get('size', 0) / (1024 * 1024):.1f} MB"
            hash_12 = p.get("sha256", "")[:12]
            filename = (p.get("filename") or "")[: max(10, w - 75)]

            is_cursor = i == self.vault_idx
            is_selected = pkg_id == self.selected_firmware_id

            if not has_device:
                match_str = "no device"
                match_st = "dim"
            else:
                target_model = (dev_model or dev_brand).lower()
                m_hint = model_hint.lower()
                if m_hint in target_model or target_model in m_hint:
                    match_str = "✓ match"
                    match_st = "ok"
                else:
                    match_str = "× mismatch"
                    match_st = "bad"

            prefix = "› " if is_cursor else "  "
            mark = "*" if is_selected else " "
            row_st = "inv" if is_cursor else ("bold" if is_selected else "")

            yy = y + 3 + i
            if is_cursor:
                c.fill(x + 1, yy, w - 2, 1, "inv")

            c.put(x + 2, yy, f"{prefix}{mark}", "accent" if is_selected and not is_cursor else row_st)
            c.put(x + 5, yy, f"{pkg_id:<14}", row_st or "bold")
            c.put(x + 19, yy, f"{model_hint:<18}", row_st)
            c.put(x + 37, yy, f"{size_mb:<12}", row_st)
            c.put(x + 49, yy, f"{hash_12:<14}", row_st or "dim")
            c.put(x + 63, yy, f"{match_str:<12}", row_st or match_st)
            c.put(x + 75, yy, filename, row_st or "dim")

    def draw_ledger(self, c: Canvas, x: int, y: int, w: int, h: int):
        top_h = max(6, h // 2)
        c.box(x, y, w, top_h, f"jobs ({len(self.jobs_cache)})")
        if not self.jobs_cache:
            c.put(x + 2, y + 1, "no jobs yet - go to Intake", "dim")
        else:
            c.put(x + 2, y + 1, f"{'job':<16}{'model':<18}{'serial':<16}{'fault':<16}{'status':<8}", "dim")
            for i, j in enumerate(self.jobs_cache[: top_h - 3]):
                c.put(x + 2, y + 2 + i,
                      f"{j['job_id']:<16}{(j['model'] or '')[:16]:<18}"
                      f"{(j['serial'] or '')[:14]:<16}{(j['fault'] or '')[:14]:<16}"
                      f"{j['status'] or '':<8}")
        ly = y + top_h
        lh = h - top_h
        c.box(x, ly, w, lh, "ledger")
        for i, e in enumerate(self.ledger_cache[: lh - 2]):
            ts = (e.get("ts") or "")[11:19]
            body = e.get("summary") or e.get("client") or e.get("status") or ""
            c.put(x + 2, ly + 1 + i,
                  f"{ts}  {e.get('kind',''):<10}{e.get('job','') or '':<22}{body}"[: w - 3])

    def draw_help(self, c: Canvas, x: int, y: int, w: int, h: int):
        c.box(x, y, w, h, "help")
        lines = [
            ("keys", "accent"),
            ("  ↑ ↓            move selection", ""),
            ("  ← →            change brand (workflow)", ""),
            ("  tab            next screen", ""),
            ("  enter          next field / build plan / submit", ""),
            ("  x              execute plan (asks for RUN)", ""),
            ("  r              rescan devices and tools", ""),
            ("  i              install platform-tools (adb, fastboot)", ""),
            ("  q / esc        quit / close dialog", ""),
            ("", ""),
            ("the gate", "accent"),
            ("  Run needs a device job plus your attestation that you saw", ""),
            ("  a government ID and a proof of purchase, in person.", ""),
            ("  No names, no numbers, no scans are stored on this machine.", ""),
            ("  Brand and model are checked against the attached device.", ""),
            ("  Type RUN to confirm. Read-only diagnosis runs freely.", ""),
            ("", ""),
            ("safety", "accent"),
            ("  Flash  : exact model + region. HOME_CSC keeps data.", ""),
            ("  MTK    : Download Only. Format All wipes IMEI.", ""),
            ("  Qualcomm: back up with edl before writing.", ""),
            ("  FRP    : owner -> vendor -> licensed -> combo firmware.", ""),
            ("  Never write persist / efs / nvram by hand.", ""),
        ]
        yy = y + 1
        for text, st in lines:
            if yy >= y + h - 1:
                break
            c.put(x + 2, yy, text[: w - 4], st)
            yy += 1

    def draw_modal(self, c: Canvas, w: int, h: int):
        mw, mh = min(60, w - 4), 7
        mx, my = (w - mw) // 2, (h - mh) // 2
        c.fill(mx, my, mw, mh, "")
        c.box(mx, my, mw, mh, "confirm", "warn")
        c.put(mx + 2, my + 2, "This executes the plan on the device.", "warn")
        c.put(mx + 2, my + 3, "Type RUN and press enter:", "dim")
        c.put(mx + 2, my + 4, self.modal_buf + "▏", "accent")

    # ------------------------------------------------------------ actions
    def action_intake(self):
        if not self.attested:
            self.say("check the ID and receipt in person, then press space to attest", "bad")
            return
        fields = dict(self.form)
        fields["attestation"] = {"id_checked": True, "receipt_checked": True}
        try:
            res = jobs.create(fields)
        except Exception as exc:
            self.say(f"intake failed: {exc}", "bad")
            return
        if not res.get("ok"):
            self.say(res.get("error", "intake failed"), "bad")
            return
        self.job = res["job"]
        self.say(f"job {self.job['job_id']} open - no personal data stored", "ok")
        self.load_ledger()

    def action_plan(self):
        brand = BRAND_ORDER[self.brand_idx]
        intent = self.intents[self.intent_idx][0]
        job_model = (self.job or {}).get("model")
        self.plan = core.plan(brand, intent, {
            "tools": self.tools,
            "state": self.device.get("state"),
            "firmware_id": self.selected_firmware_id,
            "model": job_model,
        })
        if self.current_job_id():
            self.plan["gate"] = jobs.gate(
                self.current_job_id(), brand, job_model, self.device, firmware_id=self.selected_firmware_id
            )
        else:
            self.plan["gate"] = None
        if self.plan.get("blocked"):
            self.say(f"plan blocked: {self.plan.get('block_reason')}", "bad")
        else:
            self.say(f"plan: {len(self.plan['steps'])} steps, risk {self.plan['risk']}",
                     "warn" if self.plan["risk"] != "safe" else "ok")

    def action_run(self):
        if not self.plan:
            self.say("build a plan first (enter)", "warn")
            return
        if self.plan.get("blocked"):
            self.say(f"blocked: {self.plan.get('block_reason')}", "bad")
            return
        if not self.current_job_id():
            self.say("select a job first", "bad")
            return
        job_model = (self.job or {}).get("model")
        gate = jobs.gate(
            self.current_job_id(), BRAND_ORDER[self.brand_idx], job_model, self.device, firmware_id=self.selected_firmware_id
        )
        if not gate["ok"]:
            self.say("gate blocked: " + "; ".join(gate["reasons"])[:60], "bad")
            return
        self.modal = "run"
        self.modal_buf = ""

    def execute(self):
        if self.plan and self.plan.get("blocked"):
            self.say(f"blocked: {self.plan.get('block_reason')}", "bad")
            return
        results = []
        for s in self.plan["steps"]:
            if s["kind"] == "auto" and s["cmd"]:
                from .server import run_step
                results.append(run_step(s))
            elif s["kind"] == "launch" and s.get("tool"):
                path = core.discover(s["tool"], self.registry)
                if path:
                    import subprocess
                    try:
                        subprocess.Popen([path], cwd=os.path.dirname(path))
                        results.append({"id": s["id"], "ok": True, "launched": path})
                    except OSError as exc:
                        results.append({"id": s["id"], "ok": False, "err": str(exc)})
                else:
                    results.append({"id": s["id"], "ok": False, "err": f"not installed: {s['tool']}"})
            else:
                results.append({"id": s["id"], "ok": True, "guide": s.get("detail", "")})
        ok = sum(1 for r in results if r.get("ok"))
        jobs.record_operation(self.current_job_id(), self.plan["intent"],
                              f"{self.plan['intent_label']} on {self.plan['brand_label']}",
                              [{"id": r["id"], "ok": r.get("ok")} for r in results])
        self.say(f"executed {ok}/{len(results)} steps", "ok" if ok == len(results) else "warn")
        self.load_ledger()

    def load_ledger(self):
        self.jobs_cache = jobs.list_jobs()
        self.ledger_cache = jobs.ledger_read(120)

    # ------------------------------------------------------------ loop
    def handle(self, key: str) -> bool:
        if self.modal:
            if key == "esc":
                self.modal = None
                return True
            if key == "backspace":
                self.modal_buf = self.modal_buf[:-1]
                return True
            if key == "enter":
                if self.modal_buf == "RUN":
                    self.modal = None
                    self.execute()
                else:
                    self.modal = None
                    self.say("cancelled", "dim")
                return True
            if len(key) == 1 and key.isprintable():
                self.modal_buf += key
            return True

        if key == "q":
            return False
        if key == "tab":
            self.screen = (self.screen + 1) % len(self.screens)
            if self.screens[self.screen] == "ledger":
                self.load_ledger()
            return True

        if self.screen == 0:
            if key == "r":
                self.rescan()
            elif key == "i":
                self.say("installing platform-tools…", "dim")
                r = core.bootstrap_platform_tools()
                self.rescan()
                self.say("platform-tools ready" if r.get("ok") else r.get("error", "failed"),
                         "ok" if r.get("ok") else "bad")

        elif self.screen == 1:
            nrows = len(FIELDS) + 1
            if key == "down":
                self.field = (self.field + 1) % nrows
            elif key == "up":
                self.field = (self.field - 1) % nrows
            elif key == " " and self.field == ATTEST_ROW:
                self.attested = not self.attested
            elif key == "backspace" and self.field < ATTEST_ROW:
                k = FIELDS[self.field][0]
                self.form[k] = self.form[k][:-1]
            elif key == "enter":
                if self.field >= ATTEST_ROW:
                    self.action_intake()
                else:
                    self.field += 1
            elif len(key) == 1 and key.isprintable() and self.field < ATTEST_ROW:
                k = FIELDS[self.field][0]
                self.form[k] += key

        elif self.screen == 2:
            if key == "down":
                self.intent_idx = (self.intent_idx + 1) % len(self.intents)
            elif key == "up":
                self.intent_idx = (self.intent_idx - 1) % len(self.intents)
            elif key == "right":
                self.brand_idx = (self.brand_idx + 1) % len(BRAND_ORDER)
            elif key == "left":
                self.brand_idx = (self.brand_idx - 1) % len(BRAND_ORDER)
            elif key == "enter":
                self.action_plan()
            elif key == "x":
                self.action_run()

        elif self.screen == 3:
            from . import firmware
            pkgs = firmware.list_firmware().get("packages", [])
            if key == "down" and pkgs:
                self.vault_idx = (self.vault_idx + 1) % len(pkgs)
            elif key == "up" and pkgs:
                self.vault_idx = (self.vault_idx - 1) % len(pkgs)
            elif key == "enter" and pkgs:
                if 0 <= self.vault_idx < len(pkgs):
                    selected = pkgs[self.vault_idx]
                    self.selected_firmware_id = selected["id"]
                    self.say(f"selected firmware {selected['id']} ({selected.get('model_hint')})", "ok")
            elif key in ("d", "esc"):
                self.selected_firmware_id = None
                self.say("no firmware selected", "dim")

        elif self.screen == 4:
            if key in ("r", "enter"):
                self.load_ledger()

        return True

    def run(self):
        enable_vt()
        sys.stdout.write("\x1b[?25l\x1b[2J")  # hide cursor, clear
        try:
            while True:
                self.draw().flush()
                key = read_key()
                if not self.handle(key):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write(RESET + "\x1b[?25h\x1b[2J\x1b[H")
            sys.stdout.flush()


def main() -> int:
    App().run()
    return 0


def preview() -> int:
    """Headless render - used for testing layout without a TTY."""
    app = App()
    for idx in range(len(app.screens)):
        app.screen = idx
        if app.screens[idx] == "ledger":
            app.load_ledger()
        if app.screens[idx] == "workflow":
            app.action_plan()
        print(f"\n===== {app.titles[app.screens[idx]]} =====")
        print(app.draw().to_text())
    return 0
