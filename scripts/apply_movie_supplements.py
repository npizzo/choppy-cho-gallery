#!/usr/bin/env python3
"""Add validated post-processing movies without changing frozen publishers."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import math
import re

SLUG = 'langmuir-steepening'
CASES = {'steep12', 'long10'}
MAX_ASSET = 90 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def checked_asset(root, name, suffix):
    require(isinstance(name, str) and re.fullmatch(r'(steep12|long10)/parent_plus_cho_evolution\.(mp4|png|json)', name), 'Invalid supplement asset path')
    path = root / name
    require(path.suffix == suffix and path.is_file() and not path.is_symlink(), 'Missing or invalid supplement asset')
    require(path.resolve().is_relative_to(root.resolve()), 'Supplement asset escapes its directory')
    require(0 < path.stat().st_size < MAX_ASSET, 'Supplement asset is empty or too large')
    return path


def validate_metadata(meta, case, snapshot):
    require(case in CASES, 'Unknown supplement case')
    record = next((c for c in snapshot['cases'] if c['id'] == case), None)
    require(record is not None and record['status'] == 'complete', 'Supplement requires a completed published case')
    require(meta.get('case') == case, 'Supplement case mismatch')
    require(meta.get('source_fingerprint') == snapshot['source_fingerprint'], 'Supplement source does not match published science')
    require(snapshot.get('cho_enabled') is True and snapshot.get('cho_damping_multiplier') == 2.4, 'Published case is not the requested Cho calculation')
    require(meta.get('quantity') == 'parent_plus_cho' and meta.get('cho_enabled') is True and meta.get('damping_multiplier') == 2.4, 'Supplement must show parent plus Cho at 2.4 damping')
    require(meta.get('render_complete') is True and meta.get('full_saved_interval') is True, 'Supplement rendering must be complete over the full saved interval')
    duration = record['parameters']['duration']
    interval = meta.get('physical_interval_s')
    require(isinstance(interval, list) and len(interval) == 2 and all(finite(v) for v in interval), 'Invalid movie interval')
    require(abs(interval[0]) < 1e-8 and abs(interval[1] - duration) < 1e-8, 'Supplement must show the complete physical interval')
    require(meta.get('physical_playback_speed') == .2 and meta.get('fps') == 20, 'Supplement must use 0.2x speed at 20 fps')
    frames, encoded = meta.get('video_frame_count'), meta.get('encoded_duration_s')
    require(isinstance(frames, int) and not isinstance(frames, bool) and frames > 1 and finite(encoded), 'Missing movie frame count or duration')
    require(abs(encoded - frames / 20) < 1e-8 and abs(encoded - duration / .2) <= 1 / 20 + 1e-8, 'Movie timing is inconsistent with the complete interval')
    require(meta.get('vertical_exaggeration') == 1, 'Supplement must retain physical wave amplitudes')
    return duration


def apply(root):
    root = Path(root)
    supplements = root / 'supplements' / SLUG
    manifest_path = supplements / 'manifest.json'
    if not manifest_path.exists():
        return 0
    require(not manifest_path.is_symlink(), 'Supplement manifest may not be symlinked')
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get('schema_version') == 1 and manifest.get('experiment') == SLUG, 'Unknown supplement manifest')
    entries = manifest.get('cases')
    require(isinstance(entries, dict) and set(entries) <= CASES, 'Invalid supplement cases')
    page = root / 'experiments' / SLUG / 'index.html'
    snapshot = json.loads(page.with_name('snapshot.json').read_text())
    require(manifest.get('source_fingerprint') == snapshot['source_fingerprint'], 'Supplement manifest has a different scientific source')
    content = page.read_text()
    for case, entry in entries.items():
        assets = {key: checked_asset(supplements, entry.get(key), ext) for key, ext in [('video', '.mp4'), ('poster', '.png'), ('metadata', '.json')]}
        for key, path in assets.items():
            require(entry.get('sha256', {}).get(key) == hashlib.sha256(path.read_bytes()).hexdigest(), 'Supplement asset checksum mismatch')
            require(entry[key].split('/')[0] == case, 'Asset belongs to a different case')
        meta = json.loads(assets['metadata'].read_text())
        duration = validate_metadata(meta, case, snapshot)
        start, end = f'<!-- full-cho:{case}:start -->', f'<!-- full-cho:{case}:end -->'
        require(content.count(start) == content.count(end) <= 1, 'Duplicate or incomplete supplement section')
        content = re.sub(r'\n?' + re.escape(start) + r'.*?' + re.escape(end) + r'\n?', '', content, flags=re.S)
        anchor = f'<p><a href="assets/{case}/parent_evolution.json">Parent movie metadata</a></p>'
        require(content.count(anchor) == 1, 'Parent movie insertion point changed')
        prefix = '../../supplements/' + SLUG + '/'
        video, poster, metadata = (html.escape(prefix + entry[key], quote=True) for key in ('video', 'poster', 'metadata'))
        block = f'''{start}
<div id="full-cho-{case}" class="movie-supplement">
<h3>Full parent + Cho evolution</h3>
<p>The combined parent + Cho surface over all {duration:g} physical seconds, played at 0.2× speed: about {duration/.2:g} seconds of video. Wave amplitudes are shown without magnification.</p>
<video controls preload="metadata" poster="{poster}"><source src="{video}" type="video/mp4"></video>
<p><a href="{metadata}">Parent + Cho movie metadata</a></p>
</div>
{end}
'''
        content = content.replace(anchor, anchor + '\n' + block, 1)
    page.write_text(content)
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    args = parser.parse_args()
    print(f'Applied {apply(args.gallery)} full parent + Cho movie supplements.')


if __name__ == '__main__':
    main()
