"""The long-running supervisor: picks the scene, runs the player per output,
and pauses it on fullscreen / battery. Run by `livewall start` or systemd."""
from __future__ import annotations

import fcntl
import json
import os
import select
import signal
import socket
import time
from pathlib import Path

from livewall import backends, paths, scenes, system, theme
from livewall.config import Config

FULLSCREEN_EVENTS = (b"fullscreen>>", b"workspace>>", b"workspacev2>>", b"focusedmon>>",
                     b"activewindow>>", b"closewindow>>", b"movewindow>>", b"openwindow>>",
                     b"activespecial>>", b"changefloatingmode>>")
MONITOR_EVENTS = (b"monitoradded>>", b"monitorremoved>>", b"monitoraddedv2>>", b"monitorremovedv2>>")

STATIC = "static"   # value of the override file that forces the still background


def read_override() -> str | None:
    try:
        v = paths.override_file().read_text().strip()
    except OSError:
        return None
    return v or None


def resolve(cfg: Config, home: Path | None = None):
    """Decide what should be playing. Returns (scene|None, reason, ThemeInfo)."""
    th = theme.detect_theme(home)
    found = scenes.discover()
    ov = read_override()
    if ov == STATIC:
        return None, "static (set by `livewall set static`)", th
    if ov:
        sc = scenes.find(found, ov)
        if sc:
            return sc, f"set by `livewall set {ov}`", th
        return None, f"scene '{ov}' not found; static fallback", th
    sc, why = theme.pick_scene(th, found)
    if sc is None:
        return None, why + "; static fallback", th
    return sc, why, th


class Daemon:
    def __init__(self, cfg: Config | None = None, runner=system.default_runner,
                 battery=system.on_battery):
        self.cfg = cfg or Config.load()
        self.runner, self.battery = runner, battery
        self.backend: backends.Backend | None = None
        self.key = None
        self.scene = None
        self.reason = ""
        self.theme = None
        self.outs: list[system.Output] = []
        self.pause_reason: dict[str, str] = {}
        self.error = ""
        self.failures = 0
        self.player_started = 0.0
        self.running = True
        self.reload = True
        self.events: socket.socket | None = None
        self.started = time.time()

    # -------------------------------------------------------------- lifecycle
    def apply(self, force: bool = False) -> None:
        if self.reload:
            self.cfg = Config.load()
            self.reload = False
        scene, reason, th = resolve(self.cfg)
        self.theme, self.reason = th, reason
        self.outs = system.outputs(self.runner)
        bcls = backends.choose(scene, self.cfg.backend)
        if scene is not None and bcls is backends.StaticBackend:
            self.reason += ("; no usable player (install mpvpaper, or GStreamer's "
                            "gst-plugins-good plus gst-libav or gst-plugin-va), static fallback")
        key = (scene.id if scene else None, bcls.name,
               tuple((o.name, o.width, o.height) for o in self.outs), self.cfg.layer,
               self.cfg.resolution, self.cfg.mpv_options)
        if key == self.key and not force:
            return
        if key != self.key:
            self.error = ""       # a new scene/player gets a fresh chance
        self.stop_player()
        self.scene, self.key = scene, key
        self.backend = bcls(self.cfg)
        self.backend.start(scene, self.outs) if scene else None
        self.player_started = time.time()
        self.pause_reason = {}

    def stop_player(self) -> None:
        if self.backend:
            self.backend.stop()
        self.backend = None

    def check_alive(self) -> None:
        if not self.backend or self.backend.alive():
            # Only a player that has stayed up for a while clears the crash count;
            # otherwise one that dies every few seconds would be restarted forever.
            if self.backend and time.time() - self.player_started > 30:
                self.failures = 0
            return
        if self.backend.undecodable():
            self.error = (f"{self.backend.name} cannot decode this scene (missing GStreamer "
                          f"demuxer or decoder); static fallback; see {paths.log_file()}")
            self.stop_player()
            self.backend = backends.StaticBackend(self.cfg)
            return
        self.failures += 1
        if self.failures > 5:
            self.error = f"{self.backend.name} keeps exiting; see {paths.log_file()}"
            self.stop_player()
            self.backend = backends.StaticBackend(self.cfg)
            return
        time.sleep(min(2 ** self.failures, 10) * 0.25)
        self.apply(force=True)

    def update_pause(self) -> None:
        if not self.backend or self.backend.name == "static":
            return
        battery = self.cfg.pause_on_battery and self.battery()
        full = system.fullscreen_outputs(self.runner, self.outs) if self.cfg.pause_on_fullscreen else set()
        for out in list(self.backend.paused) or [backends.ALL]:
            why = "battery" if battery else ""
            if out in full or (out == backends.ALL and full):
                why = "fullscreen" if not why else why + "+fullscreen"
            self.backend.set_paused(out, bool(why))
            self.pause_reason[out] = why

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        b = self.backend
        outs = {}
        if b:
            for name in b.paused:
                o = next((x for x in self.outs if x.name == name), None)
                video = (self.scene.video_for(o.width if o else None, o.height if o else None,
                                              self.cfg.resolution) if self.scene else None)
                outs[name] = {"paused": b.paused.get(name, False),
                              "why": self.pause_reason.get(name, ""),
                              "video": str(video) if video else None}
        th = self.theme
        return {"pid": os.getpid(), "started": self.started,
                "scene": self.scene.id if self.scene else None,
                "reason": self.reason, "backend": b.name if b else None,
                "theme": th.name if th else None, "theme_source": th.source if th else None,
                "static_background": str(theme.static_background() or "") or None,
                "outputs": outs, "error": self.error}

    def write_state(self) -> None:
        f = paths.state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state(), indent=2))
        tmp.replace(f)

    # ----------------------------------------------------------------- events
    def connect_events(self) -> None:
        if self.events:
            return
        p = system.hypr_event_socket()
        if not p:
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(p))
            s.setblocking(False)
            self.events = s
        except OSError:
            self.events = None

    def wait(self, timeout: float) -> tuple[bool, bool]:
        """Block up to timeout. Returns (fullscreen_maybe_changed, monitors_changed)."""
        self.connect_events()
        if not self.events:
            time.sleep(timeout)
            return True, False
        try:
            r, _, _ = select.select([self.events], [], [], timeout)
        except (OSError, ValueError, InterruptedError):
            return True, False
        if not r:
            return False, False
        try:
            data = self.events.recv(65536)
        except BlockingIOError:
            return False, False
        except OSError:
            data = b""
        if not data:          # Hyprland went away
            self.events.close()
            self.events = None
            return True, True
        time.sleep(0.15)      # coalesce bursts (workspace switch = several events)
        try:
            data += self.events.recv(65536)
        except OSError:
            pass
        lines = data.splitlines()
        return (any(l.startswith(FULLSCREEN_EVENTS) for l in lines),
                any(l.startswith(MONITOR_EVENTS) for l in lines))

    # ------------------------------------------------------------------- main
    def run(self) -> int:
        paths.runtime_dir().mkdir(parents=True, exist_ok=True)
        lock = open(paths.pid_file(), "a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("livewall: another daemon is already running")
            return 1
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()

        def stop(*_):
            self.running = False

        def hup(*_):
            self.reload = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGHUP, hup)
        last_poll = 0.0
        try:
            self.apply()
            self.update_pause()
            self.write_state()
            while self.running:
                fs, mon = self.wait(1.0)
                if not self.running:
                    break
                now = time.monotonic()
                periodic = now - last_poll >= self.cfg.poll_interval
                if self.reload or mon or periodic:
                    last_poll = now
                    self.apply()
                    self.check_alive()
                if fs or periodic or mon:
                    self.update_pause()
                    self.write_state()
        finally:
            self.stop_player()
            paths.state_file().unlink(missing_ok=True)
            lock.seek(0)
            lock.truncate()
            lock.close()
            paths.pid_file().unlink(missing_ok=True)
        return 0
