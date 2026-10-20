"""Shared helpers for the procedural scene generators.

Every generator renders frame i at t = i / N for i in [0, N), so frame N would
equal frame 0 exactly and the clip wraps without a visible jump. Anything that
moves must complete a whole number of cycles over the loop.
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import numpy as np


def hex_rgb(value: str) -> np.ndarray:
    value = value.strip().lstrip("#")
    return np.array([int(value[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def load_palette(colors_toml: Path) -> dict[str, np.ndarray]:
    data = tomllib.loads(Path(colors_toml).read_text())
    return {k: hex_rgb(v) for k, v in data.items()
            if isinstance(v, str) and v.startswith("#") and len(v) == 7}


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def static_dither(h: int, w: int, seed: int = 7) -> np.ndarray:
    """A fixed (not per-frame) dither field, so gradients do not band and the
    encoder does not have to chase changing noise."""
    rng = np.random.default_rng(seed)
    return ((rng.random((h, w, 1), dtype=np.float32) - 0.5) / 255.0)


def default_threads() -> int:
    """Threads for ffmpeg and render processes. Kept small on purpose: these
    tools run on shared machines. Override with LIVEWALL_THREADS."""
    try:
        return max(1, int(os.environ.get("LIVEWALL_THREADS", "2")))
    except ValueError:
        return 2


class Encoder:
    """Pipe raw RGB24 frames into ffmpeg and write an H.264 loop."""

    def __init__(self, out: Path, w: int, h: int, fps: int, crf: int = 20,
                 preset: str = "slow", frames: int = 240, threads: int | None = None,
                 maxrate: str | None = None, tune: str | None = "film",
                 x264: str = "aq-mode=3:ipratio=1.0"):
        out.parent.mkdir(parents=True, exist_ok=True)
        # maxrate caps the bitrate (VBV) so a busy scene cannot blow up the file size.
        # The buffer is large so the single keyframe is not starved: a starved
        # keyframe looks different from the last frame, and the seam shows.
        vbv = []
        if maxrate:
            kbps = int(maxrate.rstrip("kK"))
            vbv = ["-maxrate", f"{kbps}k", "-bufsize", f"{8 * kbps}k"]
        tune_args = ["-tune", tune] if tune else []
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-threads", str(threads or default_threads()),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264", "-threads", str(threads or default_threads()),
            "-preset", preset, "-crf", str(crf), *vbv,
            *tune_args, "-x264-params", x264,
            "-pix_fmt", "yuv420p", "-g", str(frames), "-keyint_min", str(frames),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-movflags", "+faststart", "-an", str(out),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        """frame: float32 HxWx3 in 0..1 (dither already applied)."""
        data = np.clip(frame * 255.0 + 0.5, 0, 255).astype(np.uint8)
        self.proc.stdin.write(data.tobytes())

    def close(self) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")


_SCENE = None


def _init(scene):
    global _SCENE
    _SCENE = scene


def _render(t):
    return np.clip(_SCENE.frame(t) * 255.0 + 0.5, 0, 255).astype(np.uint8).tobytes()


def render_parallel(scene, n: int, enc: "Encoder", label: str, workers: int | None = None):
    """Render frames t = i/n (i < n) in a process pool and feed them in order."""
    import multiprocessing as mp
    workers = workers or default_threads()
    ctx = mp.get_context("fork")
    with ctx.Pool(workers, initializer=_init, initargs=(scene,)) as pool:
        for i, buf in enumerate(pool.imap(_render, [i / n for i in range(n)], chunksize=2)):
            enc.proc.stdin.write(buf)
            if i % 30 == 0:
                print(f"{label}: frame {i}/{n}", flush=True)
    enc.close()
