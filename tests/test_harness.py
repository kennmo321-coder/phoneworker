"""Test harness covering phonebench safety model, gate checks, fake devices, and risk floors."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phonebench import core, firmware, jobs, tui


class TestSafetyModelAndHarness(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_app_dir = core.APP_DIR
        self.original_jobs_dir = jobs.JOBS_DIR
        self.original_vault_dir = firmware.VAULT_DIR
        self.original_fake_root = os.environ.get("PHONEBENCH_FAKE_ROOT")
        self.original_test_mode = os.environ.get("PHONEBENCH_TEST_MODE")

        tmp_app = Path(self.tmp_dir) / "phonebench"
        core.APP_DIR = tmp_app
        jobs.JOBS_DIR = tmp_app / "jobs"
        firmware.VAULT_DIR = tmp_app / "firmware"

        tmp_app.mkdir(parents=True, exist_ok=True)
        jobs.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        firmware.VAULT_DIR.mkdir(parents=True, exist_ok=True)

        self.fakes_dir = Path(__file__).parent / "fakes"
        os.environ["PHONEBENCH_FAKE_ROOT"] = str(self.fakes_dir.resolve())
        os.environ["PHONEBENCH_TEST_MODE"] = "1"

    def tearDown(self):
        core.APP_DIR = self.original_app_dir
        jobs.JOBS_DIR = self.original_jobs_dir
        firmware.VAULT_DIR = self.original_vault_dir
        if self.original_fake_root:
            os.environ["PHONEBENCH_FAKE_ROOT"] = self.original_fake_root
        else:
            os.environ.pop("PHONEBENCH_FAKE_ROOT", None)

        if self.original_test_mode:
            os.environ["PHONEBENCH_TEST_MODE"] = self.original_test_mode
        else:
            os.environ.pop("PHONEBENCH_TEST_MODE", None)

        os.environ.pop("PHONEBENCH_FAKE_STATE_FILE", None)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_fake_state(self, state_dict: dict) -> Path:
        sf = Path(self.tmp_dir) / "fake_state.json"
        sf.write_text(json.dumps(state_dict), encoding="utf-8")
        os.environ["PHONEBENCH_FAKE_STATE_FILE"] = str(sf)
        return sf

    def test_attestation_refusal(self):
        # Missing attestation must fail job creation
        res1 = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": {"id_checked": False, "receipt_checked": True},
        })
        self.assertFalse(res1["ok"])
        self.assertIn("ownership not attested", res1["error"])

        res2 = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": {"id_checked": True, "receipt_checked": False},
        })
        self.assertFalse(res2["ok"])
        self.assertIn("ownership not attested", res2["error"])

    def test_gate_pass_and_fail_paths(self):
        # 1. Valid intake job
        job_res = jobs.create({
            "brand": "google",
            "model": "Pixel 6a",
            "serial": "fake_serial_123",
            "attestation": True,
        })
        self.assertTrue(job_res["ok"])
        job_id = job_res["job"]["job_id"]

        # Gate pass
        gate_ok = jobs.gate(job_id, brand="google", model="Pixel 6a")
        self.assertTrue(gate_ok["ok"])

        # Brand mismatch
        gate_brand_fail = jobs.gate(job_id, brand="xiaomi", model="Pixel 6a")
        self.assertFalse(gate_brand_fail["ok"])
        self.assertTrue(any("does not match request" in r for r in gate_brand_fail["reasons"]))

        # Model mismatch
        gate_model_fail = jobs.gate(job_id, brand="google", model="SM-G991B")
        self.assertFalse(gate_model_fail["ok"])
        self.assertTrue(any("does not match device" in r for r in gate_model_fail["reasons"]))

    def test_gate_refuses_job_without_attestation(self):
        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": True,
        })
        self.assertTrue(job_res["ok"])
        job_id = job_res["job"]["job_id"]
        job_file = jobs.JOBS_DIR / f"{job_id}.json"

        # 1. Modify attestation.id_checked = False directly on disk
        job_data = json.loads(job_file.read_text(encoding="utf-8"))
        job_data["attestation"]["id_checked"] = False
        job_file.write_text(json.dumps(job_data), encoding="utf-8")

        gate_id_fail = jobs.gate(job_id, brand="samsung", model="SM-G991B")
        self.assertFalse(gate_id_fail["ok"])
        self.assertTrue(any("ID not attested" in r for r in gate_id_fail["reasons"]))

        # 2. Modify attestation.receipt_checked = False directly on disk
        job_data["attestation"]["id_checked"] = True
        job_data["attestation"]["receipt_checked"] = False
        job_file.write_text(json.dumps(job_data), encoding="utf-8")

        gate_receipt_fail = jobs.gate(job_id, brand="samsung", model="SM-G991B")
        self.assertFalse(gate_receipt_fail["ok"])
        self.assertTrue(any("proof of purchase not attested" in r for r in gate_receipt_fail["reasons"]))

        # 3. Restore both flags
        job_data["attestation"]["receipt_checked"] = True
        job_file.write_text(json.dumps(job_data), encoding="utf-8")

        gate_pass = jobs.gate(job_id, brand="samsung", model="SM-G991B")
        self.assertTrue(gate_pass["ok"])

    def test_gate_refuses_firmware_after_tamper(self):
        fw_src = Path(self.tmp_dir) / "test_stock.bin"
        fw_src.write_bytes(b"VALID_FIRMWARE_PAYLOAD_DATA")

        reg_res = firmware.add_firmware(fw_src, copy=True, model_hint="SM-G991B")
        self.assertTrue(reg_res["ok"])
        pkg_id = reg_res["firmware"]["id"]
        copied_path = Path(reg_res["firmware"]["path"])

        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": True,
        })
        job_id = job_res["job"]["job_id"]

        # Flip byte on disk
        copied_path.write_bytes(b"TAMPERED_FIRMWARE_PAYLOAD_DATA")

        gate_res = jobs.gate(job_id, brand="samsung", model="SM-G991B", firmware_id=pkg_id)
        self.assertFalse(gate_res["ok"])
        self.assertTrue(any("firmware verification failed" in r for r in gate_res["reasons"]))

    def test_simulation_active_gating(self):
        # setUp sets both variables, so simulation starts active.
        self.assertTrue(core.simulation_active())

        # Without PHONEBENCH_TEST_MODE the fake root must be ignored by
        # discovery, not just by the helper - a stray environment variable
        # must never hand the bench a fake device.
        os.environ.pop("PHONEBENCH_TEST_MODE", None)
        self.assertFalse(core.simulation_active())
        self.assertNotIn("fakes", core.discover("adb") or "",
                         "fake adb resolved without PHONEBENCH_TEST_MODE=1")

        os.environ["PHONEBENCH_TEST_MODE"] = "1"
        self.assertTrue(core.simulation_active())
        self.assertIn("fakes", core.discover("adb") or "",
                      "fake adb not resolved while simulation is active")

    def test_fake_requires_explicit_state(self):
        # A fake with no state file must fail loudly instead of inventing a
        # connected device; this is what makes the fixtures trustworthy.
        empty = Path(self.tmp_dir) / "empty_fakes"
        empty.mkdir()
        env = dict(os.environ)
        env.pop("PHONEBENCH_FAKE_STATE_FILE", None)
        env["PHONEBENCH_FAKE_ROOT"] = str(empty)
        env["PHONEBENCH_TEST_MODE"] = "1"
        repo_root = Path(__file__).resolve().parent.parent
        for module in ("tests.fakes.adb_fake", "tests.fakes.fastboot_fake"):
            res = subprocess.run(
                [sys.executable, "-m", module, "devices"],
                capture_output=True, text=True, env=env, cwd=str(repo_root),
            )
            output = (res.stdout + res.stderr).lower()
            self.assertNotEqual(res.returncode, 0, f"{module} accepted a missing state file")
            self.assertIn("no state file", output, f"{module} failed for the wrong reason")

    def test_gate_attached_device_mismatch(self):
        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "serial": "samsung_serial_999",
            "attestation": True,
        })
        job_id = job_res["job"]["job_id"]

        # Attached device reports Pixel 6a
        attached_dev = {
            "state": "adb",
            "props": {
                "ro.product.model": "Pixel 6a",
                "ro.serialno": "fake_serial_123",
            },
        }

        gate_res = jobs.gate(job_id, brand="samsung", model="SM-G991B", device=attached_dev)
        self.assertFalse(gate_res["ok"])
        self.assertTrue(any("attached device reports" in r for r in gate_res["reasons"]))

    def test_intent_risk_floors(self):
        # Flash intent must carry 'destructive' risk floor even when no tools are found
        plan_flash = core.plan("samsung", "flash", {"tools": {}})
        self.assertEqual(plan_flash["risk"], "destructive")

        # Diagnose intent carries 'safe' risk
        plan_diag = core.plan("google", "diagnose", {"tools": {}})
        self.assertEqual(plan_diag["risk"], "safe")

        # Wipe intent carries 'destructive' risk floor
        plan_wipe = core.plan("xiaomi", "wipe", {"tools": {}})
        self.assertEqual(plan_wipe["risk"], "destructive")

    def test_ledger_append(self):
        job_res = jobs.create({
            "brand": "google",
            "model": "Pixel 6a",
            "attestation": True,
        })
        job_id = job_res["job"]["job_id"]

        jobs.record_operation(job_id, "diagnose", "Ran read-only diagnosis")
        jobs.close(job_id, "done")

        entries = jobs.ledger_read()
        kinds = [e.get("kind") for e in entries]
        self.assertIn("intake", kinds)
        self.assertIn("operation", kinds)
        self.assertIn("close", kinds)

    def test_modal_confirmation_in_tui(self):
        app = tui.App()
        app.plan = {"intent": "diagnose", "intent_label": "Diagnose", "brand_label": "Google", "steps": []}
        app.job = {"job_id": "fake-job-id"}

        # Trigger modal
        app.modal = "run"
        app.modal_buf = "RUN"

        # Submit RUN
        ret = app.handle("enter")
        self.assertTrue(ret)
        self.assertIsNone(app.modal)

        # Trigger modal and submit incorrect confirmation
        app.modal = "run"
        app.modal_buf = "NO"
        app.handle("enter")
        self.assertEqual(app.msg, "cancelled")

    def test_fake_device_scanning_states(self):
        # State 1: ADB
        self._write_fake_state({
            "state": "adb",
            "serial": "adb_123",
            "props": {"ro.product.model": "Pixel 6a", "ro.product.manufacturer": "Google"},
        })

        scan_adb = core.scan()
        self.assertEqual(scan_adb["state"], "adb")
        self.assertEqual(scan_adb["props"]["ro.product.model"], "Pixel 6a")

        # State 2: Fastboot
        self._write_fake_state({
            "state": "fastboot",
            "serial": "fake_fb_serial_456",
        })
        scan_fb = core.scan()
        self.assertEqual(scan_fb["state"], "fastboot")
        self.assertEqual(scan_fb["fastboot"], ["fake_fb_serial_456"])

        # State 3: Unauthorized
        self._write_fake_state({
            "state": "unauthorized",
            "serial": "adb_unauth_789",
        })
        scan_unauth = core.scan()
        self.assertEqual(scan_unauth["state"], "adb")
        self.assertEqual(scan_unauth["adb"][0]["state"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
