"""Building blocks for the preset generators (everything except neon_horizon.py).

The seamless-loop rule from common.py still holds: frame i is rendered at
t = i / N, and anything that moves completes a whole number of cycles per loop.
The helpers here are built so that is easy to keep:

  * tile_noise() is periodic, so scrolling it by whole tiles per loop wraps;
  * loop_mix() blends two noise fields with cos/sin of 2*pi*n*t, which morphs a
    pattern in place, returns to the start, and keeps its contrast constant;
  * particles use age = frac(k * t + phase) with integer k.

Each preset script defines a scene class with frame(t) -> HxWx3 float32 in 0..1
and calls run(), which gives it the same command line as neon_horizon.py:

    python3 generators/aurora.py --out scenes/aurora/loop-1080p.mp4
    python3 generators/aurora.py --still scenes/aurora/poster.jpg --t 0.3
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from common import Encoder, hex_rgb, render_parallel, smoothstep, static_dither  # noqa: F401

TAU = 2.0 * math.pi


def palette(colors: dict[str, str]) -> dict[str, np.ndarray]:
    return {k: hex_rgb(v) for k, v in colors.items()}


def coords(w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre row (Hx1) and column (1xW) coordinates."""
    return (np.arange(h, dtype=np.float32)[:, None] + 0.5,
            np.arange(w, dtype=np.float32)[None, :] + 0.5)


def ramp(v: np.ndarray, stops) -> np.ndarray:
    """Map v (any shape, 0..1) through colour stops [(pos, rgb), ...]."""
    pos = np.array([p for p, _ in stops], np.float32)
    cols = np.stack([c for _, c in stops]).astype(np.float32)
    v = np.asarray(v, np.float32)
    return np.stack([np.interp(v, pos, cols[:, i]) for i in range(3)], axis=-1).astype(np.float32)


def vgradient(w: int, h: int, stops) -> np.ndarray:
    col = ramp((np.arange(h, dtype=np.float32) + 0.5) / h, stops)
    return np.ascontiguousarray(np.broadcast_to(col[:, None, :], (h, w, 3)))


def screen(base: np.ndarray, col, a: np.ndarray) -> np.ndarray:
    """Screen-blend col (rgb or HxWx3) with weight a (HxW) onto base."""
    return 1 - (1 - base) * (1 - np.asarray(col, np.float32) * a[..., None])


def over(base: np.ndarray, col, a: np.ndarray) -> np.ndarray:
    """Alpha-blend col over base with coverage a (HxW)."""
    a = a[..., None]
    return base * (1 - a) + np.asarray(col, np.float32) * a


def tile_noise(h: int, w: int, beta: float = 2.0, seed: int = 0,
               sx: float = 1.0, sy: float = 1.0, cut: float = 0.0) -> np.ndarray:
    """Periodic 1/f^beta noise (zero mean, unit std). sx/sy stretch the spectrum
    (sx > sy gives horizontal streaks); `cut` removes frequencies below it."""
    rng = np.random.default_rng(seed)
    fy = np.fft.fftfreq(h)[:, None] * sy
    fx = np.fft.rfftfreq(w)[None, :] * sx
    f = np.sqrt(fx * fx + fy * fy)
    f[0, 0] = 1.0
    amp = f ** (-beta / 2.0)
    amp[0, 0] = 0.0
    if cut:
        amp *= f > cut
    spec = amp * np.exp(1j * rng.uniform(0, TAU, f.shape))
    n = np.fft.irfft2(spec, s=(h, w)).astype(np.float32)
    return (n - n.mean()) / (n.std() + 1e-8)


def loop_mix(a: np.ndarray, b: np.ndarray, t: float, n: int = 1, phase: float = 0.0) -> np.ndarray:
    """A pattern that morphs and comes back after the loop: a*cos + b*sin."""
    ang = TAU * (n * t + phase)
    return a * math.cos(ang) + b * math.sin(ang)


def roll(img: np.ndarray, dy: float = 0.0, dx: float = 0.0) -> np.ndarray:
    """Shift a periodic field by a fractional number of pixels (bilinear)."""
    out = img
    if dy:
        i, f = int(math.floor(dy)), dy - math.floor(dy)
        out = (1 - f) * np.roll(out, i, axis=0) + f * np.roll(out, i + 1, axis=0)
    if dx:
        i, f = int(math.floor(dx)), dx - math.floor(dx)
        out = (1 - f) * np.roll(out, i, axis=1) + f * np.roll(out, i + 1, axis=1)
    return out


def resize(img: np.ndarray, w: int, h: int, smooth: bool = True) -> np.ndarray:
    """Resize a float HxW or HxWxC array."""
    mode = Image.BICUBIC if smooth else Image.BILINEAR
    if img.ndim == 2:
        return np.asarray(Image.fromarray(np.ascontiguousarray(img, np.float32), "F").resize((w, h), mode))
    return np.stack([resize(img[..., c], w, h, smooth) for c in range(img.shape[2])], axis=-1)


def blur(img: np.ndarray, sigma: float, pad_mode: str = "constant") -> np.ndarray:
    """Gaussian blur (HxW or HxWxC), done in the frequency domain. Zero padding
    suits glows; pad_mode="edge" suits blurring a whole picture."""
    if sigma <= 0:
        return img
    pad = int(3 * sigma) + 1
    h, w = img.shape[:2]
    spec_pad = ((pad, pad), (pad, pad)) + ((0, 0),) * (img.ndim - 2)
    p = np.pad(img, spec_pad, mode=pad_mode)
    H, W = p.shape[:2]
    fy = np.fft.fftfreq(H)[:, None]
    fx = np.fft.rfftfreq(W)[None, :]
    g = np.exp(-2 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    if img.ndim == 3:
        g = g[..., None]
    out = np.fft.irfft2(np.fft.rfft2(p, axes=(0, 1)) * g, s=(H, W), axes=(0, 1))
    return out[pad:pad + h, pad:pad + w].astype(np.float32)


def glow(layer: np.ndarray, sigma: float, down: int = 4, pad_mode: str = "constant") -> np.ndarray:
    """Cheap wide blur: shrink, blur, grow back."""
    h, w = layer.shape[:2]
    small = resize(layer, max(1, w // down), max(1, h // down), smooth=False)
    return np.clip(resize(blur(small, sigma / down, pad_mode), w, h), 0, None)


class Canvas:
    """A supersampled greyscale canvas for PIL drawing; get() gives HxW floats 0..1."""

    def __init__(self, w: int, h: int, ss: int = 2):
        self.w, self.h, self.ss = w, h, ss
        self.im = Image.new("L", (w * ss, h * ss), 0)
        self.d = ImageDraw.Draw(self.im)

    def line(self, pts, value: float, width: float):
        s = self.ss
        self.d.line([(x * s, y * s) for x, y in pts], fill=int(255 * min(max(value, 0), 1)),
                    width=max(1, int(round(width * s))), joint="curve")

    def polygon(self, pts, value: float = 1.0):
        s = self.ss
        self.d.polygon([(x * s, y * s) for x, y in pts], fill=int(255 * min(max(value, 0), 1)))

    def ellipse(self, cx, cy, rx, ry, value: float = 1.0):
        s = self.ss
        self.d.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
                       fill=int(255 * min(max(value, 0), 1)))

    def rect(self, x0, y0, x1, y1, value: float = 1.0):
        s = self.ss
        self.d.rectangle([x0 * s, y0 * s, max(x1 * s - 1, x0 * s), max(y1 * s - 1, y0 * s)],
                         fill=int(255 * min(max(value, 0), 1)))

    def get(self) -> np.ndarray:
        im = self.im.reduce(self.ss) if self.ss > 1 else self.im
        return np.asarray(im, np.float32) / 255.0


class Stars:
    """Fixed stars in a few twinkle groups. Each group's brightness is a sine with
    a whole number of cycles per loop, so a frame costs a handful of multiply-adds."""

    def __init__(self, w: int, h: int, n: int, seed: int = 1, top: float = 0.0, bottom: float = 1.0,
                 groups: int = 5, size: float = 1.0, bias: float = 1.6):
        rng = np.random.default_rng(seed)
        s = h / 1080.0
        self.layers = np.zeros((groups, h, w), np.float32)
        self.freq = rng.integers(1, 4, groups)
        self.phase = rng.uniform(0, 1, groups)
        ys, xs = coords(w, h)
        for _ in range(n):
            x = rng.uniform(0, w)
            v = rng.random() ** bias
            y = (top + (bottom - top) * v) * h
            b = rng.uniform(0.2, 1.0) ** 1.5
            r = rng.uniform(0.55, 1.25) * s * size * (1.6 if rng.random() < 0.04 else 1.0)
            g = rng.integers(groups)
            x0, x1 = int(max(x - 5 * r - 1, 0)), int(min(x + 5 * r + 2, w))
            y0, y1 = int(max(y - 5 * r - 1, 0)), int(min(y + 5 * r + 2, h))
            if x1 <= x0 or y1 <= y0:
                continue
            gx = xs[0, x0:x1] - x
            gy = ys[y0:y1, 0][:, None] - y
            self.layers[g, y0:y1, x0:x1] += b * np.exp(-(gx ** 2 + gy ** 2) / (2 * r * r))

    def at(self, t: float, depth: float = 0.45) -> np.ndarray:
        k = 1 - depth + depth * np.sin(TAU * (self.freq * t + self.phase))
        return np.clip(np.tensordot(k.astype(np.float32), self.layers, axes=1), 0, 1)


# x264 settings for the presets. A loop has one keyframe, and the seam is where
# the last P-frame meets it, so the two must look alike. mbtree and psy-rd make
# quality drift along the GOP, so both are off. A high ipratio makes the
# keyframe at least as clean as the P-frames; otherwise the first P-frames
# "repair" static areas and the seam shows the difference.
LOOP_X264 = "aq-mode=3:ipratio=4.0:mbtree=0:psy=0:deblock=-1,-1"


def loop_zones(n: int) -> str:
    """Raise quality over the last ~1 s. Slow, low-contrast change can sit in the
    quantizer's dead zone, so P-frames lag behind the picture and the lag would
    all land at the wrap. With more bits at the end, they catch up first. (The
    VBV cap must leave room for this, so keep maxrate generous.)"""
    span = max(4, n // 8) // 4 * 4
    q, s0 = span // 4, n - span
    return "/".join(f"{s0 + i * q},{s0 + (i + 1) * q - 1},b={b}" for i, b in enumerate((1.2, 1.5, 2.0, 2.5)))


def run(make, name: str, fps: int = 24, seconds: float = 8.0, crf: int = 26,
        maxrate: str = "2000k", doc: str | None = None):
    """Command line shared by the preset generators. make(w, h) builds the scene."""
    ap = argparse.ArgumentParser(description=doc)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=fps)
    ap.add_argument("--seconds", type=float, default=seconds,
                    help="loop length; keep the default, the motion is tuned to it")
    ap.add_argument("--crf", type=int, default=crf)
    ap.add_argument("--maxrate", default=maxrate, help="bitrate cap, e.g. 1200k")
    ap.add_argument("--out", type=Path, help="write the video loop here")
    ap.add_argument("--still", type=Path, help="write one frame (.jpg posters are 1280 wide)")
    ap.add_argument("--t", type=float, default=0.0, help="loop position for --still, 0..1")
    ap.add_argument("--poster-width", type=int, default=1280)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    if not a.out and not a.still:
        ap.error("give --out (video loop) or --still (single image)")
    w, h = map(int, a.size.lower().split("x"))
    scene = make(w, h)
    if a.still:
        img = Image.fromarray((np.clip(scene.frame(a.t % 1.0), 0, 1) * 255 + 0.5).astype(np.uint8))
        a.still.parent.mkdir(parents=True, exist_ok=True)
        if a.still.suffix.lower() in (".jpg", ".jpeg"):
            if img.width > a.poster_width:
                img = img.resize((a.poster_width, round(img.height * a.poster_width / img.width)),
                                 Image.LANCZOS)
            img.save(a.still, quality=84, optimize=True, progressive=True)
        else:
            img.save(a.still)
        return
    n = int(round(a.fps * a.seconds))
    maxrate = None if a.maxrate in ("", "0", "none") else a.maxrate
    enc = Encoder(a.out, w, h, a.fps, crf=a.crf, frames=n, maxrate=maxrate, tune=None,
                  x264=f"{LOOP_X264}:zones={loop_zones(n)}")
    render_parallel(scene, n, enc, name, a.workers)
