#!/usr/bin/env python3
"""Validate the public gallery, its asset references, and publication limits."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote

MAX_ASSET = 90 * 1024**2
MAX_TOTAL = 800 * 1024**2
ALLOWED = {".html", ".css", ".js", ".json", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".txt", ".svg"}
TEXT = {".html", ".css", ".js", ".json", ".csv", ".txt", ".svg"}
PRIVATE = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|/(?:Users|home|work|u)/|privkey\.key", re.I)
STATES = {"awaiting_sync", "partial", "outputs_available"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def no_private(value):
    if isinstance(value, str):
        require(not PRIVATE.search(value), "Private path or credential-like text in public content")
    elif isinstance(value, dict):
        for key, item in value.items():
            no_private(key)
            no_private(item)
    elif isinstance(value, list):
        for item in value:
            no_private(item)
    elif isinstance(value, float):
        require(math.isfinite(value), "Nonfinite JSON number")


def asset(root, reference, suffixes):
    require(isinstance(reference, str) and bool(reference), "Empty asset reference")
    path = PurePosixPath(reference)
    require(not path.is_absolute() and "\\" not in reference and ":" not in reference and "?" not in reference and "#" not in reference and unquote(reference) == reference, "Asset references must be plain relative paths")
    require(all(part not in ("", ".", "..") and not part.startswith(".") for part in reference.split("/")), "Unsafe asset path")
    require(path.suffix.lower() in suffixes, "Unexpected referenced asset type")
    target = root.joinpath(*path.parts)
    require(target.is_file() and not target.is_symlink(), "Referenced asset is absent or symlinked")
    require(target.resolve().is_relative_to(root.resolve()), "Referenced asset escapes gallery")
    require(0 < target.stat().st_size < MAX_ASSET, "Referenced asset is empty or too large")
    return target


def number(value, nonnegative=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (not nonnegative or value >= 0)


def check_manifest(data, root):
    root = Path(root)
    require(isinstance(data, dict) and data.get("schema_version") == 1, "Unsupported manifest schema")
    no_private(data)
    require(data.get("status") in STATES, "Invalid campaign state")
    require(isinstance(data.get("title"), str) and isinstance(data.get("updated_at"), str), "Missing campaign metadata")
    require(isinstance(data.get("status_text"), str), "Missing status explanation")
    validation = data.get("validation", {})
    require(isinstance(validation, dict) and str(validation.get("job_id", "")).isdigit(), "Invalid validation job")
    require(validation.get("state") in {"not_synchronized", "record_available"}, "Invalid validation state")
    experiment = data.get("experiment", {})
    require(isinstance(experiment, dict), "Missing experiment parameters")
    for name in ("wavelength_m", "initial_steepness", "damping_multiplier", "duration_s"):
        require(number(experiment.get(name)) and experiment[name] > 0, "Invalid experiment parameter")
    require(isinstance(experiment.get("domain_m"), list) and len(experiment["domain_m"]) == 3 and all(number(value) and value > 0 for value in experiment["domain_m"]), "Invalid experiment domain")
    cases = data.get("cases")
    require(isinstance(cases, list) and len(cases) == 2 and {case.get("id") for case in cases} == {"pilot", "prescribed"}, "Expected the pilot and prescribed cases")
    for case in cases:
        require(case.get("status") in STATES, "Invalid case status")
        require(isinstance(case.get("tank_complete"), bool), "Tank completion must be explicit")
        require(case.get("observed_time_s") is None or number(case["observed_time_s"], True), "Invalid observed time")
        require(isinstance(case.get("metrics"), dict) and all(number(value) for value in case["metrics"].values()), "Metrics must be finite numeric values")
        metrics = case["metrics"]
        for name, value in metrics.items():
            if name != "final_cross_slope_term":
                require(value >= 0, "Unexpected negative metric")
            if "variance_fraction" in name:
                require(0 <= value <= 1, "Invalid variance fraction")
        mss = ("final_parent_mss", "final_cho_disturbance_mss", "final_total_mss", "final_cross_slope_term")
        if all(name in metrics for name in mss):
            p, c, total, cross = (metrics[name] for name in mss)
            require(math.isclose(total, p + c + cross, rel_tol=1e-8, abs_tol=1e-13), "Invalid MSS decomposition")
        for category in ("videos", "figures", "downloads", "notices"):
            require(isinstance(case.get(category), list), "Case collections must be arrays")
        ids = []
        for video in case["videos"]:
            require(video.get("id") in {"surface_startup", "surface_late", "surface_evolution", "underwater"}, "Unknown video kind")
            ids.append(video["id"])
            asset(root, video.get("src"), {".mp4"})
            if "poster" in video:
                asset(root, video["poster"], {".png", ".jpg", ".jpeg", ".webp"})
            if "physical_interval_s" in video:
                interval = video["physical_interval_s"]
                require(isinstance(interval, list) and len(interval) == 2 and all(number(value, True) for value in interval) and interval[0] < interval[1], "Invalid movie physical interval")
            if "physical_playback_speed" in video:
                require(number(video["physical_playback_speed"]) and video["physical_playback_speed"] > 0, "Invalid playback speed")
        require(len(ids) == len(set(ids)), "Duplicate video kind")
        for figure in case["figures"]:
            asset(root, figure.get("src"), {".png", ".jpg", ".jpeg", ".webp", ".svg"})
        for download in case["downloads"]:
            asset(root, download.get("src"), {".csv", ".json", ".txt"})
        if case["status"] == "outputs_available":
            require(case["tank_complete"] and "underwater" in ids and any(item.startswith("surface_") for item in ids) and all(name in metrics for name in mss), "Outputs-available state lacks required evidence")
        if case["status"] == "awaiting_sync":
            require(not case["videos"] and not case["figures"] and not case["downloads"] and not metrics and not case["tank_complete"] and case["observed_time_s"] is None, "Awaiting-sync state contains observed outputs")
    expected = "outputs_available" if all(case["status"] == "outputs_available" for case in cases) else "partial" if any(case["status"] != "awaiting_sync" for case in cases) else "awaiting_sync"
    require(data["status"] == expected, "Campaign status does not match its cases")


def check_gallery(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "Gallery directory is absent or symlinked")
    total = 0
    for path in root.rglob("*"):
        require(not path.is_symlink(), "Symlinks are not allowed in the public gallery")
        require(not any(part.startswith(".") for part in path.relative_to(root).parts), "Hidden public paths are not allowed")
        if path.is_file():
            require(path.suffix.lower() in ALLOWED, "Unapproved public file type")
            size = path.stat().st_size
            require(0 < size < MAX_ASSET, "Public asset is empty or exceeds 90 MiB")
            total += size
            require(total < MAX_TOTAL, "Public gallery exceeds 800 MiB")
            if path.suffix.lower() in TEXT:
                no_private(path.read_text(encoding="utf-8"))
    manifest = root / "data/campaign.json"
    require(manifest.is_file(), "Campaign manifest is missing")
    check_manifest(json.loads(manifest.read_text()), root)
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gallery", type=Path)
    args = parser.parse_args()
    total = check_gallery(args.gallery)
    print(f"Public gallery checks passed ({total / 1024**2:.2f} MiB)")


if __name__ == "__main__":
    main()
