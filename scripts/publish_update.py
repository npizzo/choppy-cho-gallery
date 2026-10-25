"""Read a Unity campaign and publish derived assets from a separate checkout."""
import argparse
import fcntl
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
DEFAULT_REPOSITORY = "npizzo/choppy-cho-gallery"


def command(argv, cwd, *, env=None, check=True):
    return subprocess.run(argv, cwd=cwd, env=env, check=check, text=True)


def validate_repository(repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub owner/repository")


def separate_paths(root, campaign):
    if root == campaign or root in campaign.parents or campaign in root.parents:
        raise ValueError("Keep the gallery checkout and scientific campaign in separate directories")


def publishing_environment(key, known_hosts, state):
    if not key.is_file() or not known_hosts.is_file():
        raise RuntimeError("Run bash unity/setup-key.sh and register the public deploy key first")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg",
               MPLCONFIGDIR=str(state / "matplotlib"), OPENBLAS_NUM_THREADS="1",
               OMP_NUM_THREADS="1")
    env["GIT_SSH_COMMAND"] = shlex.join([
        "ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known_hosts.resolve()),
        "-i", str(key.resolve()),
    ])
    return env


def publish(root, campaign, repository, key, known_hosts, *, runner=command):
    root, campaign = Path(root).resolve(), Path(campaign).resolve()
    separate_paths(root, campaign)
    validate_repository(repository)
    state = root / ".unity-publisher"
    state.mkdir(exist_ok=True, mode=0o700)
    env = publishing_environment(Path(key), Path(known_hosts), state)
    python = campaign / "runtime/python-env/bin/python3"
    if not python.is_file():
        raise RuntimeError("Campaign Python runtime is missing; finish the existing bootstrap first")
    if not (campaign / "pilot.sbatch").is_file():
        raise RuntimeError("Expected the choppy + Cho campaign root")
    with (state / "publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for attempt in range(3):
            with tempfile.TemporaryDirectory(prefix="publish-", dir=state) as scratch:
                checkout = Path(scratch) / "repository"
                runner(["git", "clone", "--single-branch", "--branch", "main",
                        f"https://github.com/{repository}.git", str(checkout)], root, env=env)
                runner([str(python), str(root / "scripts/export_campaign.py"),
                        "--campaign", str(campaign), "--destination", str(checkout / "gallery")], root, env=env)
                runner([str(python), str(root / "scripts/check_gallery.py"), str(checkout / "gallery")], root, env=env)
                runner(["git", "add", "--", "gallery"], checkout, env=env)
                changed = runner(["git", "diff", "--cached", "--quiet"], checkout, env=env, check=False)
                if changed.returncode == 0:
                    print("The public gallery already matches this snapshot.", flush=True)
                    return
                if changed.returncode != 1:
                    raise RuntimeError("Unable to inspect the staged gallery changes")
                runner(["git", "-c", "user.name=Choppy Cho gallery", "-c",
                        "user.email=7075590+npizzo@users.noreply.github.com", "commit",
                        "-m", "Update verified Unity choppy and Cho results"], checkout, env=env)
                pushed = runner(["git", "push", f"git@github.com:{repository}.git", "HEAD:main"],
                                checkout, env=env, check=False)
                if pushed.returncode == 0:
                    print("Gallery snapshot pushed. GitHub Pages will deploy it.", flush=True)
                    return
                print(f"Push failed on attempt {attempt + 1}; rebuilding against current main.", flush=True)
        raise RuntimeError("Publishing failed after three attempts; no force push was used")


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--key", type=Path, default=root / ".unity-publisher/id_ed25519")
    parser.add_argument("--known-hosts", type=Path, default=root / ".unity-publisher/known_hosts")
    args = parser.parse_args()
    publish(root, args.campaign, args.repository, args.key, args.known_hosts)


if __name__ == "__main__":
    main()
