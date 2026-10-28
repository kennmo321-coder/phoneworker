"""CLI unit tests for phonebench firmware subcommands and tamper blocking."""
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from phonebench import __main__ as main_module
from phonebench import core, firmware, jobs


class TestCLI(unittest.TestCase):
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

    def tearDown(self):
        firmware.VAULT_DIR = self.original_vault_dir
        core.APP_DIR = self.original_app_dir
        jobs.JOBS_DIR = self.original_jobs_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_cli_firmware_add_list_verify_rm_happy_path(self):
        src = self.fixtures_dir / "pixel_factory.zip"

        # 1. firmware add
        code = main_module.main(["firmware", "add", str(src), "--model", "Pixel 6a"])
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

    def test_plan_and_gate_tampered_firmware_blocks_run(self):
        src = Path(self.tmp_dir) / "test_fw.zip"
        src.write_bytes(b"ORIGINAL_DATA")

        res = firmware.add_firmware(src, copy=True, model_hint="SM-G991B")
        pkg_id = res["firmware"]["id"]
        copied_path = Path(res["firmware"]["path"])

        # Create intake job
        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": {"id_checked": True, "receipt_checked": True},
        })
        self.assertTrue(job_res["ok"])
        job_id = job_res["job"]["job_id"]

        # Tamper with copied firmware file (change size so fast check fails and sha256 is checked)
        copied_path.write_bytes(b"TAMPERED_DATA_MODIFIED_PAYLOAD")

        # Plan with tampered firmware_id
        plan_res = core.plan("samsung", "flash", {
            "firmware_id": pkg_id,
            "tools": {},
        })

        # Step "fw-tampered" must be present with destructive risk
        tampered_steps = [s for s in plan_res["steps"] if s["id"] == "fw-tampered"]
        self.assertEqual(len(tampered_steps), 1)
        self.assertEqual(tampered_steps[0]["risk"], "destructive")

        # Gate verification with tampered firmware_id must fail
        gate_res = jobs.gate(job_id, brand="samsung", model="SM-G991B", firmware_id=pkg_id)
        self.assertFalse(gate_res["ok"])
        self.assertTrue(any("firmware verification failed" in r for r in gate_res["reasons"]))


if __name__ == "__main__":
    unittest.main()
