#!/usr/bin/env bash
# Install Livewall for the current user (no root needed).
#   ./install.sh [--no-systemd] [--enable]
#     --no-systemd  do not install the systemd user unit
#     --enable      enable + start the unit now and at login
#   Without --enable the unit file is still copied (not enabled), so
#   `livewall start` can use it; nothing runs until you start it.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}/livewall"
bin="$HOME/.local/bin"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
use_systemd=1; enable=0
for a in "$@"; do
  case "$a" in
    --no-systemd) use_systemd=0 ;;
    --enable) enable=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
command -v python3 >/dev/null || { echo "livewall needs python3 (3.11+)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "livewall needs Python 3.11+" >&2; exit 1; }

launcher="$bin/livewall"
if [ -e "$launcher" ] && ! grep -q 'from livewall.cli import main' "$launcher" 2>/dev/null; then
  echo "$launcher exists and is not the Livewall launcher; not overwriting it" >&2
  exit 1
fi

mkdir -p "$data" "$bin"
# Only Livewall's own copies under $data are replaced.
rm -rf "$data/livewall" "$data/renderer"
cp -r "$here/livewall" "$here/renderer" "$data/"
mkdir -p "$data/scenes"
for s in "$here"/scenes/*/; do
  [ -f "$s/scene.toml" ] || continue
  n="$(basename "$s")"; rm -rf "$data/scenes/$n"; cp -r "$s" "$data/scenes/$n"
done
cp "$here/README.md" "$data/" 2>/dev/null || true
find "$data" -name __pycache__ -type d -prune -exec rm -rf {} +
install -m 755 "$here/bin/livewall" "$launcher"
echo "installed livewall to $data (command: $launcher)"

if [ "$use_systemd" = 1 ] && command -v systemctl >/dev/null; then
  mkdir -p "$unit_dir"
  install -m 644 "$here/systemd/livewall.service" "$unit_dir/livewall.service"
  systemctl --user daemon-reload || true
  if [ "$enable" = 1 ]; then
    systemctl --user enable --now livewall.service
    echo "installed and enabled $unit_dir/livewall.service"
  else
    echo "installed $unit_dir/livewall.service (not enabled; run \`livewall start\` or re-run with --enable)"
  fi
elif [ "$enable" = 1 ]; then
  echo "note: --enable ignored (no systemd user unit installed); use \`livewall start\`"
fi
if ! command -v mpvpaper >/dev/null; then
  echo "note: install mpvpaper for the best player (otherwise the GTK player or swww is used)"
  # The GTK player plays the scene through GStreamer: it needs an MP4 demuxer and an H.264 decoder.
  if command -v gst-inspect-1.0 >/dev/null; then
    gst-inspect-1.0 qtdemux >/dev/null 2>&1 || echo "note: the GTK player needs gst-plugins-good (MP4 demuxer)"
    { gst-inspect-1.0 avdec_h264 || gst-inspect-1.0 vah264dec || gst-inspect-1.0 openh264dec; } >/dev/null 2>&1 \
      || echo "note: the GTK player needs an H.264 decoder: gst-libav or gst-plugin-va"
  else
    echo "note: the GTK player needs GStreamer with gst-plugins-good and gst-libav (or gst-plugin-va)"
  fi
fi
case ":$PATH:" in *":$bin:"*) ;; *) echo "note: add $bin to your PATH" ;; esac
