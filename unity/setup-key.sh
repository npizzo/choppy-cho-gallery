#!/usr/bin/env bash
# Run inside the separate gallery checkout on Unity.
set -euo pipefail
gallery_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
publisher_state="$gallery_root/.unity-publisher"
mkdir -p "$publisher_state/logs"
chmod 700 "$publisher_state"
if [[ ! -f "$publisher_state/id_ed25519" ]]; then
    ssh-keygen -q -t ed25519 -N '' -C 'Unity choppy-cho-gallery publisher' -f "$publisher_state/id_ed25519"
fi
chmod 600 "$publisher_state/id_ed25519"
[[ -f "$publisher_state/id_ed25519.pub" ]] || { echo 'The existing publishing key has no public-key file; inspect it before continuing.' >&2; exit 1; }
# Get authenticated GitHub host keys over HTTPS; do not silently trust ssh-keyscan.
python3 - "$publisher_state/known_hosts" <<'PY'
import json
from pathlib import Path
import sys
import urllib.request
request = urllib.request.Request('https://api.github.com/meta', headers={'User-Agent':'choppy-cho-gallery-setup'})
with urllib.request.urlopen(request, timeout=30) as response:
    keys = json.load(response)['ssh_keys']
if not keys or not all(isinstance(k, str) and k.startswith(('ssh-ed25519 ', 'ecdsa-sha2-nistp256 ', 'ssh-rsa ')) and '\n' not in k and '\r' not in k for k in keys):
    raise SystemExit('Invalid GitHub host-key metadata')
target = Path(sys.argv[1])
temporary = target.with_suffix('.tmp')
temporary.write_text(''.join('github.com ' + key + '\n' for key in keys))
temporary.replace(target)
PY
echo 'Add this PUBLIC key to npizzo/choppy-cho-gallery under Settings > Deploy keys, with Allow write access enabled:'
cat "$publisher_state/id_ed25519.pub"
echo 'The private key remains on Unity inside .unity-publisher/; never paste or upload it.'
