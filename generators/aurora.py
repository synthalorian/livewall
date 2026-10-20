#!/usr/bin/env python3
"""aurora: curtains of polar light over a still lake, in the Nord palette.

Three ribbons sway on sines with whole cycles per loop; their rays shimmer with
loop_mix()ed 1D noise, so the loop wraps exactly. The lake mirrors the sky with
a gentle periodic ripple.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, Canvas, Stars, coords, loop_mix, palette, ramp, resize, run,  # noqa: E402
                     screen, smoothstep, static_dither, tile_noise, vgradient)

P = palette({
    "night": "#191d24", "bg": "#2e3440", "bg1": "#3b4252", "bg3": "#4c566a",
    "frost0": "#8fbcbb", "frost1": "#88c0d0", "frost3": "#5e81ac",
    "green": "#a3be8c", "glow": "#8fe3ad", "purple": "#b48ead", "snow": "#eceff4",
})


class Aurora:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.hy = int(0.70 * h)                       # lake shore
        self.lw, self.lh = w // 2, self.hy // 2       # aurora is soft: render at half size
        self.ys, self.xs = coords(w, h)
        self.dither = static_dither(h, w, seed=21)
        self.sky = vgradient(w, h, [(0.0, P["night"]), (0.45, 0.8 * P["bg"] + 0.2 * P["night"]),
                                    (0.70, 0.75 * P["bg1"] + 0.25 * P["frost3"] * 0.5), (1.0, P["night"])])
        self.stars = Stars(w, self.hy, 650, seed=4, bottom=0.95, bias=1.3)
        rng = np.random.default_rng(9)
        # ribbons: base height (fraction of sky), thickness, strength, sway terms
        self.ribbons = []
        for base, height, k in ((0.62, 0.28, 1.0), (0.45, 0.20, 0.7), (0.74, 0.14, 0.5)):
            sway = [(rng.uniform(0.05, 0.10) / (i + 1), rng.uniform(0.5, 1.2) * (i + 1),
                     int(rng.choice([-1, 1]) * (1 + i // 2)), rng.uniform()) for i in range(4)]
            rays = (tile_noise(1, self.lw, beta=1.4, seed=int(rng.integers(1 << 30)), cut=0.003)[0],
                    tile_noise(1, self.lw, beta=1.4, seed=int(rng.integers(1 << 30)), cut=0.003)[0])
            self.ribbons.append(dict(base=base, height=height, k=k, sway=sway, rays=rays,
                                     ph=rng.uniform()))
        self._build_land()
        # ripple for the reflection: whole cycles per loop
        self.rip = [(rng.uniform(0.6, 1.4) * s, rng.uniform(0.02, 0.05), int(n), rng.uniform())
                    for n in (1, 2, 3)]

    def _build_land(self):
        w, h, hy, s = self.w, self.h, self.hy, self.s
        rng = np.random.default_rng(31)
        x = np.linspace(0, 1, w)
        ridge = np.zeros(w)
        for k in range(1, 8):
            ridge += rng.uniform(0.4, 1.0) / k ** 1.2 * np.sin(TAU * (k * 1.3 * x + rng.uniform()))
        ridge = (ridge - ridge.min()) / (ridge.max() - ridge.min())
        ridge = hy - (0.03 + 0.11 * ridge * (0.55 + 0.45 * np.abs(x - 0.45) * 2)) * h
        self.ridge = ridge.astype(np.float32)
        # foreground shore with pines, both corners
        c = Canvas(w, h, ss=2)
        for side in (0, 1):
            x0 = 0 if side == 0 else w
            span = 0.30 * w
            pts = [(x0, h)]
            for i in range(41):
                u = i / 40
                xx = x0 + (u * span if side == 0 else -u * span)
                yy = h - (0.13 - 0.10 * u ** 1.5) * h - 0.008 * h * np.sin(17 * u)
                pts.append((xx, yy))
            pts.append((pts[-1][0], h))
            c.polygon(pts)
            for i in range(14 if side == 0 else 11):
                u = rng.uniform(0, 0.8) ** 1.4
                tx = x0 + (u * span if side == 0 else -u * span)
                base = h - (0.13 - 0.10 * u ** 1.5) * h + 4 * s
                th = (0.10 + 0.20 * (1 - u) * rng.uniform(0.5, 1.0)) * h
                tw = th * rng.uniform(0.20, 0.27)
                for j in range(5):                    # stacked tiers
                    a = j / 5
                    yb = base - a * th * 0.85
                    c.polygon([(tx - tw * (1 - a * 0.8) / 2, yb), (tx + tw * (1 - a * 0.8) / 2, yb),
                               (tx, yb - th * 0.32)])
                c.rect(tx - 2 * s, base - 0.1 * th, tx + 2 * s, base + 2)
        self.shore = c.get()

    def _aurora(self, t: float) -> np.ndarray:
        lw, lh = self.lw, self.lh
        v = (np.arange(lh, dtype=np.float32)[:, None] + 0.5) / lh      # 0 top .. 1 shore
        xs = (np.arange(lw, dtype=np.float32) + 0.5) / lw
        out = np.zeros((lh, lw, 3), np.float32)
        for r in self.ribbons:
            yb = np.full(lw, r["base"], np.float32)
            for amp, f, n, ph in r["sway"]:
                yb += amp * np.sin(TAU * (f * xs + n * t + ph))
            ray = loop_mix(*r["rays"], t, n=1, phase=r["ph"]) / 1.4
            ray = np.clip(0.6 + 0.4 * ray, 0.1, 1.4)
            # bright folds drifting along the curtain, dark gaps between them
            env = np.clip(0.5 + 0.9 * np.sin(TAU * (0.9 * xs - t + r["ph"])), 0, 1) ** 1.5
            env *= 0.75 + 0.25 * np.sin(TAU * (2.3 * xs + 2 * t + r["ph"]))
            d = yb[None, :] - v                                           # >0 above the lower edge
            hgt = r["height"] * (0.5 + 0.7 * ray)[None, :]
            edge = smoothstep(-0.006, 0.012, d)
            inten = (np.exp(-np.maximum(d, 0) / hgt) * edge
                     + 0.6 * np.exp(-(d / 0.012) ** 2)
                     + 0.18 * np.exp(np.minimum(d, 0) / 0.035) * (d < 0)) * (ray * env)[None, :] * r["k"]
            col = ramp(np.clip(d / (r["height"] * 1.8), 0, 1),
                       [(0.0, P["glow"]), (0.30, 0.7 * P["glow"] + 0.3 * P["frost0"]),
                        (0.65, 0.5 * P["frost0"] + 0.5 * P["purple"]), (1.0, P["purple"])])
            out += col * inten[..., None]
        return out * 0.85

    def frame(self, t: float) -> np.ndarray:
        w, h, hy, s = self.w, self.h, self.hy, self.s
        ys, xs = self.ys, self.xs
        img = self.sky.copy()
        up = img[:hy]
        up[:] = screen(up, P["snow"] * 0.85, self.stars.at(t) * 0.9)
        aur = resize(self._aurora(t), w, hy)
        up[:] = 1 - (1 - up) * (1 - np.clip(aur, 0, 1))
        # distant mountains with a faint aurora rim
        m = np.clip(ys[:hy] - self.ridge[None, :] + 0.5, 0, 1)
        mcol = vgradient(1, hy, [(0.0, P["bg"] * 0.55), (1.0, P["night"] * 1.1)])[:, 0][:, None, :]
        rim = np.exp(-((ys[:hy] - self.ridge[None, :]) / (1.5 * s)) ** 2) * (ys[:hy] > self.ridge[None, :] - 2)
        glowc = aur.mean(axis=0, keepdims=True)
        up[:] = up * (1 - m[..., None]) + mcol * m[..., None]
        up[:] += rim[..., None] * glowc * 0.8
        # lake: mirrored sky, darkened, with a slow ripple
        rows = np.arange(hy, h)
        src = np.clip(2 * hy - rows - 1, 0, hy - 1)
        dist = (rows - hy) / (h - hy)
        shift = np.zeros(len(rows), np.float32)
        for amp, f, n, ph in self.rip:
            shift += amp * (0.8 + 3 * dist) * np.sin(TAU * ((rows - hy) / (s * (14 + 60 * dist)) * f * 20 + n * t + ph))
        xi = np.clip((np.arange(w)[None, :] + shift[:, None]).astype(np.int32), 0, w - 1)
        refl = up[src[:, None], xi]
        fade = (0.55 - 0.25 * dist)[:, None, None]
        img[hy:] = refl * fade + P["night"] * (1 - fade) * 0.9
        shore_line = np.exp(-((ys - hy) / (1.2 * s)) ** 2)
        img = screen(img, P["frost1"] * 0.25, np.broadcast_to(shore_line, (h, w)).astype(np.float32))
        # foreground shore and pines
        img = img * (1 - self.shore[..., None]) + (P["night"] * 0.55) * self.shore[..., None]
        vig = 1 - 0.30 * (((xs / w - 0.5) * 1.5) ** 2 + ((ys / h - 0.45) * 1.2) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(Aurora, "aurora", fps=24, seconds=10.0, crf=26, doc=__doc__)
