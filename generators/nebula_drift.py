#!/usr/bin/env python3
"""nebula-drift: a slow glide through a star field past a violet and teal nebula.

Each drifting star moves from far to near once per loop (its depth wraps with
frac()), fading in and out at the ends of the trip, so no star pops. The
nebula is two periodic noise fields blended with cos/sin of the loop phase:
part of it churns in place and returns to its start.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, Stars, coords, loop_mix, palette, ramp, resize, run,  # noqa: E402
                     smoothstep, static_dither, tile_noise)

P = palette({
    "void": "#05070f", "bg": "#0b0e1f", "indigo": "#2a2f6b", "violet": "#7a5cc8",
    "magenta": "#c86ab4", "teal": "#4fb8c0", "ice": "#d8e6ff", "warm": "#ffd9b0",
})


class NebulaDrift:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = h / 1080.0
        self.ys, self.xs = coords(w, h)
        self.dither = static_dither(h, w, seed=29)
        self.lw, self.lh = w // 4, h // 4
        lw, lh = self.lw, self.lh
        # each layer: a fixed shape plus a smaller part that churns over the loop
        self.gas = [(tile_noise(lh, lw, beta=3.0, seed=s0), tile_noise(lh, lw, beta=3.0, seed=s1),
                     tile_noise(lh, lw, beta=3.0, seed=s2)) for s0, s1, s2 in ((11, 1, 2), (13, 3, 4))]
        self.dust = (tile_noise(lh, lw, beta=2.8, seed=15), tile_noise(lh, lw, beta=2.8, seed=5),
                     tile_noise(lh, lw, beta=2.8, seed=6))
        self.hue = tile_noise(lh, lw, beta=3.4, seed=7)
        ly, lx = coords(lw, lh)
        # the nebula lives on a diagonal band so the frame keeps dark space
        band = (lx / lw - 0.5) * 0.8 + (ly / lh - 0.5) * 1.0
        self.band = np.exp(-(band / 0.42) ** 2).astype(np.float32)
        self.bg_stars = Stars(w, h, 600, seed=12, bias=1.0)
        rng = np.random.default_rng(77)
        n = 240
        self.st_theta = rng.uniform(0, TAU, n)
        self.st_rho = np.sqrt(rng.uniform(0.02, 1.0, n)) * 1.25
        self.st_z0 = rng.uniform(0, 1, n)
        self.st_b = rng.uniform(0.6, 1.0, n)
        self.st_warm = rng.random(n) < 0.25
        self.centre = (0.56 * w, 0.46 * h)

    def _nebula(self, t: float) -> np.ndarray:
        def layer(fixed, a, b, phase):
            return (0.85 * fixed + 0.5 * loop_mix(a, b, t, n=1, phase=phase)) / 1.4
        g1 = layer(*self.gas[0], 0.0)
        g2 = layer(*self.gas[1], 0.25)
        dens = np.clip(0.55 * g1 + 0.30 * g2 + 0.45, 0, None) ** 2.0 * self.band
        dust = np.clip(layer(*self.dust, 0.6) - 0.15, 0, None)
        dens = dens * np.exp(-1.4 * dust)
        hue = np.clip(0.5 + 0.35 * self.hue + 0.15 * g2, 0, 1)
        col = ramp(hue, [(0.0, P["indigo"]), (0.35, P["violet"]), (0.6, P["magenta"]), (0.85, P["teal"]),
                         (1.0, P["teal"] * 0.8 + P["ice"] * 0.2)])
        neb = col * np.clip(dens * 0.75, 0, 1.2)[..., None]
        neb += P["ice"] * (np.clip(dens - 0.9, 0, 1) * 0.25)[..., None]      # hot cores
        return resize(neb, self.w, self.h)

    def _drift(self, t: float) -> np.ndarray:
        w, h, s = self.w, self.h, self.s
        layer = np.zeros((h, w), np.float32)
        warm = np.zeros((h, w), np.float32)
        u = (self.st_z0 - t) % 1.0                      # 1 = far, 0 = near; one trip per loop
        z = 0.30 + 0.70 * u
        r = self.st_rho * 0.42 * h / z
        x = self.centre[0] + r * np.cos(self.st_theta)
        y = self.centre[1] + r * np.sin(self.st_theta)
        fade = smoothstep(1.0, 0.80, u) * smoothstep(0.0, 0.12, u)
        b = self.st_b * fade * (0.35 / z) ** 1.2
        rad = (0.85 + 0.9 * (1 - u)) * s
        xs, ys = self.xs[0], self.ys[:, 0]
        for xi, yi, bi, ri, wi in zip(x, y, b, rad, self.st_warm):
            if bi < 0.01 or not (-6 < xi < w + 6 and -6 < yi < h + 6):
                continue
            x0, x1 = max(int(xi - 4 * ri - 1), 0), min(int(xi + 4 * ri + 2), w)
            y0, y1 = max(int(yi - 4 * ri - 1), 0), min(int(yi + 4 * ri + 2), h)
            if x1 <= x0 or y1 <= y0:
                continue
            g = np.exp(-((xs[x0:x1] - xi) ** 2 + (ys[y0:y1, None] - yi) ** 2) / (2 * ri * ri)) * bi
            (warm if wi else layer)[y0:y1, x0:x1] += g
        return np.clip(layer, 0, 1), np.clip(warm, 0, 1)

    def frame(self, t: float) -> np.ndarray:
        w, h = self.w, self.h
        xs, ys = self.xs, self.ys
        v = np.sqrt(((xs - self.centre[0]) / w) ** 2 + ((ys - self.centre[1]) / h) ** 2)
        img = P["bg"] * (1 - np.clip(v * 1.3, 0, 1))[..., None] + P["void"] * np.clip(v * 1.3, 0, 1)[..., None]
        neb = self._nebula(t)
        img = 1 - (1 - img) * (1 - np.clip(neb, 0, 1))
        bg = self.bg_stars.at(t, depth=0.2) * 0.7
        img = 1 - (1 - img) * (1 - P["ice"] * bg[..., None])
        cool, warm = self._drift(t)
        img = 1 - (1 - img) * (1 - P["ice"] * cool[..., None])
        img = 1 - (1 - img) * (1 - P["warm"] * warm[..., None])
        return np.clip(img + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(NebulaDrift, "nebula-drift", fps=24, seconds=8.0, crf=31, doc=__doc__)
