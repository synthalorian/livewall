#!/usr/bin/env python3
"""neon-horizon: a slowly scrolling synthwave grid under a pulsing striped sun.

Palette comes from the theme's colors.toml. Seamless: the grid scrolls a whole
number of cell depths per loop, and every pulse/twinkle/stripe uses an integer
number of cycles per loop.

    python3 neon_horizon.py --colors .../colors.toml --out loop.mp4 [--size 1920x1080]
    python3 neon_horizon.py --colors ... --still poster.png --t 0.25
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Encoder, load_palette, render_parallel, smoothstep, static_dither  # noqa: E402

TAU = 2.0 * math.pi


class NeonHorizon:
    def __init__(self, w: int, h: int, pal: dict[str, np.ndarray], scroll_cells: int = 4):
        self.w, self.h, self.p = w, h, pal
        self.s = h / 1080.0
        self.scroll_cells = scroll_cells
        self.hy = 0.60 * h                                   # horizon row
        ys = np.arange(h, dtype=np.float32)[:, None]
        xs = np.arange(w, dtype=np.float32)[None, :]
        self.ys, self.xs = ys, xs
        self.dither = static_dither(h, w)
        self._build_static()

    # ------------------------------------------------------------------ static
    def _build_static(self):
        p, h, w = self.p, self.h, self.w
        ys, xs, hy = self.ys, self.xs, self.hy
        v = np.clip(ys / hy, 0, 1)[..., None]               # 0 top .. 1 horizon
        top, mid = p["darker_background"], p["dark_background"]
        low = 0.55 * p["selection"] + 0.45 * p["brown"]
        sky = np.where(v < 0.55, top + (mid - top) * (v / 0.55),
                       mid + (low - mid) * (np.clip(v - 0.55, 0, None) / 0.45) ** 1.6)
        self.sky = np.broadcast_to(sky, (h, w, 3)).astype(np.float32).copy()

        # stars: fixed positions, twinkle animated per frame
        rng = np.random.default_rng(11)
        n = int(260 * (w * h) / (1920 * 1080) ** 1 * 1.0)
        n = min(n, 900)
        sx = rng.uniform(0, w, n)
        sy = rng.uniform(0, hy * 0.8, n) ** 1.0
        sy = (rng.random(n) ** 1.6) * hy * 0.85
        self.stars = dict(x=sx, y=sy, b=rng.uniform(0.25, 1.0, n) * (1 - sy / hy),
                          f=rng.integers(1, 4, n), ph=rng.uniform(0, 1, n),
                          r=rng.uniform(0.6, 1.4, n) * self.s)

        # mountains: two silhouette layers made of incommensurate sines (static)
        x01 = xs[0] / w
        def ridge(seed, base, amp):
            r = np.random.default_rng(seed)
            y = np.zeros_like(x01)
            for k in range(1, 7):
                y += r.uniform(0.3, 1.0) / k * np.sin(TAU * (k * 1.7 * x01 + r.uniform()))
            y = (y - y.min()) / (y.max() - y.min())
            # keep the centre lower so the sun reads clearly
            centre = 1 - 0.75 * np.exp(-((x01 - 0.5) / 0.16) ** 2)
            return hy - (base + amp * y * centre) * h
        self.ridge_far = ridge(3, 0.015, 0.11)
        self.ridge_near = ridge(8, 0.004, 0.06)

        # floor base
        fv = np.clip((ys - hy) / (h - hy), 0, 1)[..., None]
        floor = p["darker_background"] * (1 - fv) + p["background"] * fv
        self.floor = np.broadcast_to(floor, (h, w, 3)).astype(np.float32).copy()

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _screen(base, col, a):
        """Screen-blend col with weight a (HxW) onto base."""
        add = col[None, None, :] * a[..., None]
        return 1 - (1 - base) * (1 - add)

    # ------------------------------------------------------------------- frame
    def frame(self, t: float) -> np.ndarray:
        """t in [0, 1): position in the loop."""
        p, w, h, s = self.p, self.w, self.h, self.s
        ys, xs, hy = self.ys, self.xs, self.hy
        img = self.sky.copy()

        # stars
        st = self.stars
        tw = 0.55 + 0.45 * np.sin(TAU * (st["f"] * t + st["ph"]))
        star_layer = np.zeros((h, w), np.float32)
        for x, y, b, r in zip(st["x"], st["y"], st["b"] * tw, st["r"]):
            x0, x1 = int(max(x - 4 * s, 0)), int(min(x + 4 * s + 1, w))
            y0, y1 = int(max(y - 4 * s, 0)), int(min(y + 4 * s + 1, h))
            gx = xs[0, x0:x1] - x
            gy = ys[y0:y1, 0][:, None] - y
            star_layer[y0:y1, x0:x1] += b * np.exp(-(gx ** 2 + gy ** 2) / (2 * r * r))
        img = self._screen(img, p["bright_foreground"] * 0.9 + p["bright_cyan"] * 0.1,
                           np.clip(star_layer, 0, 1))

        # sun: two slow pulses per loop
        pulse = 0.5 + 0.5 * math.sin(TAU * 2 * t - math.pi / 2)  # 0..1, starts low
        cx, cy, R = w / 2, hy - 0.20 * h, 0.215 * h
        d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        glow_r = R * (1.55 + 0.25 * pulse)
        glow = np.exp(-np.maximum(d - R, 0) ** 2 / (2 * (0.32 * glow_r) ** 2)) * (d > R * 0.98)
        glow = glow * (0.35 + 0.25 * pulse)
        img = self._screen(img, p["accent"], glow.astype(np.float32))
        haze = np.exp(-(d / (R * 3.2)) ** 2) * (0.10 + 0.06 * pulse)
        img = self._screen(img, p["magenta"] * 0.8, haze.astype(np.float32))

        sv = np.clip((ys - (cy - R)) / (2 * R), 0, 1)        # 0 top of sun .. 1 bottom
        sun_col = np.where(sv[..., None] < 0.45,
                           p["yellow"] + (p["orange"] - p["yellow"]) * (sv[..., None] / 0.45),
                           p["orange"] + (p["accent"] - p["orange"]) * ((sv[..., None] - 0.45) / 0.55))
        sun_col = sun_col * (0.92 + 0.10 * pulse)
        disc = np.clip(R - d + 0.75, 0, 1.5) / 1.5           # AA edge
        # stripes: lower part, scroll downward one stripe period per loop
        period = 0.11 * R * 2
        phase = (ys - cy - t * period) / period
        frac = phase - np.floor(phase)
        gap = 0.10 + np.clip((sv - 0.5) / 0.5, 0, 1) * 0.55       # gaps widen downward
        cut = np.clip((frac - (1 - gap)) * period / 1.2, 0, 1) * (sv > 0.5)
        cut = np.clip(cut * 1.0 + 0, 0, 1)
        sun_a = disc * (1 - cut)
        img = img * (1 - sun_a[..., None]) + np.broadcast_to(sun_col, img.shape) * sun_a[..., None]

        # mountains over the sun
        for ridge, col, rim, k in ((self.ridge_far, p["lighter_background"] * 0.75, p["magenta"], 0.35),
                                   (self.ridge_near, p["darker_background"], p["cyan"], 0.55)):
            m = np.clip(ys - ridge[None, :] + 0.5, 0, 1) * (ys < hy + 1)
            edge = np.exp(-((ys - ridge[None, :]) / (1.6 * s)) ** 2) * (ys < hy)
            img = img * (1 - m[..., None]) + col[None, None, :] * m[..., None]
            img = self._screen(img, rim * k, edge.astype(np.float32) * (0.5 + 0.2 * pulse))

        # floor
        below = ys >= hy
        img = np.where(below[..., None], self.floor, img)
        dy = np.maximum(ys - hy, 0.5) / h                    # normalized rows below horizon
        C = 0.50                                             # camera height (cells)
        z = C / dy                                           # depth in cells
        Z = z + t * self.scroll_cells                        # integer scroll per loop
        dZ = C / (dy * dy * h)                               # cells per pixel (rows)
        fz = np.abs(Z - np.round(Z))
        line_w = 1.1 * s
        hz_core = np.clip(1 - (fz / dZ) / line_w, 0, 1)
        hz_glow = np.exp(-((fz / dZ) / (5.5 * s)) ** 2)
        hz_fade = smoothstep(0.075, 0.02, dZ)      # kill moire near horizon
        X = (xs - w / 2) / h * z * 5.4 + 0.5
        dX = np.sqrt((z * 5.4 / h) ** 2 + ((xs - w / 2) / h * 5.4 * dZ) ** 2)  # |grad X| per px
        fx = np.abs(X - np.round(X))
        vx_core = np.clip(1 - (fx / dX) / line_w, 0, 1)
        vx_glow = np.exp(-((fx / dX) / (5.5 * s)) ** 2)
        vx_fade = smoothstep(0.12, 0.03, dX)
        depth_fog = smoothstep(0.0, 0.10, ys / h - hy / h)   # dim at the horizon
        near = 0.65 + 0.35 * smoothstep(hy, h, ys)
        core = np.maximum(hz_core * hz_fade, vx_core * vx_fade)
        glw = np.maximum(hz_glow * hz_fade, vx_glow * vx_fade)
        a_core = (core * (0.25 + 0.75 * depth_fog) * near) * below
        a_glow = (glw * 0.35 * (0.3 + 0.7 * depth_fog) * near) * below
        img = self._screen(img, p["cyan"] * 0.85 + p["magenta"] * 0.15, a_glow.astype(np.float32))
        img = self._screen(img, p["bright_cyan"], a_core.astype(np.float32))
        # horizon band + sun reflection on the floor
        band = np.exp(-(np.abs(ys - hy) / (0.010 * h)) ** 1.5) * (0.45 + 0.20 * pulse)
        img = self._screen(img, p["accent"], np.broadcast_to(band, (h, w)).astype(np.float32))
        haze2 = np.exp(-((ys - hy) / (0.045 * h)) ** 2) * (0.22 + 0.08 * pulse)
        img = self._screen(img, p["magenta"] * 0.7, np.broadcast_to(haze2, (h, w)).astype(np.float32))
        refl = (np.exp(-((xs - cx) / (0.55 * R)) ** 2) * np.exp(-(ys - hy) / (0.18 * h))
                * below * (0.16 + 0.08 * pulse))
        img = self._screen(img, p["accent"], refl.astype(np.float32))

        # vignette (static) + dither
        vig = 1 - 0.28 * (((xs / w - 0.5) * 1.6) ** 2 + ((ys / h - 0.5) * 1.3) ** 2)
        img = img * np.clip(vig, 0, 1)[..., None] + self.dither
        return np.clip(img, 0, 1).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colors", required=True, type=Path)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--still", type=Path)
    ap.add_argument("--t", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=None, help="render processes (4K needs ~2 GB each)")
    a = ap.parse_args()
    if not a.out and not a.still:
        ap.error("give --out (video loop) or --still (single image)")
    w, h = map(int, a.size.lower().split("x"))
    scene = NeonHorizon(w, h, load_palette(a.colors))
    if a.still:
        Image.fromarray((scene.frame(a.t) * 255 + 0.5).astype(np.uint8)).save(a.still)
        return
    n = int(round(a.fps * a.seconds))
    render_parallel(scene, n, Encoder(a.out, w, h, a.fps, crf=a.crf, frames=n), "neon-horizon", a.workers)


if __name__ == "__main__":
    main()
