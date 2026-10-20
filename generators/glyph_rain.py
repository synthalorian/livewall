#!/usr/bin/env python3
"""glyph-rain: columns of teal runes falling through the dark.

The runes are drawn here, not taken from a font: each is a few strokes on a
3x4 lattice, half of them mirror-symmetric. Every column's head travels its
cycle length a whole number of times per loop, and runes that change do so on
a schedule that repeats each loop. Two layers (near and far) give depth.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import Canvas, coords, glow, palette, run, static_dither  # noqa: E402

P = palette({
    "void": "#060d0c", "bg": "#0b1715", "deep": "#12302c", "dim": "#1d5c55",
    "teal": "#2dd5b7", "mint": "#a8f5e4",
})


def make_atlas(n: int, cw: int, ch: int, seed: int) -> np.ndarray:
    """n procedural runes, each a (ch, cw) float mask."""
    rng = np.random.default_rng(seed)
    mx, my = 0.22 * cw, 0.16 * ch
    gx = [mx + i * (cw - 2 * mx) / 2 for i in range(3)]
    gy = [my + j * (ch - 2 * my) / 3 for j in range(4)]
    pts = [(i, j) for i in range(3) for j in range(4)]
    out = np.zeros((n, ch, cw), np.float32)
    width = max(1.0, cw / 11)
    for g in range(n):
        c = Canvas(cw, ch, ss=4)
        sym = rng.random() < 0.5
        strokes = []
        # a spine keeps runes legible as a family
        if rng.random() < 0.7:
            i = 1 if sym else int(rng.integers(3))
            j0, j1 = sorted(rng.choice(4, 2, replace=False))
            strokes.append(((i, j0), (i, j1)))
        for _ in range(int(rng.integers(2, 4))):
            a = pts[int(rng.integers(len(pts)))]
            nb = [(a[0] + dx, a[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                  if (dx or dy) and 0 <= a[0] + dx < 3 and 0 <= a[1] + dy < 4]
            b = nb[int(rng.integers(len(nb)))]
            strokes.append((a, b))
        if sym:
            strokes += [((2 - a[0], a[1]), (2 - b[0], b[1])) for a, b in strokes]
        for a, b in strokes:
            c.line([(gx[a[0]], gy[a[1]]), (gx[b[0]], gy[b[1]])], 1.0, width)
        if rng.random() < 0.3:
            i, j = int(rng.integers(3)), int(rng.integers(4))
            c.ellipse(gx[i], gy[j], width * 1.1, width * 1.1)
        out[g] = c.get()
    return out


class Layer:
    def __init__(self, w, h, cw, ch, seed, density, speed):
        self.cw, self.ch = cw, ch
        self.cols, self.rows = -(-w // cw), -(-h // ch)
        self.w, self.h = w, h
        rng = np.random.default_rng(seed)
        self.atlas = make_atlas(72, cw, ch, seed)
        C, R = self.cols, self.rows
        self.L = rng.integers(R + 6, 2 * R + 10, C).astype(np.float32)    # cycle length (cells)
        self.k = rng.choice(speed, C)                                       # trips per loop
        self.off = rng.uniform(0, 1, C).astype(np.float32)
        self.trail = rng.uniform(7, 22, C).astype(np.float32)
        self.active = (rng.random(C) < density).astype(np.float32)
        self.base = rng.integers(0, len(self.atlas), (R, C))
        self.mut = rng.random((R, C)) < 0.18                                # runes that change
        self.mut_n = rng.integers(2, 7, (R, C))                             # changes per loop
        self.mut_ph = rng.uniform(0, 1, (R, C))
        self.row = np.arange(R, dtype=np.float32)[:, None]

    def at(self, t):
        head = (self.off * self.L + self.k * self.L * t) % self.L          # cells
        d = (head[None, :] - self.row) % self.L[None, :]                   # cells behind the head
        bright = np.clip(1 - d / self.trail[None, :], 0, 1) ** 1.6 * self.active[None, :]
        hot = np.clip(1 - d / 1.3, 0, 1) * self.active[None, :]
        step = np.floor(self.mut_n * t + self.mut_ph).astype(np.int64) % self.mut_n
        idx = np.where(self.mut, (self.base + 31 * step) % len(self.atlas), self.base)
        g = self.atlas[idx]                                                # R, C, ch, cw
        R, C = self.rows, self.cols
        inten = (g * bright[..., None, None]).transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)
        heat = (g * hot[..., None, None]).transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)
        return inten[:self.h, :self.w], heat[:self.h, :self.w]


class GlyphRain:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        s = h / 1080.0
        self.ys, self.xs = coords(w, h)
        self.dither = static_dither(h, w, seed=37)
        self.near = Layer(w, h, int(round(26 * s)), int(round(34 * s)), seed=8, density=0.65, speed=[1, 1, 2])
        self.far = Layer(w, h, int(round(16 * s)), int(round(21 * s)), seed=9, density=0.6, speed=[1, 1])
        v = self.ys / h
        r = np.sqrt(((self.xs / w - 0.5) * 1.3) ** 2 + (v - 0.45) ** 2)
        self.bg = (P["bg"] * (1 - np.clip(r * 1.4, 0, 1))[..., None]
                   + P["void"] * np.clip(r * 1.4, 0, 1)[..., None]).astype(np.float32)

    def frame(self, t: float) -> np.ndarray:
        img = self.bg.copy()
        fi, fh = self.far.at(t)
        far = glow(fi, 2.0, down=2) * 0.8 + fi * 0.25
        img = 1 - (1 - img) * (1 - P["dim"] * np.clip(far, 0, 1)[..., None])
        ni, nh = self.near.at(t)
        halo = glow(ni, 10.0, down=4)
        img = 1 - (1 - img) * (1 - P["deep"] * np.clip(halo * 2.0, 0, 1)[..., None])
        img = 1 - (1 - img) * (1 - P["teal"] * ni[..., None])
        img = 1 - (1 - img) * (1 - P["mint"] * nh[..., None])
        return np.clip(img + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(GlyphRain, "glyph-rain", fps=24, seconds=8.0, crf=30, doc=__doc__)
