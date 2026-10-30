"""phonebench.server - local HTTP app (127.0.0.1 only)."""
from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import core, jobs

HERE = Path(__file__).resolve().parent
REGISTRY = core.APP_DIR / "registry.json"


def registry() -> dict:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tools": {}}


def plan_commands(plan: dict, reg: dict | None = None) -> list[dict]:
    reg_tools = (reg or {}).get("tools") if reg else registry().get("tools")
    steps = (plan or {}).get("steps", [])
    out = []
    for idx, s in enumerate(steps, 1):
        kind = s.get("kind", "guide")
        risk = s.get("risk", "safe")
        step_id = s.get("id", "")
        title = s.get("title", "")
        detail = s.get("detail", "")

        if kind == "auto" and s.get("cmd"):
            cmd = list(s["cmd"])
            if cmd:
                tool_name = cmd[0]
                resolved = core.discover(tool_name, reg_tools) or tool_name
                cmd[0] = resolved
                tool_path = resolved
            else:
                tool_path = None

            out.append({
                "n": idx,
                "id": step_id,
                "title": title,
                "kind": "auto",
                "argv": cmd,
                "tool_path": tool_path,
                "risk": risk,
            })
        elif kind == "launch" and s.get("tool"):
            tool_name = s["tool"]
            path = core.discover(tool_name, reg_tools)
            if path:
                out.append({
                    "n": idx,
                    "id": step_id,
                    "title": title,
                    "kind": "launch",
                    "argv": [path],
                    "tool_path": path,
                    "risk": risk,
                })
            else:
                out.append({
                    "n": idx,
                    "id": step_id,
                    "title": title,
                    "kind": "guide",
                    "text": f"tool not installed: {tool_name}",
                    "risk": risk,
                    "missing": True,
                })
        else:
            text_str = detail if detail else "guide only - nothing to execute"
            out.append({
                "n": idx,
                "id": step_id,
                "title": title,
                "kind": "guide",
                "text": text_str,
                "risk": risk,
            })
    return out


def run_step(step: dict, timeout: int = 180) -> dict:
    argv = step.get("argv") or step.get("cmd") or []
    if not argv:
        return {"id": step.get("id", ""), "ok": True, "skipped": True}
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return {"id": step.get("id", ""), "ok": r.returncode == 0, "code": r.returncode,
                "out": (r.stdout or "")[:20000], "err": (r.stderr or "")[:4000]}
    except FileNotFoundError:
        return {"id": step.get("id", ""), "ok": False, "code": 127, "err": "not found", "out": ""}
    except subprocess.TimeoutExpired:
        return {"id": step.get("id", ""), "ok": False, "code": 124, "err": f"timeout after {timeout}s", "out": ""}
    except OSError as exc:
        return {"id": step.get("id", ""), "ok": False, "code": 1, "err": str(exc), "out": ""}


class Handler(BaseHTTPRequestHandler):
    server_version = "phonebench/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ------------------------------------------------------------ helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ------------------------------------------------------------ routes
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}

        if u.path in ("/", "/index.html"):
            html = (HERE / "ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if u.path == "/api/state":
            reg = registry()
            dev = core.scan(reg.get("tools"))
            self._json({
                "device": dev,
                "tools": core.tool_report(reg.get("tools")),
                "brands": {k: {"label": v["label"]} for k, v in core.BRANDS.items()},
                "intents": core.INTENTS,
                "resources": core.RESOURCES,
            })
            return

        if u.path == "/api/jobs":
            self._json({"jobs": jobs.list_jobs()})
            return

        if u.path == "/api/job":
            job = jobs.load(q.get("id", ""))
            self._json({"job": job} if job else {"error": "not found"}, 200 if job else 404)
            return

        if u.path == "/api/plan":
            reg = registry()
            dev = core.scan(reg.get("tools"))
            fw_id = q.get("firmware_id") or q.get("firmware") or None
            job_obj = jobs.load(q.get("job", "")) if q.get("job") else None
            job_model = job_obj.get("model") if job_obj else q.get("model")
            p = core.plan(q.get("brand", "generic"), q.get("intent", "diagnose"), {
                "tools": core.tool_report(reg.get("tools")),
                "state": dev["state"],
                "firmware_id": fw_id,
                "firmware": fw_id,
                "model": job_model,
            })
            if q.get("job"):
                p["gate"] = jobs.gate(q["job"], q.get("brand"), job_model, dev, firmware_id=fw_id)
            self._json(p)
            return

        if u.path == "/api/ledger":
            self._json({"ledger": jobs.ledger_read(400)})
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()

        if u.path == "/api/scan":
            reg = registry()
            self._json(core.scan(reg.get("tools")))
            return

        if u.path == "/api/bootstrap":
            self._json(core.bootstrap_platform_tools())
            return

        if u.path == "/api/intake":
            self._json(jobs.create(body))
            return

        if u.path == "/api/close":
            self._json(jobs.close(body.get("job", ""), body.get("status", "done")))
            return

        if u.path == "/api/run":
            job_id = body.get("job", "")
            brand = body.get("brand", "generic")
            intent = body.get("intent", "diagnose")
            firmware_id = body.get("firmware_id") or body.get("firmware") or None
            confirm = body.get("confirm", "")

            reg = registry()
            dev = core.scan(reg.get("tools"))
            job_obj = jobs.load(job_id) if job_id else None
            job_model = job_obj.get("model") if job_obj else body.get("model")

            g = jobs.gate(job_id, brand, job_model, dev, firmware_id=firmware_id)
            if not g["ok"]:
                self._json({"ok": False, "blocked": "gate", "reasons": g["reasons"]}, 403)
                return
            if confirm != "RUN":
                self._json({"ok": False, "blocked": "confirm",
                            "reasons": ["type RUN to execute"]}, 403)
                return

            p = core.plan(brand, intent, {
                "tools": core.tool_report(reg.get("tools")),
                "state": dev["state"],
                "firmware_id": firmware_id,
                "firmware": firmware_id,
                "model": job_model,
            })

            if p.get("blocked"):
                self._json({"ok": False, "blocked": "firmware",
                            "reasons": [p.get("block_reason") or "Firmware verification failed"]}, 403)
                return

            results = []
            cmds = plan_commands(p, reg)
            for step in cmds:
                if step["kind"] == "auto":
                    results.append(run_step(step))
                elif step["kind"] == "launch" and step.get("argv"):
                    path = step["tool_path"]
                    try:
                        subprocess.Popen(step["argv"], cwd=str(Path(path).parent))
                        results.append({"id": step["id"], "ok": True, "launched": path})
                    except OSError as exc:
                        results.append({"id": step["id"], "ok": False, "err": str(exc)})
                else:
                    results.append({"id": step["id"], "ok": not step.get("missing"),
                                    "guide": step.get("text", "")})

            jobs.record_operation(job_id, intent,
                                  f"{p['intent_label']} on {p['brand_label']}",
                                  [{"id": r["id"], "ok": r.get("ok")} for r in results])
            self._json({"ok": True, "plan": p, "results": results})
            return

        self._json({"error": "not found"}, 404)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    httpd = None
    last_err = None
    for candidate in range(port, port + 8):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            last_err = exc
    if httpd is None:
        print(f"could not bind a port in {port}..{port + 7}: {last_err}")
        return
    url = f"http://127.0.0.1:{port}/"
    print(f"phonebench running at {url}")
    print("Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
