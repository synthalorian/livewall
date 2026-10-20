#!/usr/bin/env bash
# Remove what install.sh installed, and nothing else. Kept: ~/.config/livewall
# (config, your own scenes and packs), the log in ~/.local/state/livewall, and
# anything you added under ~/.local/share/livewall yourself.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}/livewall"
launcher="$HOME/.local/bin/livewall"
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/livewall.service"
ours() { [ -f "$launcher" ] && grep -q 'from livewall.cli import main' "$launcher" 2>/dev/null; }

if ours; then "$launcher" stop 2>/dev/null || true; fi
if [ -f "$unit" ] && command -v systemctl >/dev/null; then
  systemctl --user disable --now livewall.service 2>/dev/null || true
fi
if [ -f "$unit" ]; then
  rm -f "$unit"
  command -v systemctl >/dev/null && { systemctl --user daemon-reload || true; }
fi
if [ -d "$data" ]; then
  rm -rf "$data/livewall" "$data/renderer"
  rm -f "$data/README.md"
  for s in "$here"/scenes/*/; do
    [ -f "$s/scene.toml" ] || continue
    rm -rf "$data/scenes/$(basename "$s")"
  done
  rmdir "$data/scenes" 2>/dev/null || true
  rmdir "$data" 2>/dev/null || echo "kept $data (it holds files Livewall did not install)"
fi
if ours; then rm -f "$launcher"; fi
echo "livewall removed (kept ${XDG_CONFIG_HOME:-$HOME/.config}/livewall)"
