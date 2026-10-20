"""Hyprland and power-supply probes. Everything takes an injectable runner or
root path so it can be tested without Hyprland or a battery."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from livewall import paths

Runner = Callable[[list[str]], str | None]


def default_runner(cmd: list[str]) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3, env=hypr_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# ------------------------------------------------------------------ Hyprland
def hypr_signature() -> str | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return sig
    # Under systemd the variable may be missing: take the newest instance.
    for base in (Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr",
                 Path("/tmp/hypr")):
        try:
            cands = [d for d in base.iterdir() if (d / ".socket.sock").exists()]
        except OSError:
            continue
        if cands:
            return max(cands, key=lambda d: d.stat().st_mtime).name
    return None


def hypr_env() -> dict:
    env = dict(os.environ)
    sig = hypr_signature()
    if sig:
        env["HYPRLAND_INSTANCE_SIGNATURE"] = sig
    return env


def hypr_event_socket() -> Path | None:
    sig = hypr_signature()
    if not sig:
        return None
    for base in (Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr",
                 Path("/tmp/hypr")):
        p = base / sig / ".socket2.sock"
        if p.exists():
            return p
    return None


@dataclass
class Output:
    name: str
    width: int
    height: int
    workspace: int | None = None
    special: int | None = None


def _json(runner: Runner, *args: str):
    out = runner(["hyprctl", "-j", *args])
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def outputs(runner: Runner = default_runner) -> list[Output]:
    mons = _json(runner, "monitors")
    if not isinstance(mons, list):
        return []
    res = []
    for m in mons:
        if not isinstance(m, dict) or m.get("disabled"):
            continue
        w, h = int(m.get("width", 0)), int(m.get("height", 0))
        if m.get("transform", 0) in (1, 3, 5, 7):
            w, h = h, w
        ws = (m.get("activeWorkspace") or {}).get("id")
        sp = (m.get("specialWorkspace") or {}).get("id") or None
        res.append(Output(str(m.get("name", "")), w, h, ws, sp))
    return res


def fullscreen_outputs(runner: Runner = default_runner, outs: list[Output] | None = None) -> set[str]:
    """Names of outputs whose visible workspace has a fullscreen window."""
    outs = outputs(runner) if outs is None else outs
    wss = _json(runner, "workspaces")
    if not isinstance(wss, list):
        return set()
    full = {w.get("id") for w in wss if isinstance(w, dict) and w.get("hasfullscreen")}
    return {o.name for o in outs if o.workspace in full or (o.special and o.special in full)}


# --------------------------------------------------------------------- power
def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def on_battery(root: Path | None = None) -> bool:
    """True when a system battery exists and no AC/USB supply is online."""
    root = root or paths.sysfs_power()
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return False
    batteries, supplies = [], []
    for e in entries:
        kind = _read(e / "type")
        if kind == "Battery":
            if _read(e / "scope") != "Device":       # skip mice, headsets, pens
                batteries.append(e)
        elif kind:
            supplies.append(e)
    if not batteries:
        return False
    if any(_read(s / "online") == "1" for s in supplies):
        return False
    if supplies:
        return True
    return any(_read(b / "status") == "Discharging" for b in batteries)
