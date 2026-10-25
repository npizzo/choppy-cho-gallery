import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import export_campaign as exporter
import check_gallery as checker


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        self.campaign, self.gallery = root / "campaign", root / "gallery"
        self.campaign.mkdir()
        self.original_plot = exporter.plot_asset
        self.plot_patch = patch.object(exporter, "plot_asset", return_value=None)
        self.plot_patch.start()
        self.addCleanup(self.plot_patch.stop)

    def write(self, name, content):
        path = self.campaign / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def export(self):
        result = exporter.export_campaign(self.campaign, self.gallery)
        checker.check_gallery(self.gallery)
        return result

    def completed_fixture(self, case="pilot"):
        base = "data/" + case + "/"
        self.write(base + "metadata.toml", 'complete = true\nnmodes = 2\ninput = "/work/private/raw.bin"\n')
        self.write(base + "status.toml", "time = 10.0\nmax_divergence = 1e-15\nmean_cfl = 0.02\n")
        self.write(base + "surface/mean_square_slope.csv", "time_s,parent_mss,cho_mss,total_mss,cross_contribution\n0,0.1,0,0.1,0\n10,0.1,0.03,0.12,-0.01\n")
        self.write(base + "parent.csv", "t,ReA_1,ReA_2,ImA_1,ImA_2,ReIntrinsicAt_1\n0,2,0,0,0,0\n10,2,1,0,0,0\n")
        self.write(base + "checks.json", json.dumps({"maximum_disturbance_m": .0002, "source": "/Users/private/foo"}))
        for name in ("surface_startup", "underwater"):
            video = self.write(base + name + ".mp4", "")
            video.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(32))
            self.write(base + name + ".json", json.dumps({"source": "/home/private/foo", "physical_interval_s": [0, 1], "physical_playback_speed": .04} if name.startswith("surface") else {"time_seconds": [0, 1, 10]}))
        self.write(base + "surface/cho.npz", "private raw data should not appear")
        self.write(base + "checkpoint.jls", "private checkpoint should not appear")

    def test_missing_outputs_are_unknown_not_failed(self):
        result = self.export()
        self.assertEqual(result["status"], "awaiting_sync")
        self.assertEqual(result["validation"]["state"], "not_synchronized")
        self.assertEqual([case["id"] for case in result["cases"]], ["pilot", "prescribed"])
        self.assertTrue(all(case["observed_time_s"] is None for case in result["cases"]))

    def test_tank_completion_does_not_claim_pipeline_completion(self):
        self.write("data/pilot/metadata.toml", "complete = true\n")
        result = self.export()
        self.assertEqual(result["cases"][0]["status"], "partial")
        self.assertTrue(result["cases"][0]["tank_complete"])
        self.assertEqual(result["cases"][0]["videos"], [])

    def test_real_diagnostics_and_safe_allowlist(self):
        self.completed_fixture()
        result = self.export()
        case = result["cases"][0]
        self.assertEqual(case["status"], "outputs_available")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(case["metrics"]["final_cross_slope_term"], -.01)
        self.assertAlmostEqual(case["metrics"]["parent_sideband_elevation_variance_fraction_final"], .2)
        self.assertEqual(case["metrics"]["final_total_mss"], .12)
        self.assertNotIn("physical_playback_speed", case["videos"][1])
        self.assertEqual(case["videos"][1]["physical_interval_s"], [0, 10])
        self.assertNotIn("/home/", json.dumps(result))
        self.assertNotIn("/Users/", json.dumps(result))
        self.assertFalse(list(self.gallery.rglob("*.npz")))
        self.assertFalse(list(self.gallery.rglob("*.jls")))

    def test_invalid_mss_is_omitted_without_overclaiming(self):
        self.completed_fixture()
        self.write("data/pilot/surface/mean_square_slope.csv", "time_s,parent_mss,cho_mss,total_mss,cross_contribution\n0,0.1,-0.1,0.2,0\n")
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "partial")
        self.assertNotIn("final_parent_mss", case["metrics"])
        self.assertTrue(any("consistency" in notice for notice in case["notices"]))

    def test_truncated_tables_and_unfinished_movies_are_omitted(self):
        self.completed_fixture()
        self.write("data/pilot/parent.csv", "t,ReA_1,ImA_1\n0,1,0\n1,0.9\n")
        (self.campaign / "data/pilot/underwater.json").unlink()
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "partial")
        self.assertEqual(len(case["videos"]), 1)
        self.assertNotIn("parent_sideband_elevation_variance_fraction_final", case["metrics"])

    def test_old_completion_record_does_not_certify_rerender(self):
        self.completed_fixture()
        record = self.campaign / "data/pilot/surface_startup.json"
        video = self.campaign / "data/pilot/surface_startup.mp4"
        os.utime(record, ns=(video.stat().st_mtime_ns - 1000000,) * 2)
        case = self.export()["cases"][0]
        self.assertNotIn("surface_startup", [item["id"] for item in case["videos"]])
        self.assertTrue(any("still be rendering" in message for message in case["notices"]))

    def test_unchanged_input_reuses_assets_and_never_writes_campaign(self):
        self.completed_fixture()
        before = {p.relative_to(self.campaign): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.campaign.rglob("*") if p.is_file()}
        first = self.export()
        assets = sorted(str(p) for p in self.gallery.rglob("*") if p.is_file())
        second = self.export()
        self.assertEqual(first["cases"], second["cases"])
        self.assertEqual(assets, sorted(str(p) for p in self.gallery.rglob("*") if p.is_file()))
        after = {p.relative_to(self.campaign): (p.stat().st_mtime_ns, p.read_bytes()) for p in self.campaign.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_reject_symlinked_input_and_unsafe_destination(self):
        external = Path(self.temporary.name) / "outside.csv"
        external.write_text("time_s,parent_mss,cho_mss,total_mss,cross_contribution\n0,1,0,1,0\n")
        directory = self.campaign / "data/pilot/surface"
        directory.mkdir(parents=True)
        (directory / "mean_square_slope.csv").symlink_to(external)
        case = self.export()["cases"][0]
        self.assertEqual(case["downloads"], [])
        with self.assertRaises(ValueError):
            exporter.export_campaign(self.campaign, self.campaign / "public")

    def test_destination_symlink_ancestors_are_rejected_before_writing(self):
        root = self.campaign.parent
        outside = root / "outside"
        outside.mkdir()
        alias = root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            exporter.export_campaign(self.campaign, alias / "new-gallery")
        self.assertFalse((outside / "new-gallery").exists())
        with self.assertRaises(ValueError):
            exporter.export_campaign(self.campaign, alias)
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_asset_also_rejects_symlinked_parent(self):
        root = self.campaign.parent
        outside = root / "outside"
        outside.mkdir()
        media = self.gallery / "media"
        media.mkdir(parents=True)
        (media / "pilot").symlink_to(outside, target_is_directory=True)
        payload = b"time_s,mss\n0,1\n"
        digest = hashlib.sha256(payload).hexdigest()[:16]
        target = outside / ("diagnostic-" + digest + ".csv")
        target.write_bytes(payload)
        with self.assertRaises(ValueError):
            exporter.install_bytes(self.gallery, "pilot", "diagnostic.csv", payload)
        with self.assertRaises(ValueError):
            exporter.install_bytes(self.gallery, "pilot", "new.csv", b"new payload")
        self.assertEqual(list(outside.iterdir()), [target])
        self.assertEqual(target.read_bytes(), payload)

    def test_status_uses_tank_time_key(self):
        self.write("data/pilot/status.toml", "time = 3.25\niteration = 6500\n")
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "partial")
        self.assertEqual(case["observed_time_s"], 3.25)

    def mean_fixture(self, rows=None):
        return self.write("data/pilot/mean_history.csv", ",".join(exporter.MEAN_COLUMNS)+"\n"+
            (rows if rows is not None else "0,16,-0.02,-0.03,0.001,0.004,0.002,0,0,0\n1,17,-0.01,-0.02,0.002,0.008,0.003,0.02,0.001,0.002\n"))

    def test_mean_history_allows_signed_means_and_exports_only_allowed_columns(self):
        self.mean_fixture()
        rows = exporter.read_mean_history(self.campaign, "data/pilot/mean_history.csv")
        self.assertEqual(rows[0]["surface_UL_mean_m_s"], -.02)
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "partial")
        self.assertEqual(case["metrics"], {})
        self.assertEqual(len(case["downloads"]), 1)
        public = (self.gallery/case["downloads"][0]["src"]).read_text()
        self.assertEqual(public.splitlines()[0], ",".join(exporter.MEAN_COLUMNS))
        self.assertIn("-0.02", public)

    def test_invalid_mean_rms_action_fraction_or_time_origin_is_omitted(self):
        for row in ("0,16,0.16,0.15,-0.001,0.004,0.002,0,0,0\n",
                    "0,16,0.16,0.15,0.001,0.004,0.002,1.1,0,0\n",
                    "0,16,0.16,0.15,0.001,0.004,0.002,0,0,0\n1,18,0.16,0.15,0.001,0.004,0.002,0,0,0\n"):
            with self.subTest(row=row):
                self.mean_fixture(row)
                case = self.export()["cases"][0]
                self.assertEqual(case["downloads"], [])
                self.assertTrue(any("consistency" in notice for notice in case["notices"]))

    def test_truncated_or_extended_mean_table_is_omitted(self):
        path = self.mean_fixture()
        text = path.read_text()
        for damaged in (text+"2,18,0.16\n", text.replace("physical_age_s,", "unapproved_column,physical_age_s,")):
            with self.subTest(damaged=damaged):
                path.write_text(damaged)
                case = self.export()["cases"][0]
                self.assertEqual(case["downloads"], [])

    def test_pipeline_running_alone_is_partial_without_claiming_completion(self):
        self.write("data/pilot/pipeline_status.json", json.dumps({"current_stage":"tank","state":"running",
            "stages":{"tank":{"detail":"/work/private/raw.bin"}}}))
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "partial")
        self.assertFalse(case["tank_complete"])
        self.assertIsNone(case["observed_time_s"])
        self.assertEqual(case["metrics"], {})
        self.assertTrue(any("parent/current integration — running" in notice for notice in case["notices"]))
        self.assertNotIn("/work/", json.dumps(case))

    def test_failed_stage_keeps_completed_outputs_and_does_not_claim_live_status(self):
        self.completed_fixture()
        self.write("data/pilot/pipeline_status.json", json.dumps({"current_stage":"render","state":"failed"}))
        case = self.export()["cases"][0]
        self.assertEqual(case["status"], "outputs_available")
        self.assertEqual(len(case["videos"]), 2)
        self.assertTrue(any("rendering — failed" in notice and "not a live" in notice for notice in case["notices"]))

    def test_current_plot_has_two_panels_cm_s_and_physical_wind_age(self):
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            self.skipTest("Matplotlib unavailable")
        self.mean_fixture()
        rows = exporter.read_mean_history(self.campaign, "data/pilot/mean_history.csv")
        observed = {}
        close = plt.close
        def inspect(figure):
            if hasattr(figure, "axes"):
                observed["axes"] = [(ax.get_xlabel(), ax.get_ylabel(),
                    [(list(line.get_xdata()),list(line.get_ydata())) for line in ax.lines]) for ax in figure.axes]
            close(figure)
        with patch.object(plt, "close", side_effect=inspect):
            image = self.original_plot(self.gallery,"pilot","mean_current",rows)
        self.assertTrue((self.gallery/image).read_bytes().startswith(b"\x89PNG"))
        top, bottom = observed["axes"]
        self.assertEqual(top[1], "Mean current (cm/s)")
        self.assertEqual(top[2][0], ([16.,17.],[-2.,-1.]))
        self.assertEqual(bottom[0], "Physical wind age (s)")
        self.assertEqual(bottom[2][0], ([16.,17.],[.2,.3]))

    def test_checker_rejects_unsafe_references_private_data_and_false_claims(self):
        result = self.export()
        with self.assertRaises(ValueError):
            checker.asset(self.gallery, "../secret.csv", {".csv"})
        with self.assertRaises(ValueError):
            checker.asset(self.gallery, "%2e%2e/secret.csv", {".csv"})
        result["cases"][0]["status"] = "outputs_available"
        with self.assertRaises(ValueError):
            checker.check_manifest(result, self.gallery)
        (self.gallery / "secret.txt").write_text("/Users/private/credentials")
        with self.assertRaises(ValueError):
            checker.check_gallery(self.gallery)
        (self.gallery / "secret.txt").unlink()
        (self.gallery / "raw.bin").write_bytes(b"raw")
        with self.assertRaises(ValueError):
            checker.check_gallery(self.gallery)

    def test_validation_record_is_not_fingerprint_revalidation(self):
        self.write("validation/passed.json", json.dumps({"status": "passed", "fingerprint": "not-current", "source": "/work/private"}))
        result = self.export()
        self.assertEqual(result["validation"]["state"], "record_available")
        self.assertIn("does not revalidate", result["validation"]["description"])


if __name__ == "__main__":
    unittest.main()
