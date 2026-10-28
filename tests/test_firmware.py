"""Unit tests for phonebench.firmware."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from phonebench import core, firmware


class TestFirmwareVault(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_vault_dir = firmware.VAULT_DIR
        firmware.VAULT_DIR = Path(self.tmp_dir) / "firmware"
        firmware.VAULT_DIR.mkdir(parents=True, exist_ok=True)

        self.fixtures_dir = Path(__file__).parent / "fixtures"

        # Dynamically generate synthetic fixtures in temp directory (avoiding binary files in git)
        self.zip_fixture = Path(self.tmp_dir) / "pixel_factory.zip"
        with zipfile.ZipFile(self.zip_fixture, "w") as z:
            z.writestr("android-info.txt", "model=Pixel 6a\nrequire board=bluejay\n")

        self.sam_fixture = Path(self.tmp_dir) / "AP_G991BXXU5EWA3_REV00.tar.md5"
        self.sam_fixture.write_bytes(b"FAKE_SAMSUNG_AP_BINARY_DATA")

        self.scatter_fixture = self.fixtures_dir / "MT6768_Android_scatter.txt"

    def tearDown(self):
        firmware.VAULT_DIR = self.original_vault_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_model_hint_parsing(self):
        hint_zip = firmware.parse_model_hint(self.zip_fixture)
        self.assertEqual(hint_zip, "Pixel 6a")

        hint_sam = firmware.parse_model_hint(self.sam_fixture)
        self.assertEqual(hint_sam, "G991BXXU5EWA3")

        hint_scatter = firmware.parse_model_hint(self.scatter_fixture)
        self.assertEqual(hint_scatter, "MT6768")

    def test_registration_copy(self):
        res = firmware.add_firmware(self.zip_fixture, copy=True)
        self.assertTrue(res["ok"], res.get("error"))

        fw = res["firmware"]
        self.assertEqual(fw["model_hint"], "Pixel 6a")
        self.assertTrue(fw["copied"])
        self.assertTrue(Path(fw["path"]).exists())
        self.assertIn(fw["id"], fw["path"])

    def test_registration_no_copy(self):
        res = firmware.add_firmware(self.sam_fixture, copy=False, model_hint="SM-G991B")
        self.assertTrue(res["ok"], res.get("error"))

        fw = res["firmware"]
        self.assertEqual(fw["model_hint"], "SM-G991B")
        self.assertFalse(fw["copied"])
        self.assertEqual(fw["path"], str(self.sam_fixture.resolve()))

    def test_fast_and_full_verification(self):
        res = firmware.add_firmware(self.zip_fixture, copy=True)
        pkg_id = res["firmware"]["id"]

        # Fast path
        ver_fast = firmware.verify_firmware(pkg_id, full=False)
        self.assertTrue(ver_fast["ok"])
        self.assertTrue(ver_fast["verified"])
        self.assertTrue(ver_fast["fast"])

        # Full path
        ver_full = firmware.verify_firmware(pkg_id, full=True)
        self.assertTrue(ver_full["ok"])
        self.assertTrue(ver_full["verified"])
        self.assertFalse(ver_full["fast"])

    def test_tamper_detection(self):
        test_file = Path(self.tmp_dir) / "dummy.bin"
        test_file.write_bytes(b"ORIGINAL_FIRMWARE_CONTENT")

        res = firmware.add_firmware(test_file, copy=True)
        pkg_id = res["firmware"]["id"]
        copied_path = Path(res["firmware"]["path"])

        # Tamper with copied file
        copied_path.write_bytes(b"TAMPERED_FIRMWARE_CONTENT")

        # Full verify checks hash
        ver = firmware.verify_firmware(pkg_id, full=True)
        self.assertFalse(ver["ok"])
        self.assertTrue(ver.get("tampered"))
        self.assertIn("Hash mismatch", ver.get("error", ""))

    def test_multi_chunk_streaming_sha256(self):
        large_file = Path(self.tmp_dir) / "large_fw.bin"
        chunk = b"A" * (1024 * 1024)
        with open(large_file, "wb") as f:
            for _ in range(9):
                f.write(chunk)

        expected_hash = hashlib.sha256(b"A" * (9 * 1024 * 1024)).hexdigest()
        computed = firmware.compute_sha256(large_file)
        self.assertEqual(computed, expected_hash)

        res = firmware.add_firmware(large_file, copy=True, model_hint="LARGE_MODEL")
        self.assertTrue(res["ok"])
        self.assertEqual(res["firmware"]["sha256"], expected_hash)

    def test_get_and_ambiguous_prefix(self):
        r1 = firmware.add_firmware(self.zip_fixture, copy=True)
        r2 = firmware.add_firmware(self.sam_fixture, copy=True)

        id1 = r1["firmware"]["id"]
        id2 = r2["firmware"]["id"]

        # Exact / prefix lookup
        get1 = firmware.get_firmware(id1[:6])
        self.assertTrue(get1["ok"])
        self.assertEqual(get1["firmware"]["id"], id1)

        # Unknown ID
        get_unk = firmware.get_firmware("nonexistentid")
        self.assertFalse(get_unk["ok"])
        self.assertIn("not found", get_unk["error"])

    def test_remove_firmware(self):
        res = firmware.add_firmware(self.zip_fixture, copy=True)
        pkg_id = res["firmware"]["id"]

        rm_res = firmware.remove_firmware(pkg_id)
        self.assertTrue(rm_res["ok"])
        self.assertEqual(rm_res["id"], pkg_id)

        get_res = firmware.get_firmware(pkg_id)
        self.assertFalse(get_res["ok"])


if __name__ == "__main__":
    unittest.main()
