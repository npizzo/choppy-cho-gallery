"""Attach publishing jobs to existing validation and pilot jobs, without resubmitting science."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publish_update import DEFAULT_REPOSITORY, publishing_environment, separate_paths, validate_repository

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL",
            "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED", "SPECIAL_EXIT"}


def command(argv, cwd, *, env=None, check=True):
    return subprocess.run(argv, cwd=cwd, env=env, check=check, text=True, capture_output=True)


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def job_id(value):
    # sbatch --parsable can return jobid;cluster.
    value = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]*(?:;[A-Za-z0-9_.-]+)?", value):
        raise ValueError("Expected a numeric Slurm parent job ID")
    return value.split(";", 1)[0]


def discover_jobs(campaign, array_job=None, validation_job=None):
    receipt = campaign / "validation/submission.txt"
    recorded_array = job_id(receipt.read_text()) if receipt.is_file() else None
    array = job_id(array_job) if array_job else recorded_array
    if recorded_array and array != recorded_array:
        raise ValueError("--array-job conflicts with validation/submission.txt")
    validation = job_id(validation_job) if validation_job else None
    if validation is None and not array:
        found = set()
        for path in (campaign / "logs").glob("validate-*"):
            match = re.fullmatch(r"validate-([1-9][0-9]*)\.(?:out|err)", path.name)
            if match:
                found.add(match.group(1))
        if len(found) == 1:
            validation = found.pop()
        elif len(found) > 1:
            raise ValueError("Several validation job logs exist; specify --validation-job")
    return array, validation


def scheduler_states(root, array, validation, runner):
    ids = [value for value in (array, validation) if value]
    if not ids:
        return {}
    reply = runner(["sacct", "--array", "-X", "-n", "-P", "-j", ",".join(ids),
                    "--format=JobID,State"], root)
    states = {}
    for line in reply.stdout.splitlines():
        fields = line.split("|")
        if len(fields) >= 2 and fields[1].strip():
            states[fields[0].strip()] = fields[1].split()[0].rstrip("+")
    parents = ([f"{array}_{i}" for i in range(2)] if array else []) + ([validation] if validation else [])
    if any(parent not in states for parent in parents):
        # Accounting may lag new submissions; request each pending array element.
        queue = runner(["squeue", "--array", "--noheader", "--jobs", ",".join(ids),
                        "--format=%i|%T"], root, check=False)
        if queue.returncode == 0:
            for line in queue.stdout.splitlines():
                fields = line.strip().split("|")
                if len(fields) == 2:
                    states[fields[0].strip()] = fields[1].strip().upper()
    missing = [parent for parent in parents if parent not in states]
    if missing:
        raise RuntimeError("Cannot verify scheduler state for " + ", ".join(missing) +
                           "; no publishing jobs attached. Retry after accounting catches up, or publish a one-off snapshot.")
    return states


def attach(root, campaign, repository=DEFAULT_REPOSITORY, *, array_job=None,
           validation_job=None, runner=command):
    root, campaign = Path(root).resolve(), Path(campaign).resolve()
    separate_paths(root, campaign)
    validate_repository(repository)
    if not (campaign / "pilot.sbatch").is_file():
        raise RuntimeError("Expected the choppy + Cho campaign root")
    state = root / ".unity-publisher"
    state.mkdir(exist_ok=True, mode=0o700)
    (state / "logs").mkdir(exist_ok=True)
    record_path = state / "updates.json"
    env = publishing_environment(state / "id_ed25519", state / "known_hosts", state)
    with (state / "attach.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = json.loads(record_path.read_text()) if record_path.is_file() else {
            "schema_version": 1, "campaign": str(campaign), "repository": repository, "events": {}}
        if record.get("schema_version") != 1 or record.get("campaign") != str(campaign) or record.get("repository") != repository:
            raise RuntimeError("This sidecar is attached to a different campaign or repository")
        if any(event.get("state") in {"submitting", "uncertain"} for event in record["events"].values()):
            raise RuntimeError("A previous submission may have succeeded without a recorded job ID. Inspect .unity-publisher/updates.json and squeue before repairing the record; no jobs resubmitted.")
        array, validation = discover_jobs(campaign, array_job, validation_job)
        states = scheduler_states(root, array, validation, runner)
        parents = ([f"{array}_{i}" for i in range(2)] if array else []) + ([validation] if validation else [])
        # One immediate snapshot per discovered phase; rerunning adds only newly observed jobs.
        phase = f"snapshot:{array or 'no-array'}:{validation or 'no-validation'}"
        events = [(phase, None)] + [("after:" + parent, parent) for parent in parents if states[parent] not in TERMINAL]
        todo = [(name, parent) for name, parent in events if name not in record["events"]]
        if not todo:
            print("Gallery updates are already attached; no duplicate jobs submitted.")
            return record
        # Check against current remote main: earlier publication may have advanced
        # main beyond this sidecar's checkout, which is normal and not an auth error.
        with tempfile.TemporaryDirectory(prefix="auth-", dir=state) as scratch:
            checkout = Path(scratch) / "repository"
            runner(["git", "clone", "--depth", "1", "--single-branch", "--branch", "main",
                    f"https://github.com/{repository}.git", str(checkout)], root, env=env)
            runner(["git", "push", "--dry-run", f"git@github.com:{repository}.git", "HEAD:main"], checkout, env=env)
        record.update({"array_job": array, "validation_job": validation})
        for name, parent in todo:
            record["events"][name] = {"state": "submitting", "after": parent}
            atomic_json(record_path, record)
            argv = ["sbatch", "--parsable", f"--output={state}/logs/publish-%j.out",
                    f"--error={state}/logs/publish-%j.err"]
            if parent:
                argv += [f"--dependency=afterany:{parent}", "--kill-on-invalid-dep=yes"]
            argv += [str(root / "unity/publish.sbatch"), str(root), str(campaign), repository]
            try:
                reply = runner(argv, root)
                submitted = job_id(reply.stdout)
            except Exception:
                record["events"][name]["state"] = "uncertain"
                atomic_json(record_path, record)
                raise
            record["events"][name].update({"state": "attached", "job_id": submitted})
            atomic_json(record_path, record)
        print(json.dumps(record, indent=2))
        if array:
            print("Gallery updates attached to the existing two-member pilot. No simulations submitted or changed.")
        else:
            print("Initial gallery/validation updates attached. After submitting the pilot, rerun this command to attach its two members. No simulations submitted or changed.")
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--array-job", help="Existing two-member pilot array ID; otherwise read validation/submission.txt")
    parser.add_argument("--validation-job", help="Existing validation ID; otherwise infer from a single validation log ID")
    args = parser.parse_args()
    attach(Path(__file__).resolve().parents[1], args.campaign, args.repository,
           array_job=args.array_job, validation_job=args.validation_job)


if __name__ == "__main__":
    main()
