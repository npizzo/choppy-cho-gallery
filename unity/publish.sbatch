#!/usr/bin/env bash
#SBATCH --job-name=choppy-gallery
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
set -euo pipefail
gallery_root=${1:?Gallery checkout required}
campaign_root=${2:?Campaign root required}
repository=${3:-npizzo/choppy-cho-gallery}
cd "$gallery_root"
# Read the recorded module without sourcing runtime.sh, which creates campaign directories.
if [[ -f "$campaign_root/runtime/python-module.txt" ]]; then
    IFS= read -r gallery_python_module < "$campaign_root/runtime/python-module.txt" || true
    if [[ -n ${gallery_python_module:-} ]]; then
        type module >/dev/null 2>&1 || { echo 'Saved Python module requires the Unity module environment.' >&2; exit 1; }
        module load "$gallery_python_module"
    fi
fi
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export MPLBACKEND=Agg MPLCONFIGDIR="$gallery_root/.unity-publisher/matplotlib"
srun --ntasks=1 "$campaign_root/runtime/python-env/bin/python3" scripts/publish_update.py \
    --campaign "$campaign_root" --repository "$repository"
