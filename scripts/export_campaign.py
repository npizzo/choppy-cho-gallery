#!/usr/bin/env python3
"""Export small, explicitly allowed outputs without changing a simulation."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import tomllib

MAX_ASSET = 90 * 1024**2
MAX_TEXT = 20 * 1024**2
CASES = (
    ("pilot", "Coupled parent and current", "The parent waves and the wave-averaged current act on each other. Cho follows the evolving parent and surface current."),
    ("prescribed", "Without current feedback to the parent", "The parent retains its intrinsic evolution. Current feedback to the parent is disabled; Cho still feels the parent and surface current."),
)
MSS_COLUMNS = ("time_s", "parent_mss", "cho_mss", "total_mss", "cross_contribution")
VIDEOS = (
    ("surface_startup", "Surface · first second"),
    ("surface_late", "Surface · last second"),
    ("surface_evolution", "Surface · full evolution"),
    ("underwater", "Underwater mean-flow vortices"),
)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def reject_symlink_ancestors(path):
    """Check the supplied path before resolving it or creating directories."""
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Symlinked export directory or ancestor")
    return path


def safe_source(root, relative):
    """Refuse symlinks, including symlinked parent directories."""
    path = root / relative
    for item in (path, *path.parents):
        if item == root.parent:
            break
        if item.is_symlink():
            raise ValueError("Symlinked input is not eligible for public export")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Input escapes the campaign directory")
    return path


def read_record(root, relative):
    path = safe_source(root, relative)
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_TEXT:
        raise ValueError("Metadata exceeds the export size limit")
    with path.open("rb") as stream:
        return tomllib.load(stream) if path.suffix == ".toml" else json.load(stream)


def csv_rows(root, relative):
    path = safe_source(root, relative)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_TEXT:
        raise ValueError("Diagnostic table exceeds the export size limit")
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        result = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Incomplete diagnostic row")
            converted = {key: float(value) for key, value in row.items()}
            if not all(finite(value) for value in converted.values()):
                raise ValueError("Nonfinite diagnostic data")
            result.append(converted)
    if not result:
        raise ValueError("Empty diagnostic table")
    return columns, result


def check_times(rows, key):
    times = [row[key] for row in rows]
    if times[0] < 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Diagnostic times must be nonnegative and increasing")


def read_mss(root, relative):
    result = csv_rows(root, relative)
    if result is None:
        return None
    columns, rows = result
    if columns != list(MSS_COLUMNS):
        raise ValueError("Unexpected MSS table columns")
    check_times(rows, "time_s")
    for row in rows:
        p, c, total, cross = (row[key] for key in MSS_COLUMNS[1:])
        if min(p, c, total) < 0 or not math.isclose(total, p + c + cross, rel_tol=1e-8, abs_tol=1e-13):
            raise ValueError("MSS positivity or decomposition check failed")
    return rows


def read_sidebands(root, relative):
    result = csv_rows(root, relative)
    if result is None:
        return None
    columns, rows = result
    indices = sorted(int(key[4:]) for key in columns if key.startswith("ReA_") and key[4:].isdigit())
    if not indices or indices != list(range(1, len(indices) + 1)) or any(f"ImA_{i}" not in columns for i in indices) or "t" not in columns:
        raise ValueError("Unknown parent-mode table layout")
    check_times(rows, "t")
    def powers(row):
        return [row[f"ReA_{i}"] ** 2 + row[f"ImA_{i}"] ** 2 for i in indices]
    carrier = max(range(len(indices)), key=lambda i: powers(rows[0])[i])
    output = []
    for row in rows:
        power = powers(row)
        total = math.fsum(power)
        if not finite(total) or total <= 0:
            raise ValueError("Parent-mode elevation variance is zero or nonfinite")
        fraction = math.fsum(value for i, value in enumerate(power) if i != carrier) / total
        output.append({"time_s": row["t"], "sideband_elevation_variance_fraction": fraction})
    return output


def install_bytes(destination, case_id, name, payload):
    if len(payload) >= MAX_ASSET:
        raise ValueError("Asset exceeds the public per-file limit")
    suffix = Path(name).suffix
    stem = Path(name).stem
    digest = hashlib.sha256(payload).hexdigest()[:16]
    relative = Path("media") / case_id / f"{stem}-{digest}{suffix}"
    target = destination / relative
    reject_symlink_ancestors(target)
    if target.exists():
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("Existing public asset does not match its digest")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            stream.write(payload)
            temporary = Path(stream.name)
        os.replace(temporary, target)
    return relative.as_posix()


def install_file(root, relative, destination, case_id):
    source = safe_source(root, relative)
    before = source.stat()
    if before.st_size >= MAX_ASSET:
        raise ValueError("Asset exceeds the public per-file limit")
    payload = source.read_bytes()
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Asset is changing; retry after rendering finishes")
    if source.suffix == ".mp4" and payload[4:8] != b"ftyp":
        raise ValueError("Unrecognized MP4 container")
    if source.suffix == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Unrecognized PNG image")
    return install_bytes(destination, case_id, source.name, payload)


def table_asset(destination, case_id, name, rows, columns):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row[key] for key in columns} for row in rows)
    return install_bytes(destination, case_id, name, buffer.getvalue().encode())


def plot_asset(destination, case_id, name, rows):
    """CSV export remains usable on a host without Matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    with plt.rc_context({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}):
        fig, ax = plt.subplots(figsize=(8, 4.2), constrained_layout=True)
        times = [row["time_s"] for row in rows]
        if name == "mss":
            for key, label, color in (("parent_mss", "Parent", "#7a8790"), ("total_mss", "Parent + Cho", "#166b83"), ("cho_mss", "Cho disturbance", "#cb7047")):
                ax.plot(times, [row[key] for row in rows], label=label, color=color, lw=1.8)
            ax.set_ylabel("Mean square slope")
            ax.set_ylim(bottom=0)
            ax.legend(frameon=False)
        else:
            ax.plot(times, [100 * row["sideband_elevation_variance_fraction"] for row in rows], color="#166b83", lw=1.8)
            ax.set_ylabel("Free-mode sideband variance (%)")
            ax.set_ylim(bottom=0)
        ax.set_xlabel("Physical time (s)")
        ax.grid(alpha=.15)
        output = io.BytesIO()
        fig.savefig(output, format="png", dpi=150, metadata={"Software": "choppy-cho-gallery"})
        plt.close(fig)
    return install_bytes(destination, case_id, name + ".png", output.getvalue())


def build_case(campaign, destination, case_id, title, description):
    relative = Path("data") / case_id
    case = dict(id=case_id, title=title, description=description, status="awaiting_sync",
                status_text="No run outputs have been synchronized.", tank_complete=False,
                observed_time_s=None, metrics={}, videos=[], figures=[], downloads=[], notices=[])
    def record(name):
        try:
            value = read_record(campaign, relative / name)
            if not isinstance(value, dict):
                raise ValueError("Expected a record")
            return value
        except (ValueError, OSError, KeyError):
            case["notices"].append(f"The {name} record is unavailable or incomplete; its fields were omitted.")
            return {}
    metadata, status, checks = record("metadata.toml"), record("status.toml"), record("checks.json")
    case["tank_complete"] = metadata.get("complete") is True
    if finite(status.get("time")) and status["time"] >= 0:
        case["observed_time_s"] = status["time"]
    for key, source_key in (("mean_divergence_max_per_s", "max_divergence"), ("mean_cfl", "mean_cfl")):
        value = status.get(source_key)
        if finite(value) and value >= 0:
            case["metrics"][key] = value
    if finite(checks.get("maximum_disturbance_m")) and checks["maximum_disturbance_m"] >= 0:
        case["metrics"]["maximum_disturbance_m"] = checks["maximum_disturbance_m"]
    mss = None
    for name, reader, filename, columns, title, caption in (
        ("mss", read_mss, "surface/mean_square_slope.csv", MSS_COLUMNS, "Mean square slope", "Parent and total slopes are nonnegative. Their difference also contains the signed parent–Cho cross term; the CSV includes every contribution."),
        ("sidebands", read_sidebands, "parent.csv", ("time_s", "sideband_elevation_variance_fraction"), "Parent-wave sidebands", "Share of retained free-mode elevation variance outside the largest initial mode. Bound harmonics and Cho roughness are excluded."),
    ):
        try:
            rows = reader(campaign, relative / filename)
            if rows is None:
                continue
            src = table_asset(destination, case_id, name + ".csv", rows, columns)
            case["downloads"].append(dict(title=title + " · CSV", src=src))
            figure = plot_asset(destination, case_id, name, rows)
            if figure:
                case["figures"].append(dict(id=name, title=title, src=figure, caption=caption))
            else:
                case["notices"].append(f"{title} is available as CSV; chart generation requires Matplotlib.")
            if name == "mss":
                mss = rows
                last = rows[-1]
                case["metrics"].update(final_parent_mss=last["parent_mss"], final_cho_disturbance_mss=last["cho_mss"], final_total_mss=last["total_mss"], final_cross_slope_term=last["cross_contribution"], duration_s=last["time_s"])
            else:
                case["metrics"].update(parent_sideband_elevation_variance_fraction_initial=rows[0]["sideband_elevation_variance_fraction"], parent_sideband_elevation_variance_fraction_final=rows[-1]["sideband_elevation_variance_fraction"])
        except (ValueError, OSError, KeyError, OverflowError):
            case["notices"].append(f"{title} data are unavailable or fail consistency checks; this diagnostic was omitted.")
    for name, title in VIDEOS:
        try:
            source = safe_source(campaign, relative / (name + ".mp4"))
            if not source.exists():
                continue
            render = record(name + ".json")
            # Both renderers write the metadata only after their encoder closes.
            if not render:
                case["notices"].append(f"{title} is awaiting its renderer completion record.")
                continue
            completion = safe_source(campaign, relative / (name + ".json"))
            if completion.stat().st_mtime_ns < source.stat().st_mtime_ns:
                case["notices"].append(f"{title} is newer than its completion record; it may still be rendering.")
                continue
            video = dict(id=name, title=title, src=install_file(campaign, relative / source.name, destination, case_id))
            poster = source.with_suffix(".png")
            if poster.exists():
                video["poster"] = install_file(campaign, relative / poster.name, destination, case_id)
            interval = render.get("physical_interval_s")
            if name == "underwater":
                times = render.get("time_seconds", [])
                if isinstance(times, list) and times and all(finite(t) and t >= 0 for t in times):
                    interval = [min(times), max(times)]
            if isinstance(interval, list) and len(interval) == 2 and all(finite(t) for t in interval) and 0 <= interval[0] < interval[1]:
                video["physical_interval_s"] = interval
            speed = render.get("physical_playback_speed")
            if finite(speed) and speed > 0:
                video["physical_playback_speed"] = speed
            case["videos"].append(video)
        except (ValueError, OSError, KeyError):
            case["notices"].append(f"{title} could not be safely exported, or exceeds the 90 MiB file limit.")
    if metadata or status or checks or case["videos"] or case["downloads"]:
        case["status"] = "partial"
        case["status_text"] = "Some outputs are available; this snapshot does not establish the job's current state."
    ids = {video["id"] for video in case["videos"]}
    if case["tank_complete"] and mss and "underwater" in ids and any(name.startswith("surface_") for name in ids):
        case["status"] = "outputs_available"
        case["status_text"] = "Surface, underwater, and slope outputs are available. Job status is not monitored by this page."
    elif case["tank_complete"]:
        case["notices"].append("The parent/current integration has a completion record. Cho diagnostics and rendering have separate completion requirements.")
    return case


def export_campaign(campaign, destination, validation_job="66079691"):
    campaign = Path(campaign).resolve()
    destination = reject_symlink_ancestors(destination).resolve()
    if not campaign.is_dir():
        raise ValueError("Campaign directory does not exist")
    if destination.is_relative_to(campaign):
        raise ValueError("Keep the gallery outside the validated simulation bundle")
    if not str(validation_job).isdigit():
        raise ValueError("Validation job must be a numeric Slurm identifier")
    destination.mkdir(parents=True, exist_ok=True)
    validation = {"job_id": str(validation_job), "state": "not_synchronized", "description": "Validation was submitted; its result has not been synchronized."}
    try:
        record = read_record(campaign, "validation/passed.json")
        if isinstance(record, dict) and record.get("status") == "passed":
            validation.update(state="record_available", description="A successful numerical-consistency validation record is available. This gallery does not revalidate the current simulation source fingerprint.")
    except (ValueError, OSError):
        pass
    experiment = {"wavelength_m": .08, "initial_steepness": .28, "damping_multiplier": 2.4, "duration_s": 10., "domain_m": [.32, .32, .12]}
    try:
        config = read_record(campaign, "configs/pilot.toml")
        for key, source in (("initial_steepness", "steepness"), ("damping_multiplier", "damping_multiplier"), ("duration_s", "duration")):
            if finite(config.get(source)) and config[source] > 0:
                experiment[key] = config[source]
        if all(finite(config.get(key)) and config[key] > 0 for key in ("Lx", "Ly", "H")):
            experiment["domain_m"] = [config[key] for key in ("Lx", "Ly", "H")]
            if finite(config.get("carrier_mx")) and config["carrier_mx"] > 0:
                experiment["wavelength_m"] = config["Lx"] / config["carrier_mx"]
    except (ValueError, OSError):
        pass
    cases = [build_case(campaign, destination, *case) for case in CASES]
    state = "outputs_available" if all(case["status"] == "outputs_available" for case in cases) else "partial" if any(case["status"] != "awaiting_sync" for case in cases) else "awaiting_sync"
    manifest = dict(schema_version=1, title="Choppy waves, capillary roughness, and currents", updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), status=state,
                    status_text={"awaiting_sync": "Awaiting the first synchronized Unity outputs.", "partial": "A partial output snapshot is available.", "outputs_available": "Both experiment cases have surface, underwater, and slope outputs."}[state],
                    validation=validation, experiment=experiment, cases=cases,
                    notes=["The parent and current use a reduced reciprocal coupling. Cho responds to parent curvature, parent orbital motion, and the surface mean current; Cho does not feed back on the parent or current.",
                           "The moving surface is reconstructed separately from the wave-averaged Oceananigans current; this is not an interface-resolving flow calculation.",
                           "The parent retains nine free modes and bounded second-order corrections. Changes in crest shape and sideband content are limited by that representation.",
                           "Surface and underwater movies use different playback rates. Compare their physical time intervals, not their video clocks.",
                           "Only derived videos, plots, and compact diagnostics are public. Native fields, checkpoints, and host paths remain outside this gallery."])
    from check_gallery import check_manifest
    check_manifest(manifest, destination)
    data = destination / "data"
    reject_symlink_ancestors(data / "campaign.json")
    data.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=data, delete=False, encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, data / "campaign.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--validation-job", default="66079691")
    args = parser.parse_args()
    manifest = export_campaign(args.campaign, args.destination, args.validation_job)
    print(f"Exported {len(manifest['cases'])} cases: {manifest['status']}")


if __name__ == "__main__":
    main()
