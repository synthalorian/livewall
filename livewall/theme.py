"""Find the active Omarchy theme, and the scene that belongs to it.

Omarchy has stored the current theme in a few ways over time; all are checked:

  * ~/.local/state/omarchy/current/theme.name   (current Omarchy)
  * ~/.config/omarchy/current/theme.name         (Omarchy 3.x)
  * ~/.config/omarchy/current/theme -> ../themes/<name>   (older: a symlink)
  * a generated ~/.config/omarchy/current/theme/ (or the state dir copy) whose
    colors.toml is matched against each scene's [match] palette.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from livewall import paths
from livewall.scenes import Scene, norm


@dataclass
class ThemeInfo:
    name: str | None          # normalised theme name, None if unknown
    source: str               # how it was found
    dir: Path | None = None   # the active theme folder, if any
    colors: dict | None = None


def _read_name(f: Path) -> str | None:
    try:
        v = f.read_text().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return norm(v) or None


def _colors(d: Path | None) -> dict | None:
    if not d:
        return None
    try:
        return tomllib.loads((d / "colors.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None


def detect_theme(home: Path | None = None) -> ThemeInfo:
    home = home or paths.home()
    env = os.environ.get("LIVEWALL_THEME")
    cfg_cur = home / ".config/omarchy/current"
    st_cur = home / ".local/state/omarchy/current"
    theme_dir = next((d for d in (cfg_cur / "theme", st_cur / "theme") if d.is_dir()), None)
    colors = _colors(theme_dir)
    if env:
        return ThemeInfo(norm(env), "LIVEWALL_THEME", theme_dir, colors)
    for f in (st_cur / "theme.name", cfg_cur / "theme.name"):
        n = _read_name(f)
        if n:
            return ThemeInfo(n, str(f), theme_dir, colors)
    link = cfg_cur / "theme"
    if link.is_symlink():
        target = Path(os.readlink(link))
        n = norm(target.name)
        if n:
            return ThemeInfo(n, f"{link} -> {target}", theme_dir, colors)
    if theme_dir is not None:
        return ThemeInfo(None, f"{theme_dir} (no name; palette only)", theme_dir, colors)
    return ThemeInfo(None, "no Omarchy theme found")


def _hex(v) -> str | None:
    return v.strip().lower() if isinstance(v, str) and v.startswith("#") else None


def pick_scene(theme: ThemeInfo, scenes: list[Scene]) -> tuple[Scene | None, str]:
    """Return (scene, reason). Name match first, then palette match."""
    if theme.name:
        for s in scenes:
            if s.matches_theme(theme.name):
                return s, f"theme '{theme.name}'"
    if theme.colors:
        for s in scenes:
            if not s.match:
                continue
            keys = [k for k in s.match if k in theme.colors]
            if keys and all(_hex(theme.colors[k]) == s.match[k] for k in keys):
                return s, "palette match (" + ", ".join(keys) + ")"
    who = f"theme '{theme.name}'" if theme.name else "the current theme"
    return None, f"no scene for {who}"


def static_background(home: Path | None = None) -> Path | None:
    """The image Omarchy is showing, used as the static fallback."""
    home = home or paths.home()
    for link in (home / ".local/state/omarchy/current/background",
                 home / ".config/omarchy/current/background"):
        if link.exists():
            return link.resolve()
    return None
