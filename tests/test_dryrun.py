"""Unit tests for phonebench dry-run mode."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from phonebench import __main__ as main_module
from phonebench import core, firmware, jobs, server, tui


class TestDryRunMode(unittest.TestCase):
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

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_plan_commands_argv_matches_run_step_argv(self):
        adb_path = core.discover("adb")
        self.assertIsNotNone(adb_path)

        plan = core.plan("google", "flash", {
            "tools": {"adb": {"path": adb_path, "found": True}},
        })

        cmds = server.plan_commands(plan)
        auto_cmds = [c for c in cmds if c["kind"] == "auto"]
        self.assertGreater(len(auto_cmds), 0)

        auto_step = auto_cmds[0]
        step_argv = auto_step["argv"]

        # Get raw plan step
        raw_step = [s for s in plan["steps"] if s["id"] == auto_step["id"]][0]
        raw_cmd = list(raw_step["cmd"])
        raw_cmd[0] = core.discover(raw_cmd[0])

        # Assert plan_commands argv matches resolved raw plan step
        self.assertEqual(step_argv, raw_cmd)

        # Run step with mock subprocess.run to capture executed argv
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "ok"
            mock_run.return_value.stderr = ""

            server.run_step(raw_step)

            mock_run.assert_called_once()
            called_argv = mock_run.call_args[0][0]
            self.assertEqual(step_argv, called_argv)

    def test_dry_run_with_tampered_vault_package_reports_hash_failure(self):
        fw_src = Path(self.tmp_dir) / "test_stock.bin"
        fw_src.write_bytes(b"VALID_FIRMWARE_PAYLOAD_DATA")

        reg_res = firmware.add_firmware(fw_src, copy=True, model_hint="SM-G991B")
        self.assertTrue(reg_res["ok"])
        pkg_id = reg_res["firmware"]["id"]
        copied_path = Path(reg_res["firmware"]["path"])

        # Tamper package binary on disk
        copied_path.write_bytes(b"TAMPERED_PAYLOAD_DATA")

        err_buf = io.StringIO()
        out_buf = io.StringIO()
        with patch("sys.stderr", err_buf), patch("sys.stdout", out_buf):
            code = main_module.handle_dry_run("samsung", "flash", firmware_id=pkg_id)

        self.assertEqual(code, 0)
        self.assertIn("BLOCKED", err_buf.getvalue())
        self.assertIn("executed: 0", out_buf.getvalue())

    def test_dry_run_does_not_append_ledger_or_call_subprocess(self):
        job_res = jobs.create({
            "brand": "google",
            "model": "Pixel 6a",
            "attestation": True,
        })
        self.assertTrue(job_res["ok"])
        initial_ledger_count = len(jobs.ledger_read())

        app = tui.App()
        app.job = job_res["job"]
        app.dry_run = True
        app.plan = core.plan("google", "diagnose", {
            "tools": {"adb": {"path": str(self.fakes_dir / "adb"), "found": True}},
        })

        with patch("subprocess.run") as mock_sub, patch("subprocess.Popen") as mock_popen, patch("phonebench.server.run_step") as mock_rs:
            app.execute()

            mock_sub.assert_not_called()
            mock_popen.assert_not_called()
            mock_rs.assert_not_called()

        self.assertEqual(app.msg, "dry run - nothing executed")
        self.assertEqual(len(jobs.ledger_read()), initial_ledger_count)

    def test_guide_only_step_renders_text_not_empty_argv(self):
        plan = core.plan("generic", "diagnose", {"tools": {}})
        cmds = server.plan_commands(plan)

        guide_cmds = [c for c in cmds if c["kind"] == "guide"]
        self.assertGreater(len(guide_cmds), 0)

        for gc in guide_cmds:
            self.assertNotIn("argv", gc)
            self.assertIn("text", gc)
            self.assertTrue(bool(gc["text"]))

    def test_launch_step_with_missing_tool_is_flagged_not_ok(self):
        # A plan can name a launch step for a tool that is not installed. That
        # must surface as a failure, not as a guide step that counts as success.
        plan = {
            "brand": "samsung",
            "intent": "flash",
            "brand_label": "Samsung",
            "intent_label": "Flash stock firmware",
            "risk": "destructive",
            "blocked": False,
            "steps": [{
                "id": "launch-odin",
                "title": "Odin",
                "kind": "launch",
                "tool": "__definitely_not_installed__",
                "risk": "caution",
                "detail": "",
            }],
        }
        cmds = server.plan_commands(plan, {"tools": {}})
        self.assertEqual(len(cmds), 1)
        self.assertTrue(cmds[0].get("missing"))
        self.assertIn("not installed", cmds[0]["text"])

        job_res = jobs.create({
            "brand": "samsung",
            "model": "SM-G991B",
            "attestation": True,
        })
        self.assertTrue(job_res["ok"])

        app = tui.App()
        app.job = job_res["job"]
        app.plan = plan
        with patch("phonebench.jobs.record_operation") as rec, \
                patch("subprocess.run") as sub, patch("subprocess.Popen") as popen:
            app.execute()
            sub.assert_not_called()
            popen.assert_not_called()
        results = rec.call_args[0][3]
        self.assertFalse(results[0]["ok"], "missing tool recorded as success")
        self.assertIn("executed 0/1", app.msg)

    def test_cli_dry_run_flag_wires_up(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = main_module.main(["--dry-run", "--brand", "google", "--intent", "diagnose"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("executed: 0", text)
        self.assertIn("DRY RUN PLAN", text)


if __name__ == "__main__":
    unittest.main()
