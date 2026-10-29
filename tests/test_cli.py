"""CLI and end-to-end integration unit tests for phonebench."""
import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from phonebench import __main__ as main_module
from phonebench import core, firmware, jobs, server, tui


class TestCLIAndEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_vault_dir = firmware.VAULT_DIR
        self.original_app_dir = core.APP_DIR
        self.original_jobs_dir = jobs.JOBS_DIR

        tmp_app = Path(self.tmp_dir) / "phonebench"
        core.APP_DIR = tmp_app
        firmware.VAULT_DIR = tmp_app / "firmware"
        jobs.JOBS_DIR = tmp_app / "jobs"
        firmware.VAULT_DIR.mkdir(parents=True, exist_ok=True)
        jobs.JOBS_DIR.mkdir(parents=True, exist_ok=True)

        self.fixtures_dir = Path(__file__).parent / "fixtures"

        # Synthetic test zip archive created dynamically in temp dir
        self.zip_fixture = Path(self.tmp_dir) / "pixel_factory.zip"
        with zipfile.ZipFile(self.zip_fixture, "w") as z:
            z.writestr("android-info.txt", "model=Pixel 6a\nrequire board=bluejay\n")

    def tearDown(self):
        firmware.VAULT_DIR = self.original_vault_dir
        core.APP_DIR = self.original_app_dir
        jobs.JOBS_DIR = self.original_jobs_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cli_firmware_add_list_verify_rm_happy_path(self):
        # 1. firmware add
        code = main_module.main(["firmware", "add", str(self.zip_fixture), "--model", "Pixel 6a"])
        self.assertEqual(code, 0)

        # 2. firmware list
        buf = io.StringIO()
        sys.stdout = buf
        try:
            code = main_module.main(["firmware", "list"])
        finally:
            sys.stdout = sys.__stdout__

        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("Pixel 6a", output)

        # Get package id from list
        pkgs = firmware.list_firmware()["packages"]
        self.assertEqual(len(pkgs), 1)
        pkg_id = pkgs[0]["id"]

        # 3. firmware verify
        code = main_module.main(["firmware", "verify", pkg_id, "--full"])
        self.assertEqual(code, 0)

        # 4. firmware rm
        code = main_module.main(["firmware", "rm", pkg_id])
        self.assertEqual(code, 0)

        # Verify list is empty
        pkgs_after = firmware.list_firmware()["packages"]
        self.assertEqual(len(pkgs_after), 0)

    def test_cli_firmware_unknown_id(self):
        code = main_module.main(["firmware", "verify", "unknown123"])
        self.assertNotEqual(code, 0)

        code_rm = main_module.main(["firmware", "rm", "unknown123"])
        self.assertNotEqual(code_rm, 0)

    def test_cli_firmware_missing_file(self):
        code = main_module.main(["firmware", "add", "/path/to/nonexistent/file.zip"])
        self.assertNotEqual(code, 0)

    def test_end_to_end_tampered_firmware_blocks_gate_and_execution(self):
        # Register a valid firmware package
        fw_src = Path(self.tmp_dir) / "stock_firmware.bin"
        fw_src.write_bytes(b"VALID_STOCK_FIRMWARE_BINARY_CONTENT")

        reg_res = firmware.add_firmware(fw_src, copy=True, model_hint="SM-G991B")
        self.assertTrue(reg_res["ok"])
        pkg_id = reg_res["firmware"]["id"]
        copied_path = Path(reg_res["firmware"]["path"])

        # Create intake job record
        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": True,
        })
        self.assertTrue(job_res["ok"])
        job_id = job_res["job"]["job_id"]

        # TAMPER with the registered package binary
        copied_path.write_bytes(b"MODIFIED_TAMPERED_FIRMWARE_PAYLOAD")

        # 1. Call gate as the UI / server calls it
        gate_res = jobs.gate(job_id, brand="samsung", model="SM-G991B", firmware_id=pkg_id)
        self.assertFalse(gate_res["ok"])
        self.assertTrue(any("firmware verification failed" in r for r in gate_res["reasons"]))

        # 2. Build plan via core.plan()
        plan_res = core.plan("samsung", "flash", {
            "firmware_id": pkg_id,
            "model": "SM-G991B",
            "tools": {"adb": {"path": "/fake/adb"}},
        })
        self.assertTrue(plan_res.get("blocked"))
        self.assertIsNotNone(plan_res.get("block_reason"))

        # Monkeypatch server.run_step to record executed steps
        executed_calls = []
        def mock_run_step(step, timeout=180):
            executed_calls.append(step)
            return {"id": step["id"], "ok": True}

        original_run_step = server.run_step
        server.run_step = mock_run_step
        try:
            # 3. Test TAMPERED case with App.execute()
            app = tui.App()
            app.job = job_res["job"]
            app.plan = plan_res
            app.selected_firmware_id = pkg_id

            app.execute()

            self.assertEqual(len(executed_calls), 0)
            self.assertTrue(app.msg.startswith("blocked"), f"Expected msg starting with 'blocked', got: {app.msg}")

            # 4. Test POSITIVE UNTAMPERED case with App.execute()
            valid_src = Path(self.tmp_dir) / "valid_stock_fw.bin"
            valid_src.write_bytes(b"UNTAMPERED_STOCK_FIRMWARE_DATA")
            reg_valid = firmware.add_firmware(valid_src, copy=True, model_hint="SM-G991B")
            self.assertTrue(reg_valid["ok"])
            valid_pkg_id = reg_valid["firmware"]["id"]

            plan_valid = core.plan("google", "flash", {
                "firmware_id": valid_pkg_id,
                "model": "Pixel 6a",
                "tools": {
                    "adb": {"path": "/fake/adb", "found": True},
                    "fastboot": {"path": "/fake/fastboot", "found": True},
                },
            })
            self.assertFalse(plan_valid.get("blocked"))

            app_valid = tui.App()
            app_valid.job = job_res["job"]
            app_valid.plan = plan_valid
            app_valid.selected_firmware_id = valid_pkg_id

            app_valid.execute()

            self.assertGreater(len(executed_calls), 0)
            self.assertTrue(app_valid.msg.startswith("executed"), f"Expected msg starting with 'executed', got: {app_valid.msg}")
        finally:
            server.run_step = original_run_step


if __name__ == "__main__":
    unittest.main()
