"""Every filesystem location Livewall uses, resolved from the environment so the
tests (and unusual setups) can point it anywhere."""
from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
SRC_ROOT = PKG_DIR.parent                      # source checkout or ~/.local/share/livewall


def home() -> Path:
    return Path(os.environ.get("HOME", "~")).expanduser()


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "livewall"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "livewall"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "livewall"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/livewall-{os.getuid()}"
    return Path(base) / "livewall"


def config_file() -> Path:
    return config_dir() / "config.toml"


def override_file() -> Path:
    """Holds the scene chosen with `livewall set` (absent = follow the theme)."""
    return config_dir() / "scene"


def state_file() -> Path:
    return runtime_dir() / "state.json"


def pid_file() -> Path:
    return runtime_dir() / "daemon.pid"


def log_file() -> Path:
    return state_dir() / "livewall.log"


def scene_search_paths() -> list[Path]:
    """Highest priority first. A scene id found earlier shadows later ones.

    1. $LIVEWALL_SCENES (colon separated)
    2. ~/.config/livewall/scenes        (your own scenes)
    3. ~/.local/share/livewall/scenes   (installed built-ins)
    4. <source tree>/scenes             (running from a checkout)
    Packs are found next to each scenes dir, in a sibling packs/ dir.
    """
    out: list[Path] = []
    env = os.environ.get("LIVEWALL_SCENES")
    if env:
        out += [Path(p).expanduser() for p in env.split(":") if p]
    out += [config_dir() / "scenes", data_dir() / "scenes", SRC_ROOT / "scenes"]
    seen, uniq = set(), []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def pack_search_paths() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("LIVEWALL_PACKS")
    if env:
        out += [Path(p).expanduser() for p in env.split(":") if p]
    out += [config_dir() / "packs", data_dir() / "packs", SRC_ROOT / "packs"]
    seen, uniq = set(), []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def sysfs_power() -> Path:
    return Path(os.environ.get("LIVEWALL_SYSFS_POWER", "/sys/class/power_supply"))
