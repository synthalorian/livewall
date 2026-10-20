"""livewall start|stop|status|set <scene>|list"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from livewall import __version__, backends, paths, scenes, system, theme
from livewall.config import DEFAULT_CONFIG, Config
from livewall.daemon import STATIC, Daemon, read_override, resolve

UNIT = "livewall.service"


# ----------------------------------------------------------------- helpers
def daemon_pid() -> int | None:
    try:
        pid = int(paths.pid_file().read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read()
        if b"livewall" not in cmd:
            return None
    except OSError:
        pass
    return pid


def _systemctl(*args: str) -> subprocess.CompletedProcess | None:
    if os.environ.get("LIVEWALL_NO_SYSTEMD") or not shutil.which("systemctl"):
        return None
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def unit_installed() -> bool:
    r = _systemctl("cat", UNIT)
    return bool(r and r.returncode == 0)


def unit_active() -> bool:
    r = _systemctl("is-active", UNIT)
    return bool(r and r.stdout.strip() in ("active", "activating", "reloading"))


def read_state() -> dict | None:
    try:
        return json.loads(paths.state_file().read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _wait(pred, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


# ---------------------------------------------------------------- commands
def cmd_start(a) -> int:
    pid = daemon_pid()
    if pid:
        print(f"livewall is already running (pid {pid})")
        return 0
    if not a.no_systemd and unit_installed():
        r = _systemctl("start", UNIT)
        if not r or r.returncode != 0:
            print(f"livewall: systemctl --user start {UNIT} failed: {(r.stderr if r else '').strip()}",
                  file=sys.stderr)
            return 1
        _wait(lambda: read_state() is not None, 5)
        print("livewall started (systemd user unit)")
        return _brief()
    if a.foreground:
        return Daemon().run()
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    log = open(paths.log_file(), "ab")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(paths.SRC_ROOT), env.get("PYTHONPATH")]))
    subprocess.Popen([sys.executable, "-m", "livewall", "daemon"], stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, env=env, start_new_session=True, cwd=str(paths.SRC_ROOT))
    if not _wait(lambda: read_state() is not None, 6):
        print(f"livewall: daemon did not come up; see {paths.log_file()}", file=sys.stderr)
        return 1
    print(f"livewall started (pid {daemon_pid()})")
    return _brief()


def _brief() -> int:
    st = read_state()
    if st:
        print(f"  scene:   {st['scene'] or 'none (static background)'}  [{st['reason']}]")
        print(f"  backend: {st['backend']}")
    return 0


def cmd_stop(a) -> int:
    if unit_active():
        r = _systemctl("stop", UNIT)
        ok = bool(r and r.returncode == 0)
        print("livewall stopped (systemd user unit)" if ok else "livewall: systemctl stop failed")
        return 0 if ok else 1
    pid = daemon_pid()
    if not pid:
        print("livewall is not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        if not _wait(lambda: daemon_pid() is None, 6):
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass                                       # it exited on its own meanwhile
    paths.state_file().unlink(missing_ok=True)
    print("livewall stopped")
    return 0


def cmd_status(a) -> int:
    pid = daemon_pid()
    st = read_state() if pid else None
    if a.json:
        if st is None:
            sc, reason, th = resolve(Config.load())
            st = {"running": False, "scene": sc.id if sc else None, "reason": reason,
                  "theme": th.name, "theme_source": th.source}
        else:
            st["running"] = True
        print(json.dumps(st, indent=2))
        return 0 if pid else 3
    if not pid:
        sc, reason, th = resolve(Config.load())
        print("livewall: stopped")
        print(f"  theme:   {th.name or 'unknown'}  ({th.source})")
        print(f"  would play: {sc.id if sc else 'nothing (static background)'}  [{reason}]")
        bk = backends.choose(sc, Config.load().backend).name if sc else "static"
        print(f"  backend: {bk}")
        return 3                                   # LSB "not running"
    print(f"livewall: running (pid {pid})")
    if st:
        print(f"  theme:   {st.get('theme') or 'unknown'}  ({st.get('theme_source')})")
        print(f"  scene:   {st.get('scene') or 'none (static background)'}  [{st.get('reason')}]")
        print(f"  backend: {st.get('backend')}")
        for name, o in (st.get("outputs") or {}).items():
            state = f"paused ({o['why']})" if o.get("paused") else "playing"
            print(f"  output {name}: {state}  {o.get('video') or ''}")
        if st.get("error"):
            print(f"  error:   {st['error']}")
    return 0


def cmd_list(a) -> int:
    errs: list[str] = []
    found = scenes.discover(errors=errs)
    th = theme.detect_theme()
    auto, _ = theme.pick_scene(th, found)
    ov = read_override()
    cur = None
    if ov and ov != STATIC:
        cur = scenes.find(found, ov)
    elif not ov:
        cur = auto
    if not found:
        print("no scenes installed")
    for s in found:
        mark = "*" if cur and s.id == cur.id else " "
        sizes = ",".join(k for k in s.videos if k != "default") or s.kind
        print(f"{mark} {s.id:<28} {s.title:<22} theme={','.join(s.themes):<18} "
              f"{s.fps:g}fps {sizes:<20} {s.source}")
    print(f"\ntheme: {th.name or 'unknown'}   mode: {('set ' + ov) if ov else 'auto (follow theme)'}")
    for e in errs:
        print(f"skipped: {e}", file=sys.stderr)
    return 0


def cmd_set(a) -> int:
    key = a.scene.strip()
    f = paths.override_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    if key in ("auto", "theme"):
        f.unlink(missing_ok=True)
        msg = "following the Omarchy theme again"
    elif key in (STATIC, "none", "off"):
        f.write_text(STATIC + "\n")
        msg = "static background (animation off)"
    else:
        sc = scenes.find(scenes.discover(), key)
        if not sc:
            print(f"livewall: unknown scene '{key}' (see `livewall list`)", file=sys.stderr)
            return 2
        f.write_text(sc.id + "\n")
        msg = f"scene set to {sc.id}"
    pid = daemon_pid()
    if pid:
        os.kill(pid, signal.SIGHUP)
    print(f"livewall: {msg}" + ("" if pid else " (takes effect on `livewall start`)"))
    return 0


def cmd_daemon(a) -> int:
    return Daemon().run()


def cmd_config(a) -> int:
    f = paths.config_file()
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(DEFAULT_CONFIG)
    print(f)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="livewall", description="Animated, theme-matched wallpapers for Hyprland/Omarchy.")
    ap.add_argument("--version", action="version", version=f"livewall {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start", help="start the wallpaper daemon")
    p.add_argument("--foreground", "-f", action="store_true", help="run in this terminal")
    p.add_argument("--no-systemd", action="store_true", help="do not use the systemd user unit")
    p.set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="stop it; the static background shows again").set_defaults(fn=cmd_stop)
    p = sub.add_parser("status", help="what is playing and why")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("set", help="pick a scene: <scene> | auto | static")
    p.add_argument("scene")
    p.set_defaults(fn=cmd_set)
    sub.add_parser("list", help="list installed scenes").set_defaults(fn=cmd_list)
    sub.add_parser("daemon", help="run the daemon in the foreground (systemd uses this)").set_defaults(fn=cmd_daemon)
    sub.add_parser("config", help="create/print the config file path").set_defaults(fn=cmd_config)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except KeyboardInterrupt:
        return 130
