"""Players that put a scene on the wallpaper layer.

mpvpaper  - preferred. libmpv with hardware decoding plays an H.264/AV1 loop
            for a few % of one core; pausing holds the current frame.
gtk       - fallback: renderer/livewall_gtk.py (GTK4 + gtk4-layer-shell,
            GStreamer for video, or a frame sequence).
swww      - for packs that ship an animated GIF; swww cannot pause a GIF, so
            "pause" swaps in the poster still.
static    - draws nothing and leaves the Omarchy background in place.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from livewall import paths
from livewall.scenes import Scene
from livewall.system import Output

ALL = "ALL"
EXIT_UNDECODABLE = 3    # renderer/livewall_gtk.py: GStreamer cannot play the video


def _pdeathsig():
    """Children die with the daemon even if it is SIGKILLed."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


def _log():
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    return open(paths.log_file(), "ab", buffering=0)


class Backend:
    name = "base"

    def __init__(self, cfg):
        self.cfg = cfg
        self.procs: dict[str, subprocess.Popen] = {}
        self.paused: dict[str, bool] = {}

    @classmethod
    def available(cls) -> bool:
        return False

    @classmethod
    def supports(cls, scene: Scene) -> bool:
        return False

    def targets(self, outs: list[Output]) -> list[Output]:
        return outs or [Output(ALL, 0, 0)]

    def start(self, scene: Scene, outs: list[Output]) -> None:
        raise NotImplementedError

    def set_paused(self, output: str, paused: bool) -> None:
        self.paused[output] = paused

    def alive(self) -> bool:
        return bool(self.procs) and all(p.poll() is None for p in self.procs.values())

    def undecodable(self) -> bool:
        """A player exited saying it cannot decode the scene; retrying won't help."""
        return any(p.poll() == EXIT_UNDECODABLE for p in self.procs.values())

    def stop(self) -> None:
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        deadline = time.monotonic() + 3
        for p in self.procs.values():
            try:
                p.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        self.procs.clear()
        self.paused.clear()

    def _spawn(self, key: str, cmd: list[str], env: dict | None = None) -> None:
        log = _log()
        log.write(("$ " + " ".join(cmd) + "\n").encode())
        self.procs[key] = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           env=env, preexec_fn=_pdeathsig)
        log.close()
        self.paused[key] = False


class MpvpaperBackend(Backend):
    name = "mpvpaper"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("mpvpaper") is not None

    @classmethod
    def supports(cls, scene: Scene) -> bool:
        return bool(scene.videos)

    def socket_for(self, output: str) -> Path:
        return paths.runtime_dir() / f"mpv-{output}.sock"

    def start(self, scene: Scene, outs: list[Output]) -> None:
        paths.runtime_dir().mkdir(parents=True, exist_ok=True)
        for o in self.targets(outs):
            video = scene.video_for(o.width or None, o.height or None, self.cfg.resolution)
            sock = self.socket_for(o.name)
            sock.unlink(missing_ok=True)
            opts = ["no-audio", "loop-file=inf", "hwdec=auto-safe", "panscan=1.0",
                    "osc=no", "osd-level=0", "input-default-bindings=no",
                    f"input-ipc-server={sock}"]
            if self.cfg.mpv_options:
                opts.append(self.cfg.mpv_options)
            self._spawn(o.name, ["mpvpaper", "-l", self.cfg.layer, "-o", " ".join(opts),
                                 o.name, str(video)])

    def ipc(self, output: str, command: list, timeout: float = 1.0) -> dict | None:
        """One JSON IPC request to the output's mpv. Returns the reply or None."""
        sock = self.socket_for(output)
        deadline = time.monotonic() + timeout
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect(str(sock))
                    s.sendall((json.dumps({"command": command}) + "\n").encode())
                    buf = b""
                    while True:
                        for line in buf.split(b"\n")[:-1]:
                            msg = json.loads(line)
                            if "error" in msg:       # replies carry "error"; events don't
                                return msg
                        buf = buf[buf.rfind(b"\n") + 1:] if b"\n" in buf else buf
                        chunk = s.recv(4096)
                        if not chunk:
                            return None
                        buf += chunk
            except (OSError, json.JSONDecodeError):
                if time.monotonic() > deadline:
                    return None
                time.sleep(0.1)

    def set_paused(self, output: str, paused: bool) -> None:
        if self.paused.get(output) == paused:
            return
        r = self.ipc(output, ["set_property", "pause", paused])
        if r is not None and r.get("error") == "success":
            self.paused[output] = paused

    def stop(self) -> None:
        super().stop()
        for f in paths.runtime_dir().glob("mpv-*.sock"):
            f.unlink(missing_ok=True)


def _gtk_layer_shell_lib() -> str | None:
    for d in ("/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/lib/x86_64-linux-gnu"):
        p = Path(d) / "libgtk4-layer-shell.so"
        if p.exists():
            return str(p)
    return None


class GtkBackend(Backend):
    """renderer/livewall_gtk.py, one process per output. SIGUSR1 pauses,
    SIGUSR2 resumes."""
    name = "gtk"
    _avail: bool | None = None
    _decodable: dict[str, bool] = {}

    @staticmethod
    def renderer() -> Path:
        return paths.SRC_ROOT / "renderer" / "livewall_gtk.py"

    @classmethod
    def available(cls) -> bool:
        if cls._avail is None:
            if not cls.renderer().is_file() or not _gtk_layer_shell_lib():
                cls._avail = False
            else:
                code = ("import gi; gi.require_version('Gtk','4.0'); "
                        "gi.require_version('Gtk4LayerShell','1.0'); "
                        "from gi.repository import Gtk, Gtk4LayerShell")
                try:
                    cls._avail = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                                timeout=10).returncode == 0
                except (OSError, subprocess.SubprocessError):
                    cls._avail = False
        return cls._avail

    @classmethod
    def can_decode(cls, video: Path) -> bool:
        """GStreamer can demux and decode this file (gst-discoverer, via the
        renderer's --probe). GTK and layer-shell alone don't prove that: without
        qtdemux and an H.264 decoder GtkMediaFile shows a flat grey panel."""
        key = str(video)
        if key not in cls._decodable:
            try:
                r = subprocess.run([sys.executable, str(cls.renderer()), "--probe", key],
                                   capture_output=True, text=True, timeout=15)
                ok = r.returncode == 0
                if not ok:
                    with _log() as log:
                        log.write((r.stderr or f"probe failed: {key}\n").encode())
            except (OSError, subprocess.SubprocessError):
                ok = False
            cls._decodable[key] = ok
        return cls._decodable[key]

    @classmethod
    def playable_videos(cls, scene: Scene) -> dict[str, Path]:
        return {k: v for k, v in scene.videos.items() if cls.can_decode(v)}

    @classmethod
    def supports(cls, scene: Scene) -> bool:
        return bool(scene.frames or (scene.videos and cls.playable_videos(scene)))

    def start(self, scene: Scene, outs: list[Output]) -> None:
        playable = self.playable_videos(scene) if scene.videos else {}
        env = dict(os.environ)
        lib = _gtk_layer_shell_lib()
        if lib:   # gtk4-layer-shell must load before libwayland-client
            env["LD_PRELOAD"] = ":".join(filter(None, [lib, env.get("LD_PRELOAD")]))
        for o in self.targets(outs):
            cmd = [sys.executable, str(self.renderer()), "--layer", self.cfg.layer,
                   "--fps", str(scene.fps)]
            if o.name != ALL:
                cmd += ["--output", o.name]
            video = scene.video_for(o.width or None, o.height or None, self.cfg.resolution)
            if video is not None and str(video) not in map(str, playable.values()):
                video = next(iter(playable.values()), None)   # e.g. 1080p decodes, 2160p doesn't
            if video:
                cmd += ["--video", str(video)]
            else:
                cmd += ["--frames", *map(str, scene.frames)]
            self._spawn(o.name, cmd, env)

    def set_paused(self, output: str, paused: bool) -> None:
        p = self.procs.get(output)
        if p and p.poll() is None and self.paused.get(output) != paused:
            p.send_signal(signal.SIGUSR1 if paused else signal.SIGUSR2)
            self.paused[output] = paused


class SwwwBackend(Backend):
    name = "swww"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.scene: Scene | None = None

    @classmethod
    def available(cls) -> bool:
        if not shutil.which("swww"):
            return False
        try:
            return subprocess.run(["swww", "query"], capture_output=True, timeout=3).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @classmethod
    def supports(cls, scene: Scene) -> bool:
        return scene.gif is not None

    def _img(self, output: str, img: Path) -> None:
        cmd = ["swww", "img", "--transition-type", "none"]
        if output != ALL:
            cmd += ["-o", output]
        subprocess.run(cmd + [str(img)], capture_output=True, timeout=10)

    def start(self, scene: Scene, outs: list[Output]) -> None:
        self.scene = scene
        for o in self.targets(outs):
            self._img(o.name, scene.gif)
            self.paused[o.name] = False

    def alive(self) -> bool:
        return True

    def set_paused(self, output: str, paused: bool) -> None:
        if self.paused.get(output) == paused or not self.scene or not self.scene.poster:
            return
        self._img(output, self.scene.poster if paused else self.scene.gif)
        self.paused[output] = paused

    def stop(self) -> None:
        from livewall.theme import static_background
        bg = static_background()
        if bg and self.scene:
            for o in list(self.paused) or [ALL]:
                self._img(o, bg)
        self.paused.clear()
        self.scene = None


class StaticBackend(Backend):
    """Draws nothing: whatever Omarchy shows (swaybg / omarchy-shell) stays."""
    name = "static"

    @classmethod
    def available(cls) -> bool:
        return True

    @classmethod
    def supports(cls, scene: Scene) -> bool:
        return True

    def start(self, scene, outs) -> None:
        pass

    def alive(self) -> bool:
        return True

    def stop(self) -> None:
        pass


BACKENDS = {b.name: b for b in (MpvpaperBackend, GtkBackend, SwwwBackend, StaticBackend)}
ORDER = (MpvpaperBackend, GtkBackend, SwwwBackend)


def choose(scene: Scene | None, wanted: str = "auto") -> type[Backend]:
    """The first available backend that can play the scene, else static."""
    if scene is None:
        return StaticBackend
    if wanted != "auto" and wanted in BACKENDS:
        b = BACKENDS[wanted]
        return b if (b is StaticBackend or (b.available() and b.supports(scene))) else StaticBackend
    for b in ORDER:
        if b.supports(scene) and b.available():
            return b
    return StaticBackend
