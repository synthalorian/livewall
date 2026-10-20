#!/usr/bin/env python3
"""sunset-drive: a flight down a valley of wireframe mountains toward a low sun,
in the Catppuccin Mocha palette.

The terrain is a height field that repeats every D grid rows, and the camera
moves exactly D rows per loop, so the last frame flows into the first. Rows
are drawn far to near and each row's ground is filled before its lines, so
nearer ridges hide the ones behind them. Far rows fade into the haze instead
of popping in.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import TAU, Stars, coords, glow, palette, ramp, run, smoothstep, static_dither  # noqa: E402

P = palette({
    "crust": "#11111b", "mantle": "#181825", "base": "#1e1e2e", "surface": "#313244",
    "mauve": "#cba6f7", "pink": "#f5c2e7", "red": "#f38ba8", "maroon": "#eba0ac",
    "peach": "#fab387", "yellow": "#f9e2af", "lavender": "#b4befe", "text": "#cdd6f4",
})
ROWS_PER_LOOP = 12


class SunsetDrive:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=83)
        self.hy = hy = 0.56 * h
        self.f = 0.50 * h                                      # focal length (px)
        self.cam = 1.0                                         # camera height
        self.D = ROWS_PER_LOOP
        self.znear, self.zfar = 0.9, 26.0                 # the view reaches past one period
        self.X = np.arange(-60, 61, 1.0)
        rng = np.random.default_rng(97)
        # height terms: (amplitude, x frequency, whole z cycles per D rows, phase)
        self.terms = [(rng.uniform(0.5, 1.0) / (i + 1) ** 0.8, rng.uniform(0.04, 0.22) * (1 + i * 0.6),
                       int(rng.integers(1, 4) * (i + 1)), rng.uniform(0, TAU)) for i in range(5)]
        # sky, sun and stars are static apart from a slow pulse
        v = np.clip(ys / hy, 0, 1)
        sky = ramp(np.broadcast_to(v, (h, w)), [(0.0, P["crust"]), (0.45, P["mantle"] * 0.5 + P["base"] * 0.5),
                                                 (0.75, P["base"] * 0.55 + P["mauve"] * 0.25),
                                                 (0.93, P["maroon"] * 0.55 + P["base"] * 0.3),
                                                 (1.0, P["peach"] * 0.7)])
        self.sky = sky.astype(np.float32)
        self.stars = Stars(w, int(hy), 380, seed=5, bottom=0.8, bias=1.8)
        cx, cy, R = 0.5 * w, hy - 0.11 * h, 0.20 * h
        self.sun = (cx, cy, R)
        d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        self.sun_d = d.astype(np.float32)
        sv = np.clip((ys - (cy - R)) / (2 * R), 0, 1)
        self.sun_col = ramp(np.broadcast_to(sv, (h, w)), [(0.0, P["yellow"]), (0.45, P["peach"]),
                                                          (0.8, P["red"]), (1.0, P["mauve"])])
        # soft horizontal haze bands across the lower sun (static)
        bands = 1 - 0.55 * smoothstep(0.55, 1.0, sv) * (0.5 + 0.5 * np.cos(TAU * sv * 9)) ** 6
        self.sun_bands = bands.astype(np.float32)

    def height(self, X, Zw):
        valley = np.clip((np.abs(X) - 2.5) / 9.0, 0, 1) ** 1.6
        hgt = np.zeros(np.broadcast(X, Zw).shape)
        for a, fx, q, ph in self.terms:
            hgt += a * (0.5 + 0.5 * np.sin(fx * X + TAU * q * Zw / self.D + ph))
        return valley * hgt * 5.5

    def _terrain(self, t: float):
        w, h, s = self.w, self.h, self.s
        ss = 2
        img = Image.new("RGB", (w * ss, h * ss), (0, 0, 0))
        cov = Image.new("L", (w * ss, h * ss), 0)
        d, dc = ImageDraw.Draw(img), ImageDraw.Draw(cov)
        cam_z = t * self.D
        k0 = math.floor(cam_z + self.znear)
        ks = np.arange(k0, k0 + int(self.zfar) + 2)[::-1]      # far to near
        ground = tuple(int(c * 255) for c in P["mantle"] * 0.9)
        prev = None
        for k in ks:
            z = k - cam_z
            if z < self.znear * 0.35:
                continue
            hgt = self.height(self.X, float(k % self.D))
            sx = (w / 2 + self.f * self.X / z) * ss
            sy = (self.hy + self.f * (self.cam - hgt) / z) * ss
            fog = smoothstep(self.zfar, self.zfar * 0.45, z)
            near = smoothstep(self.zfar * 0.6, 1.5, z)
            col = (P["mauve"] * (1 - near) + P["pink"] * near) * fog
            colt = tuple(int(min(c, 1) * 255) for c in col)
            pts = list(zip(sx.tolist(), sy.tolist()))
            poly = pts + [(sx[-1], h * ss + 10), (sx[0], h * ss + 10)]
            d.polygon(poly, fill=ground)
            dc.polygon(poly, fill=255)
            lw = max(1, int(round((1.0 + 1.6 * near) * s * ss)))
            if prev is not None and fog > 0.01:
                psx, psy, pcol = prev
                for j in range(len(sx)):
                    if -50 < sx[j] < w * ss + 50 or -50 < psx[j] < w * ss + 50:
                        d.line([(psx[j], psy[j]), (sx[j], sy[j])], fill=colt, width=lw)
            if fog > 0.01:
                d.line(pts, fill=colt, width=lw, joint="curve")
            prev = (sx, sy, colt)
        rgb = np.asarray(img.reduce(ss), np.float32) / 255.0
        a = np.asarray(cov.reduce(ss), np.float32) / 255.0
        return rgb, a

    def frame(self, t: float) -> np.ndarray:
        w, h, s = self.w, self.h, self.s
        ys, xs = self.ys, self.xs
        pulse = 0.5 - 0.5 * math.cos(TAU * t)
        img = self.sky.copy()
        hy = int(self.hy)
        img[:hy] = 1 - (1 - img[:hy]) * (1 - P["text"] * (self.stars.at(t) * 0.8)[..., None])
        cx, cy, R = self.sun
        d = self.sun_d
        halo = np.exp(-(np.maximum(d - R, 0) / (0.35 * R * (1 + 0.15 * pulse))) ** 1.2) * (0.45 + 0.15 * pulse)
        img = 1 - (1 - img) * (1 - P["red"] * 0.8 * halo[..., None])
        ring_r = R * (1.22 + 0.03 * math.sin(TAU * t))
        ring = np.exp(-((d - ring_r) / (1.4 * s)) ** 2) * 0.35
        img = 1 - (1 - img) * (1 - P["peach"] * ring[..., None])
        disc = smoothstep(R + 1.0, R - 1.0, d) * self.sun_bands
        img = img * (1 - disc[..., None]) + self.sun_col * (0.95 + 0.05 * pulse) * disc[..., None]
        rgb, a = self._terrain(t)
        img = img * (1 - a[..., None]) + rgb
        gl = glow(rgb, 7 * s, down=4)
        img = 1 - (1 - img) * (1 - np.clip(gl * 1.4, 0, 1))
        haze = np.exp(-((ys - self.hy) / (0.03 * h)) ** 2) * 0.30
        img = 1 - (1 - img) * (1 - P["maroon"] * haze[..., None])
        vig = 1 - 0.30 * (((xs / w - 0.5) * 1.5) ** 2 + ((ys / h - 0.5) * 1.2) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(SunsetDrive, "sunset-drive", fps=24, seconds=10.0, crf=33, doc=__doc__)
