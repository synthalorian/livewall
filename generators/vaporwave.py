#!/usr/bin/env python3
"""vaporwave: a floating crystal between two columns over an endless checkered
floor, in the Rose Pine palette.

The octahedron turns a quarter turn per loop, which maps it onto itself, and
bobs once. The floor scrolls an even number of tiles (an odd number would swap
the colours). The checkerboard is box-filtered per pixel, so it stays clean
down to the horizon instead of shimmering.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import TAU, Canvas, coords, glow, palette, ramp, run, smoothstep, static_dither  # noqa: E402

P = palette({
    "base": "#191724", "surface": "#1f1d2e", "overlay": "#26233a", "muted": "#6e6a86",
    "subtle": "#908caa", "text": "#e0def4", "love": "#eb6f92", "gold": "#f6c177",
    "rose": "#ebbcba", "pine": "#31748f", "foam": "#9ccfd8", "iris": "#c4a7e7",
})
TILES_PER_LOOP = 4


def filtered_checker(u, v, du, dv):
    """Box-filtered checkerboard in [0, 1] (0.5 where it is too fine to show)."""
    def tri(x):
        return np.abs(np.mod(x * 0.5, 1.0) - 0.5)
    du = np.maximum(du, 1e-4)
    dv = np.maximum(dv, 1e-4)
    iu = 2 * (tri(u + 0.5 * du) - tri(u - 0.5 * du)) / du
    iv = 2 * (tri(v + 0.5 * dv) - tri(v - 0.5 * dv)) / dv
    return 0.5 - 0.5 * iu * iv


class Vaporwave:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=89)
        self.hy = hy = int(0.62 * h)
        v = ys / hy
        sky = ramp(np.broadcast_to(np.clip(v, 0, 1), (h, w)),
                   [(0.0, P["base"]), (0.35, P["overlay"]), (0.65, P["iris"] * 0.55 + P["overlay"] * 0.45),
                    (0.88, P["love"] * 0.6 + P["iris"] * 0.25), (1.0, P["gold"] * 0.75 + P["rose"] * 0.25)])
        # big soft sun behind everything
        cx, cy, R = 0.5 * w, 0.40 * h, 0.24 * h
        d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        sv = np.clip((ys - (cy - R)) / (2 * R), 0, 1)
        disc = smoothstep(R + 1, R - 1, d)
        sun = ramp(np.broadcast_to(sv, (h, w)), [(0.0, P["gold"]), (0.5, P["rose"]), (1.0, P["love"])])
        sky = 1 - (1 - sky) * (1 - P["rose"] * (np.exp(-(np.maximum(d - R, 0) / (0.5 * R)) ** 1.5) * 0.35)[..., None])
        sky = sky * (1 - disc[..., None] * 0.85) + sun * (disc * 0.85)[..., None]
        self.sky = sky.astype(np.float32)
        # floor geometry
        rows = np.maximum(ys - hy, 0.5) / h
        self.below = (ys >= hy).astype(np.float32)
        C = 0.35
        self.z = (C / rows).astype(np.float32)
        self.dz = (C / (rows * rows * h)).astype(np.float32)
        self.u = ((xs - w / 2) / h * self.z * 3.0).astype(np.float32)
        self.du = (self.z * 3.0 / h).astype(np.float32)
        self.fog = smoothstep(0.0, 0.25, rows).astype(np.float32)
        # columns, drawn once
        c = Canvas(w, h, ss=2)
        hl = Canvas(w, h, ss=2)
        for xc in (0.16 * w, 0.84 * w):
            cw, top, bot = 0.075 * h, 0.20 * h, 0.90 * h
            c.rect(xc - cw * 0.85, bot - 0.035 * h, xc + cw * 0.85, bot)          # plinth
            c.rect(xc - cw * 0.70, bot - 0.06 * h, xc + cw * 0.70, bot - 0.03 * h)
            c.rect(xc - cw * 0.5, top + 0.05 * h, xc + cw * 0.5, bot - 0.05 * h)   # shaft
            c.rect(xc - cw * 0.75, top + 0.02 * h, xc + cw * 0.75, top + 0.055 * h)  # capital
            c.rect(xc - cw * 0.9, top, xc + cw * 0.9, top + 0.025 * h)
            for k in range(-3, 4):                                                 # flutes
                fx = xc + k * cw * 0.13
                hl.line([(fx, top + 0.06 * h), (fx, bot - 0.065 * h)], 1.0, 1.4 * s)
            hl.rect(xc - cw * 0.5, top + 0.05 * h, xc - cw * 0.38, bot - 0.05 * h, 0.6)
        self.col_mask = c.get()
        self.col_lines = hl.get() * self.col_mask

    def _crystal(self, t: float):
        w, h, s = self.w, self.h, self.s
        th = (math.pi / 2) * t
        tilt = 0.42
        V = np.array([[1, 0, 0], [-1, 0, 0], [0, 1.45, 0], [0, -1.45, 0], [0, 0, 1], [0, 0, -1]], float)
        cy_, sy_ = math.cos(th), math.sin(th)
        Ry = np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]])
        ct, st = math.cos(tilt), math.sin(tilt)
        Rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])
        Vr = V @ Ry.T @ Rx.T
        scale = 0.13 * h
        cx, cy = 0.5 * w, 0.42 * h + 0.018 * h * math.sin(TAU * t)
        cam = 6.0
        pz = cam - Vr[:, 2]
        px = cx + Vr[:, 0] * scale * cam / pz
        py = cy - Vr[:, 1] * scale * cam / pz
        faces = [(2, 0, 4), (2, 4, 1), (2, 1, 5), (2, 5, 0), (3, 4, 0), (3, 1, 4), (3, 5, 1), (3, 0, 5)]
        light = np.array([-0.4, 0.6, 0.7])
        light /= np.linalg.norm(light)
        fill = np.zeros((h, w, 3), np.float32)
        cover = np.zeros((h, w), np.float32)
        for f in faces:                                       # convex: culling is enough
            a, b, c = (Vr[i] for i in f)
            n = np.cross(b - a, c - a)
            n /= np.linalg.norm(n)
            if n[2] <= 0:                                     # back face
                continue
            lam = 0.62 + 0.45 * max(0.0, float(n @ light))
            cv = Canvas(w, h, ss=2)
            cv.polygon([(px[i], py[i]) for i in f])
            m = cv.get()
            mix = 0.5 + 0.5 * n[0]
            col = ((P["rose"] * (1 - mix) + P["foam"] * mix) * 0.75 + P["iris"] * 0.35 * abs(n[1])) * lam
            fill = fill * (1 - m[..., None]) + col * m[..., None]
            cover = np.maximum(cover, m)
        edges = Canvas(w, h, ss=2)
        drawn = set()
        for f in faces:
            a, b, c = (Vr[i] for i in f)
            n = np.cross(b - a, c - a)
            if n[2] <= 0:
                continue
            for i, j in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                key = (min(i, j), max(i, j))
                if key not in drawn:
                    drawn.add(key)
                    edges.line([(px[i], py[i]), (px[j], py[j])], 1.0, 2.2 * s)
        return fill, cover, edges.get(), (cx, cy)

    def frame(self, t: float) -> np.ndarray:
        w, h, s, hy = self.w, self.h, self.s, self.hy
        ys, xs = self.ys, self.xs
        img = self.sky.copy()
        # floor
        v = self.z + t * TILES_PER_LOOP
        chk = filtered_checker(self.u, v, self.du, self.dz)
        near = ramp(chk, [(0.0, P["surface"]), (1.0, P["pine"] * 0.85 + P["foam"] * 0.15)])
        horizon = P["love"] * 0.45 + P["iris"] * 0.35
        floor = near * self.fog[..., None] + horizon * (1 - self.fog[..., None])
        floor = 1 - (1 - floor) * (1 - P["rose"] * (np.exp(-((xs - w / 2) / (0.12 * w)) ** 2)
                                                    * np.exp(-(ys - hy) / (0.08 * h)) * 0.25)[..., None])
        img = img * (1 - self.below[..., None]) + floor * self.below[..., None]
        line = np.exp(-((ys - hy) / (1.5 * s)) ** 2) * 0.6
        img = 1 - (1 - img) * (1 - P["gold"] * line[..., None])
        # crystal
        fill, cover, edges, (cx, cy) = self._crystal(t)
        shadow = np.exp(-(((xs - cx) / (0.10 * h)) ** 2 + ((ys - 0.80 * h) / (0.012 * h)) ** 2)) * 0.45
        img = img * (1 - shadow[..., None] * self.below[..., None])
        img = img * (1 - cover[..., None]) + fill
        gl = glow(edges, 6 * s, down=2)
        img = 1 - (1 - img) * (1 - P["foam"] * np.clip(gl * 1.5, 0, 1)[..., None])
        img = img * (1 - edges[..., None]) + P["text"] * edges[..., None]
        # columns
        cm = self.col_mask[..., None]
        shade = P["overlay"] * 0.9 + P["iris"] * 0.12
        img = img * (1 - cm) + shade * cm
        img = 1 - (1 - img) * (1 - P["rose"] * (self.col_lines * 0.22)[..., None])
        scan = 1 - 0.035 * (0.5 + 0.5 * np.cos(TAU * ys / (3 * s)))
        vig = 1 - 0.28 * (((xs / w - 0.5) * 1.5) ** 2 + ((ys / h - 0.5) * 1.2) ** 2)
        return np.clip(img * (vig * scan)[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(Vaporwave, "vaporwave", fps=24, seconds=10.0, crf=27, doc=__doc__)
