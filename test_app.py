"""Native window state and asynchronous export checks."""

import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipUnless(tk is not None and (sys.platform == "win32" or os.environ.get("DISPLAY")), "Requires Tk and a display or Xvfb")
class NativeAppTests(unittest.TestCase):
    def setUp(self):
        import app
        self.module = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app.App(self.root)
        self.root.update()

    def tearDown(self):
        self.root.after_cancel(self.app.poll_job)
        self.root.destroy()

    def wait_for_work(self):
        deadline = time.monotonic() + 40
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.root.update()
        self.assertFalse(self.app.busy, "Background task did not finish")

    def test_source_change_discards_previous_result(self):
        self.app.result = {"archive": "/old/result.zip", "directory": "/old"}
        self.app.result_path.set("/old/result.zip")
        self.app.source.set("/different/package.zip")
        self.assertIsNone(self.app.result)
        self.assertNotEqual(self.app.result_path.get(), "/old/result.zip")
        self.assertIn("disabled", self.app.copy_button.state())

    def test_rescan_discards_previous_result(self):
        self.app.source.set(str(Path(tempfile.gettempdir()) / "missing-package.zip"))
        self.app.result = {"archive": "/old/result.zip", "directory": "/old"}
        self.app.result_path.set("/old/result.zip")
        with mock.patch.object(self.module.messagebox, "showerror") as error_dialog:
            self.app.start_scan()
            self.assertIsNone(self.app.result)
            self.assertEqual(self.app.result_path.get(), "")
            self.wait_for_work()
        error_dialog.assert_called_once()

    def test_window_fits_small_scaled_work_area(self):
        self.app.ui_scale = 1.5
        with mock.patch.object(self.module, "work_area", return_value=(0, 0, 1366, 728)):
            geometry = self.app.fit_geometry(1120, 860, 900, 720)
        width, height = map(int, geometry.split("+")[0].split("x"))
        self.assertEqual(width, 1366 - 24)
        self.assertEqual(height, 728 - 72)
        self.assertEqual(self.app.px(28), 42)

    def test_native_scan_adjust_export_and_catalog(self):
        from bank_volume import SAMPLES, export
        sources = list(SAMPLES.glob("*.zip"))
        if not sources:
            self.skipTest("No local sample package")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_dir = base / "input"
            source_dir.mkdir()
            with zipfile.ZipFile(sources[0]) as archive:
                for name in ("masterbank.bank", "masterbank.strings.bank", "aircraft_common.bank"):
                    (source_dir / name).write_bytes(archive.read(name))
            self.app.source.set(str(source_dir))
            with mock.patch.object(self.module.messagebox, "showerror") as error_dialog:
                self.app.start_scan()
                self.assertTrue(self.app.busy)
                self.wait_for_work()
                self.assertIsNotNone(self.app.scan)
                self.assertTrue(self.app.rows["aircraft_common"].available)
                self.assertFalse(self.app.rows["missile"].available)
                self.app.rows["aircraft_common"].value.set("50")
                self.app.rows["aircraft_common"].commit()
                self.app.rows["crew_ground"].value.set("80")
                self.app.rows["crew_ground"].commit()
                self.assertEqual(self.app.rows["aircraft_common"].value.get(), "50")
                self.app.show_catalog()
                self.root.update()
                for child in self.root.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        child.destroy()
                with mock.patch.object(self.module, "export", side_effect=lambda scan, gains, progress: export(scan, gains, base / "output", progress)):
                    self.app.start_export()
                    self.assertTrue(self.app.busy)
                    self.wait_for_work()
                error_dialog.assert_not_called()
                self.assertIsNotNone(self.app.result)
                self.assertTrue(Path(self.app.result["archive"]).is_file())
                self.assertEqual(self.app.result["changed_fields"], self.app.scan.counts["aircraft_common"] + 1)
                self.app.copy_path()
                self.assertEqual(self.root.clipboard_get(), self.app.result["archive"])
                self.app.reset()
                self.assertIsNone(self.app.result)
                self.assertTrue(all(row.value.get() == "100" for row in self.app.rows.values()))


if __name__ == "__main__":
    unittest.main()
