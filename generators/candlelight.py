#!/usr/bin/env python3
"""candlelight: one pillar candle in a dark, warm room. Calm and quiet.

The flame sways and breathes on a few low sines (whole cycles per loop); the
room light follows it. A few out-of-focus lights glow faintly behind. Warm,
low-contrast tones for Ristretto and other warm themes.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import TAU, coords, palette, ramp, run, smoothstep, static_dither  # noqa: E402

P = palette({
    "dark": "#140f0e", "bg": "#2c2525", "wall": "#3a2c27", "table": "#1d1614",
    "wax": "#e6d2b5", "wax_dark": "#8a6a50", "amber": "#f9cc6c", "orange": "#f38d70",
    "ember": "#d4643c", "core": "#fff4dc", "blue": "#5b6fb5",
})


class Candlelight:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=17)
        self.cx = 0.5 * w
        self.ty = 0.80 * h                                  # table edge
        self.rc = 0.085 * h                                 # candle radius
        self.top = self.ty - 0.26 * h                       # candle top
        self.fbase = self.top - 0.016 * h                   # flame base
        self.fh, self.fw = 0.12 * h, 0.030 * h             # flame height, half width
        rng = np.random.default_rng(3)
        self.sway = [(rng.uniform(0.3, 1.0) / n, n, rng.uniform()) for n in (1, 2, 3, 5)]
        self.flick = [(rng.uniform(0.4, 1.0) / n ** 0.7, n, rng.uniform()) for n in (2, 3, 4, 7, 9)]
        # static room: warm wall falling off from the flame, darker table top
        d = np.sqrt((xs - self.cx) ** 2 + ((ys - self.fbase) * 1.15) ** 2) / h
        self.dist = d.astype(np.float32)
        wall = ramp(np.clip(d / 0.95, 0, 1), [(0.0, P["wall"] * 1.25), (0.35, P["bg"]),
                                             (1.0, P["dark"])])
        tv = np.clip((ys - self.ty) / (h - self.ty), 0, 1)
        table = ramp(np.broadcast_to(tv, (h, w)), [(0.0, P["table"] * 1.6), (1.0, P["dark"])])
        table = table * (0.55 + 0.45 * np.exp(-((xs - self.cx) / (0.45 * w)) ** 2))[..., None]
        edge = smoothstep(self.ty - 1.5 * s, self.ty + 1.5 * s, np.broadcast_to(ys, (h, w)))
        self.room = (wall * (1 - edge[..., None]) + table * edge[..., None]).astype(np.float32)
        self.table_mask = edge
        # out-of-focus lights in the background
        self.bokeh = np.zeros((h, w), np.float32)
        self.bokeh_k = []
        for i in range(7):
            bx = rng.uniform(0.05, 0.95) * w
            if abs(bx - self.cx) < 0.12 * w:
                bx += 0.25 * w * np.sign(bx - self.cx + 1e-3)
            by = rng.uniform(0.18, 0.55) * h
            r = rng.uniform(0.025, 0.06) * h
            disc = smoothstep(r, r * 0.82, np.sqrt((xs - bx) ** 2 + (ys - by) ** 2))
            layer = (disc * rng.uniform(0.05, 0.11)).astype(np.float32)
            self.bokeh_k.append((layer, int(rng.integers(1, 3)), rng.uniform()))
        # candle body: lit from the flame above, rounded sides
        u = (xs - self.cx) / self.rc
        body = (np.abs(u) < 1) & (ys > self.top) & (ys < self.ty + 0.005 * h)
        aa = smoothstep(1.0, 0.985, np.abs(u)) * smoothstep(self.top - 1, self.top + 1, ys) * \
            smoothstep(self.ty + 0.006 * h, self.ty + 0.004 * h, ys)
        shade = np.sqrt(np.clip(1 - u * u, 0, 1))
        down = np.clip((ys - self.top) / (self.ty - self.top), 0, 1)
        glow_in = np.exp(-down / 0.22)                       # light scattered through the wax
        wax = (P["wax_dark"] * (0.25 + 0.55 * shade)[..., None] * (1 - 0.5 * down)[..., None]
               + P["amber"] * (0.55 * glow_in * (0.5 + 0.5 * shade))[..., None])
        self.wax = np.where(body[..., None], wax, 0).astype(np.float32)
        self.wax_a = (aa * body).astype(np.float32)
        # melted pool at the top: a lit ellipse
        e = ((xs - self.cx) / (self.rc * 0.97)) ** 2 + ((ys - self.top) / (0.012 * h)) ** 2
        self.pool = smoothstep(1.0, 0.8, e).astype(np.float32)
        # flame region of interest
        self.fx0, self.fx1 = int(self.cx - 0.17 * h), int(self.cx + 0.17 * h)
        self.fy0, self.fy1 = int(self.fbase - 3.2 * self.fh), int(self.fbase + 2.6 * self.fh)

    def _state(self, t: float):
        sway = sum(a * math.sin(TAU * (n * t + p)) for a, n, p in self.sway) * 0.55
        fl = sum(a * math.sin(TAU * (n * t + p)) for a, n, p in self.flick)
        return sway, 1.0 + 0.035 * fl

    def frame(self, t: float) -> np.ndarray:
        w, h, s = self.w, self.h, self.s
        ys, xs = self.ys, self.xs
        sway, bright = self._state(t)
        img = self.room * (0.80 + 0.20 * bright)
        for layer, n, ph in self.bokeh_k:
            k = 0.75 + 0.25 * math.sin(TAU * (n * t + ph))
            img = 1 - (1 - img) * (1 - P["amber"] * (layer * k)[..., None])
        # warm light pooled around the flame
        light = np.exp(-(self.dist / 0.30) ** 2) * 0.22 * bright
        img = 1 - (1 - img) * (1 - P["orange"] * light[..., None])
        # reflection of the flame on the table
        refl = (np.exp(-((xs - self.cx - sway * self.fw * 0.5) / (0.05 * h)) ** 2)
                * np.exp(-np.maximum(ys - self.ty, 0) / (0.07 * h)) * self.table_mask * 0.28 * bright)
        img = 1 - (1 - img) * (1 - P["amber"] * refl[..., None])
        # candle
        img = img * (1 - self.wax_a[..., None]) + self.wax * (0.85 + 0.15 * bright) * self.wax_a[..., None]
        img = 1 - (1 - img) * (1 - P["amber"] * (self.pool * 0.55 * bright)[..., None])
        # flame (only its box)
        y0, y1, x0, x1 = self.fy0, self.fy1, self.fx0, self.fx1
        fy = (self.fbase - ys[y0:y1]) / (self.fh * bright)          # 0 base .. 1 tip
        off = sway * self.fw * 1.6 * np.clip(fy, 0, 1) ** 2
        fx = (xs[:, x0:x1] - self.cx - off) / self.fw
        yy = np.clip(fy, 0, 1)
        hw = 1.0 * np.sqrt(np.clip(yy * 2.6, 0, 1)) * (1 - yy ** 1.4) ** 1.1 + 0.02
        q = np.sqrt((fx / hw) ** 2 + np.where(fy < 0, (fy / 0.12) ** 2, 0))
        inside = smoothstep(1.0, 0.75, q) * (fy < 1.0)
        core = smoothstep(0.8, 0.2, q) * smoothstep(0.75, 0.15, fy) * smoothstep(-0.05, 0.12, fy)
        col = ramp(np.clip(fy, 0, 1), [(0.0, P["ember"]), (0.12, P["amber"]), (0.5, P["amber"]),
                                       (1.0, 0.5 * P["orange"] + 0.5 * P["ember"])])
        col = col * (1 - core[..., None]) + P["core"] * core[..., None]
        blue = smoothstep(0.2, -0.02, fy) * smoothstep(0.35, 0.85, q) * inside
        col = col * (1 - 0.6 * blue[..., None]) + P["blue"] * (0.6 * blue)[..., None]
        halo = np.exp(-((fx / 2.8) ** 2 + ((fy - 0.35) / 0.9) ** 2)) * 0.30 * bright
        box = img[y0:y1, x0:x1]
        box = 1 - (1 - box) * (1 - P["amber"] * halo[..., None])
        box = box * (1 - inside[..., None]) + col * inside[..., None]
        img[y0:y1, x0:x1] = box
        # wick
        wick = (np.abs(xs - self.cx - sway * 0.6 * s) < 1.4 * s) & (ys > self.fbase + 0.002 * h) & (ys < self.top)
        img = np.where(wick[..., None], P["dark"] * 1.5, img)
        vig = 1 - 0.35 * (((xs / w - 0.5) * 1.4) ** 2 + ((ys / h - 0.5) * 1.2) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(Candlelight, "candlelight", fps=24, seconds=8.0, crf=25, doc=__doc__)
