"""Sidecar scheduler and publishing tests; no network, Slurm or real git mutations."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_update as publisher
spec = importlib.util.spec_from_file_location("enable_updates", ROOT / "unity/enable-updates.py")
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


class FakeRunner:
    def __init__(self, states="", queue=""):
        self.calls = []
        self.states = states
        self.queue = queue
        self.next_job = 9000
        self.diff = 1
        self.push_failures = 0
        self.bad_submit = False
        self.fail_check = False

    def __call__(self, argv, cwd, *, env=None, check=True):
        argv = list(argv)
        self.calls.append((argv, Path(cwd), env, check))
        stdout, code = "", 0
        if argv[0] == "sacct":
            stdout = self.states
        elif argv[0] == "squeue":
            stdout = self.queue
        elif argv[0] == "sbatch":
            stdout = "uncertain reply" if self.bad_submit else str(self.next_job) + ";unity\n"
            self.next_job += 1
        elif argv[:2] == ["git", "clone"]:
            Path(argv[-1]).mkdir()
            (Path(argv[-1]) / "gallery").mkdir()
        elif argv[:2] == ["git", "diff"]:
            code = self.diff
        elif argv[:2] == ["git", "push"] and "--dry-run" not in argv:
            if self.push_failures:
                self.push_failures -= 1
                code = 1
        elif len(argv) > 1 and argv[1].endswith("check_gallery.py") and self.fail_check:
            code = 1
        if code and check:
            raise subprocess.CalledProcessError(code, argv)
        return subprocess.CompletedProcess(argv, code, stdout, "")

    def named(self, name):
        return [call[0] for call in self.calls if call[0][0] == name]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "gallery"
        self.campaign = Path(self.temp.name) / "campaign"
        (self.root / ".unity-publisher").mkdir(parents=True)
        (self.campaign / "validation").mkdir(parents=True)
        (self.campaign / "logs").mkdir()
        (self.campaign / "pilot.sbatch").write_text("unchanged scientific source\n")
        (self.campaign / "runtime/python-env/bin").mkdir(parents=True)
        (self.campaign / "runtime/python-env/bin/python3").touch()
        self.key = self.root / ".unity-publisher/id_ed25519"
        self.hosts = self.root / ".unity-publisher/known_hosts"
        self.key.write_text("fake test key")
        self.hosts.write_text("fake host key")

    def attach(self, runner, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return updates.attach(self.root, self.campaign, runner=runner, **kwargs)

    def publish(self, runner):
        with contextlib.redirect_stdout(io.StringIO()):
            return publisher.publish(self.root, self.campaign, "npizzo/choppy-cho-gallery",
                                     self.key, self.hosts, runner=runner)

    def test_validation_first_then_array_is_idempotent(self):
        (self.campaign / "logs/validate-66079691.out").touch()
        runner = FakeRunner("66079691|RUNNING|\n")
        first = self.attach(runner)
        self.assertEqual(len(runner.named("sbatch")), 2)
        self.assertIsNone(first["array_job"])
        self.attach(runner)
        self.assertEqual(len(runner.named("sbatch")), 2)
        (self.campaign / "validation/submission.txt").write_text("12345;unity\n")
        runner.states = "66079691|COMPLETED|\n12345_0|PENDING|\n12345_1|PENDING|\n"
        final = self.attach(runner)
        self.assertEqual(len(runner.named("sbatch")), 5)
        dependencies = [arg for call in runner.named("sbatch") for arg in call if arg.startswith("--dependency")]
        self.assertEqual(dependencies, ["--dependency=afterany:66079691", "--dependency=afterany:12345_0", "--dependency=afterany:12345_1"])
        self.attach(runner)
        self.assertEqual(len(runner.named("sbatch")), 5)
        self.assertEqual(final["array_job"], "12345")
        self.assertIsNone(final["validation_job"])
        dry_runs = [call for call in runner.calls if call[0][:3] == ["git", "push", "--dry-run"]]
        self.assertTrue(all(call[1] != self.root for call in dry_runs))
        self.assertEqual((self.campaign / "pilot.sbatch").read_text(), "unchanged scientific source\n")
        self.assertFalse((self.campaign / ".unity-publisher").exists())

    def test_terminal_members_only_need_snapshot(self):
        # A successful array no longer needs historical validation scheduler records.
        (self.campaign / "logs/validate-66079691.out").touch()
        runner = FakeRunner("12345_0|COMPLETED|\n12345_1|FAILED|\n")
        self.attach(runner, array_job="12345")
        self.assertEqual(len(runner.named("sbatch")), 1)
        self.assertFalse(any(arg.startswith("--dependency") for arg in runner.named("sbatch")[0]))

    def test_empty_campaign_can_publish_initial_snapshot(self):
        runner = FakeRunner()
        result = self.attach(runner)
        self.assertIsNone(result["array_job"])
        self.assertEqual(len(runner.named("sbatch")), 1)
        self.assertEqual(runner.named("sacct"), [])

    def test_submission_mismatch_and_unknown_scheduler_fail_before_mutation(self):
        (self.campaign / "validation/submission.txt").write_text("12345\n")
        runner = FakeRunner()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.attach(runner, array_job="12346")
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            self.attach(runner)
        self.assertEqual(runner.named("sbatch"), [])

    def test_queue_catches_accounting_lag(self):
        runner = FakeRunner(queue="12345_0|PENDING\n12345_1|RUNNING\n")
        self.attach(runner, array_job="12345")
        self.assertEqual(len(runner.named("sbatch")), 3)
        self.assertEqual(len(runner.named("squeue")), 1)

    def test_uncertain_submission_is_not_duplicated(self):
        runner = FakeRunner()
        runner.bad_submit = True
        with self.assertRaises(ValueError):
            self.attach(runner)
        record = json.loads((self.root / ".unity-publisher/updates.json").read_text())
        self.assertEqual(next(iter(record["events"].values()))["state"], "uncertain")
        runner.bad_submit = False
        with self.assertRaisesRegex(RuntimeError, "previous submission"):
            self.attach(runner)
        self.assertEqual(len(runner.named("sbatch")), 1)

    def test_invalid_or_conflicting_binding_rejected(self):
        for invalid in ["abc", "123_0", "123\n456", "123;unity extra", "0"]:
            with self.assertRaises(ValueError):
                updates.job_id(invalid)
        runner = FakeRunner()
        self.attach(runner)
        with self.assertRaisesRegex(RuntimeError, "different campaign"):
            with contextlib.redirect_stdout(io.StringIO()):
                updates.attach(self.root, self.campaign, "npizzo/other", runner=runner)
        with self.assertRaises(ValueError):
            updates.attach(self.root, self.root / "campaign", runner=runner)

    def test_push_retries_fresh_checkout_and_only_gallery_staged(self):
        runner = FakeRunner()
        runner.push_failures = 1
        self.publish(runner)
        clones = [args for args in runner.named("git") if args[1] == "clone"]
        pushes = [args for args in runner.named("git") if args[1] == "push"]
        stages = [args for args in runner.named("git") if args[1] == "add"]
        self.assertEqual(len(clones), 2)
        self.assertNotEqual(clones[0][-1], clones[1][-1])
        self.assertTrue(all("npizzo/choppy-cho-gallery.git" in " ".join(args) for args in clones + pushes))
        self.assertTrue(all(args == ["git", "add", "--", "gallery"] for args in stages))
        self.assertFalse(any("--force" in arg for call in runner.calls for arg in call[0]))
        exporters = [call for call in runner.calls if len(call[0]) > 1 and call[0][1].endswith("export_campaign.py")]
        self.assertEqual(len(exporters), 2)
        self.assertTrue(all("--campaign" in call[0] and "--destination" in call[0] for call in exporters))
        for _, _, env, _ in runner.calls:
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertIn("StrictHostKeyChecking=yes", env["GIT_SSH_COMMAND"])

    def test_unchanged_snapshot_has_no_commit_or_push(self):
        runner = FakeRunner()
        runner.diff = 0
        self.publish(runner)
        self.assertFalse(any("commit" in args or args[1] == "push" for args in runner.named("git")))

    def test_failed_export_check_or_git_diff_cannot_publish(self):
        runner = FakeRunner()
        runner.fail_check = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(runner)
        self.assertFalse(any(args[1] == "push" for args in runner.named("git")))
        runner = FakeRunner()
        runner.diff = 128
        with self.assertRaisesRegex(RuntimeError, "staged"):
            self.publish(runner)
        self.assertFalse(any(args[1] == "push" for args in runner.named("git")))

    def test_three_failed_pushes_stop_without_force(self):
        runner = FakeRunner()
        runner.push_failures = 5
        with self.assertRaisesRegex(RuntimeError, "three attempts"):
            self.publish(runner)
        self.assertEqual(len([args for args in runner.named("git") if args[1] == "push"]), 3)
        self.assertFalse(any("--force" in arg for call in runner.calls for arg in call[0]))


if __name__ == "__main__":
    unittest.main()
