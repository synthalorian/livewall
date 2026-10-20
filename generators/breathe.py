#!/usr/bin/env python3
"""breathe: a minimal gradient that slowly breathes, in the Everforest palette.

Three soft colour fields drift on closed Lissajous paths (whole cycles per
loop) while the light swells and settles once per loop: about six breaths a
minute. Everything is smooth, so it renders small and upsamples cleanly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import TAU, coords, palette, resize, run, static_dither  # noqa: E402

P = palette({
    "bg_dim": "#1e2326", "bg0": "#2d353b", "bg2": "#3d484d",
    "green": "#a7c080", "aqua": "#83c092", "blue": "#7fbbb3", "yellow": "#dbbc7f",
})


class Breathe:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.lw, self.lh = 256, 144                  # everything here is soft
        ys, xs = coords(self.lw, self.lh)
        self.u = (xs / self.lw - 0.5) * (self.lw / self.lh)
        self.v = ys / self.lh - 0.5
        self.dither = static_dither(h, w, seed=5)
        # (colour, centre, orbit radii, orbit cycles per loop, phase, size, strength)
        self.blobs = [
            (P["green"], (-0.35, 0.10), (0.18, 0.10), (1, 1), 0.00, 0.55, 0.55),
            (P["aqua"], (0.40, -0.12), (0.14, 0.12), (1, 2), 0.30, 0.50, 0.50),
            (P["blue"], (0.05, 0.30), (0.22, 0.06), (1, 1), 0.65, 0.60, 0.40),
            (P["yellow"], (0.55, 0.38), (0.10, 0.08), (2, 1), 0.15, 0.35, 0.18),
        ]

    def frame(self, t: float) -> np.ndarray:
        u, v = self.u, self.v
        breath = 0.5 - 0.5 * np.cos(TAU * t)                     # 0 -> 1 -> 0
        breath = breath * breath * (3 - 2 * breath)               # linger at the ends
        base = P["bg_dim"] + (P["bg0"] - P["bg_dim"]) * np.clip(0.75 - 0.9 * v, 0, 1)[..., None]
        img = np.broadcast_to(base, (self.lh, self.lw, 3)).copy()
        light = np.zeros((self.lh, self.lw, 3), np.float32)
        for col, (cx, cy), (rx, ry), (fx, fy), ph, size, k in self.blobs:
            px = cx + rx * np.sin(TAU * (fx * t + ph))
            py = cy + ry * np.cos(TAU * (fy * t + ph))
            r = size * (0.85 + 0.25 * breath)
            d2 = ((u - px) ** 2 + (v - py) ** 2) / (r * r)
            light += col * (k * (0.55 + 0.45 * breath) * np.exp(-1.6 * d2))[..., None]
        halo = np.exp(-((u * 0.8) ** 2 + (v * 1.1) ** 2) / (0.20 + 0.10 * breath))
        img = img + (P["bg2"] - img) * (halo * (0.20 + 0.15 * breath))[..., None]
        # screen the colour in: lifts the background without washing it out
        img = 1 - (1 - img) * (1 - np.clip(light, 0, 1) * 0.42)
        out = resize(img, self.w, self.h)
        return np.clip(out + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(Breathe, "breathe", fps=24, seconds=10.0, crf=28, doc=__doc__)
