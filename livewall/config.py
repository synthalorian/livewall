"""~/.config/livewall/config.toml. Every key is optional."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields

from livewall import paths

DEFAULT_CONFIG = """\
# Livewall settings. Delete a line to get the default back.

# auto | mpvpaper | gtk | swww | static
backend = "auto"

# Layer-shell layer for the animated surface: "bottom" sits above swaybg (or
# the Omarchy shell background), so stopping Livewall reveals the static
# background again. Use "background" if something of yours lives on "bottom".
layer = "bottom"

# Pause (hold the current frame) while a window is fullscreen / on battery.
pause_on_fullscreen = true
pause_on_battery = true

# Which loop to use: "auto" picks per monitor, or force "1920x1080" / "3840x2160".
resolution = "auto"

# Seconds between battery/theme checks (fullscreen changes are event driven).
poll_interval = 3.0

# Extra mpv options for the mpvpaper backend.
mpv_options = ""
"""


@dataclass
class Config:
    backend: str = "auto"
    layer: str = "bottom"
    pause_on_fullscreen: bool = True
    pause_on_battery: bool = True
    resolution: str = "auto"
    poll_interval: float = 3.0
    mpv_options: str = ""

    @classmethod
    def load(cls) -> "Config":
        f = paths.config_file()
        if not f.is_file():
            return cls()
        try:
            data = tomllib.loads(f.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            return cls()
        known = {fl.name: fl.type for fl in fields(cls)}
        kw = {}
        for k, v in data.items():
            if k not in known:
                continue
            default = getattr(cls, k)
            if isinstance(default, bool):
                if isinstance(v, bool):
                    kw[k] = v
            elif isinstance(default, float):
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    kw[k] = float(v)
            elif isinstance(v, str):
                kw[k] = v
        cfg = cls(**kw)
        if cfg.layer not in ("background", "bottom"):
            cfg.layer = "bottom"
        return cfg
