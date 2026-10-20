#!/usr/bin/env bash
# Render the procedural presets: scenes/<name>/loop-1080p.mp4 and poster.jpg.
#   generators/build_presets.sh              all presets
#   generators/build_presets.sh aurora ...   only these
# Needs ffmpeg, numpy and Pillow; no theme files. Runs niced with
# $LIVEWALL_THREADS (default 2) render processes, one scene at a time, and
# finishes with check_seam.py over everything it built.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scenes="$(dirname "$here")/scenes"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

# scene name and the loop position used for its poster
presets=(
  "sunset-drive 0.30" "neon-rain 0.30" "nebula-drift 0.30" "aurora 0.30"
  "ocean-dusk 0.10" "crt-terminal 0.40" "forge-sparks 0.30" "glyph-rain 0.30"
  "candlelight 0.20" "lofi-window 0.30" "vaporwave 0.60" "breathe 0.50"
)
want=" $* "
built=()
for entry in "${presets[@]}"; do
  read -r name t <<<"$entry"
  [ $# -eq 0 ] || [[ "$want" == *" $name "* ]] || continue
  gen="$here/${name//-/_}.py"
  out="$scenes/$name"
  echo "== $name"
  nice -n 19 python3 "$gen" --out "$out/loop-1080p.mp4"
  nice -n 19 python3 "$gen" --still "$out/poster.jpg" --t "$t"
  built+=("$out/loop-1080p.mp4")
done
[ ${#built[@]} -gt 0 ] || { echo "no such preset: $*" >&2; exit 2; }
ls -l "${built[@]}"
python3 "$here/check_seam.py" "${built[@]}"
