#!/usr/bin/env bash
# Rebuild previews/ from the neon-horizon scene (fully procedural).
#   generators/make_previews.sh [path/to/neon-horizon/colors.toml]
#   (default: ~/.config/omarchy/themes/neon-horizon/colors.toml)
#   hero.png      1920x1080 still at the sun-pulse peak (t = 0.25)
#   preview.webm  1280x720 VP9 two-pass, ~430 kb/s (about 435 KB for the 8 s loop)
#   preview.mp4   1280x720 H.264 for players without VP9
# Runs niced, with 2 threads, one job at a time; it is safe on a shared box.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lw="$(dirname "$here")"
colors="${1:-${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/themes/neon-horizon/colors.toml}"
[ -f "$colors" ] || { echo "colors.toml not found: $colors" >&2; exit 1; }
out="$lw/previews"; src="$lw/scenes/neon-horizon/loop-2160p.mp4"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
run() { nice -n 19 timeout 900 "$@"; }
run python3 "$here/neon_horizon.py" --colors "$colors" \
    --size 1920x1080 --still "$out/hero.png" --t 0.25
vf="scale=1280:720:flags=lanczos"
vp9=(-c:v libvpx-vp9 -threads 2 -row-mt 0 -b:v 430k -minrate 200k -maxrate 600k -deadline good -cpu-used 2)
run ffmpeg -v error -threads 2 -i "$src" -vf "$vf" "${vp9[@]}" -pass 1 -passlogfile "$tmp/vp9" -an -f null -
run ffmpeg -v error -threads 2 -i "$src" -vf "$vf" "${vp9[@]}" -pass 2 -passlogfile "$tmp/vp9" \
    -auto-alt-ref 1 -lag-in-frames 25 -an -y "$out/preview.webm"
run ffmpeg -v error -threads 2 -i "$src" -vf "$vf" -c:v libx264 -threads 2 -preset slow -crf 24 \
    -pix_fmt yuv420p -movflags +faststart -an -y "$out/preview.mp4"
ls -l "$out"
