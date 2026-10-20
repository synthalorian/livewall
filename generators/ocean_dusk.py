#!/usr/bin/env python3
"""ocean-dusk: open sea under a violet-to-amber dusk, in the Kanagawa palette.

The water is a sum of deep-water waves. Wave n completes n periods per loop,
and its length follows the deep-water dispersion relation (k = w^2 / g), so the
swell moves at a believable speed and wraps exactly. Each pixel reflects the
sky through the wave slope, which draws the sun's glitter path by itself.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, coords, glow, loop_mix, palette, ramp, resize, run, smoothstep,  # noqa: E402
                     static_dither, tile_noise)

P = palette({
    "ink": "#16161d", "bg": "#1f1f28", "wave": "#223249", "wave2": "#2d4f67",
    "violet": "#957fb8", "sakura": "#d27e99", "orange": "#ffa066", "yellow": "#e6c384",
    "white": "#dcd7ba", "crystal": "#7e9cd8",
})
SECONDS = 8.0
G = 9.81


class OceanDusk:
    def __init__(self, w: int, h: int, seconds: float = SECONDS):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.hy = hy = int(0.52 * h)
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=13)
        self.sun = (0.63 * w, hy - 0.035 * h, 0.055 * h)
        # sky (static part)
        v = np.clip(ys / hy, 0, 1)
        sky = ramp(np.broadcast_to(v[:hy], (hy, w)),
                   [(0.0, P["ink"]), (0.30, P["bg"] * 0.6 + P["violet"] * 0.25),
                    (0.62, P["violet"] * 0.55 + P["sakura"] * 0.25), (0.85, P["sakura"] * 0.75 + P["orange"] * 0.2),
                    (1.0, P["orange"] * 0.85 + P["yellow"] * 0.15)])
        cx, cy, R = self.sun
        d = np.sqrt((xs - cx) ** 2 + ((ys[:hy] - cy) * 1.4) ** 2)
        glow = np.exp(-(d / (6 * R)) ** 2) * 0.55 + np.exp(-(d / (1.8 * R)) ** 2) * 0.5
        sky = 1 - (1 - sky) * (1 - P["orange"] * glow[..., None])
        disc = smoothstep(R + 1.0, R - 1.0, np.sqrt((xs - cx) ** 2 + (ys[:hy] - cy) ** 2))
        self.disc = disc.astype(np.float32)
        sky = sky * (1 - disc[..., None]) + (P["yellow"] * 0.6 + P["white"] * 0.45) * disc[..., None]
        self.sky0 = sky.astype(np.float32)
        # clouds: soft horizontal streaks that morph in place
        cw, ch = w // 4, hy // 4
        self.cloud_ab = (tile_noise(ch, cw, beta=2.6, seed=41, sx=5.0, sy=1.0),
                         tile_noise(ch, cw, beta=2.6, seed=42, sx=5.0, sy=1.0))
        band = np.exp(-((np.arange(ch)[:, None] / ch - 0.55) / 0.22) ** 2)
        self.cloud_band = band.astype(np.float32)
        # a far island with a lone peak, left of the sun
        x01 = xs[0] / w
        peak = 0.085 * np.exp(-np.abs(x01 - 0.22) / 0.055) + 0.018 * np.exp(-((x01 - 0.33) / 0.035) ** 2)
        peak = np.where(peak > 0.004, peak - 0.004, 0)
        top = hy - peak * h
        self.island = (np.clip(ys[:hy] - top[None, :] + 0.5, 0, 1) * (peak[None, :] > 0)).astype(np.float32)
        # water geometry
        rows = ys[hy:] - hy + 0.5
        self.dy = rows / h                                           # Hx1
        self.C = 3.0                                                 # camera height (m)
        z = self.C / (self.dy * 1.25)                                # depth (m)
        self.X = ((xs - w / 2) / h * z * 1.25).astype(np.float32)
        self.Z = np.broadcast_to(z, self.X.shape).astype(np.float32)
        dz = self.C / (self.dy ** 2 * 1.25 * h)                      # metres per pixel row
        rng = np.random.default_rng(23)
        self.waves = []
        for n, amp in ((1, 0.020), (2, 0.06), (2, 0.05), (3, 0.06), (4, 0.06), (5, 0.06), (6, 0.05),
                       (7, 0.05), (9, 0.045), (11, 0.04), (13, 0.035), (16, 0.03)):
            om = TAU * n / seconds
            k = om * om / G
            ang = math.pi / 2 + rng.uniform(-0.75, 0.75)            # mostly towards the camera
            kx, kz = k * math.cos(ang), k * math.sin(ang)
            lam = TAU / k
            fade = smoothstep(2.5, 6.0, lam / np.maximum(dz, lam / 1e3 * 0 + 1e-6)) * \
                smoothstep(2.5, 6.0, lam / (z * 1.25 / h))
            self.waves.append((n, kx, kz, amp, rng.uniform(0, TAU), fade.astype(np.float32)))
        self.fres = (0.35 + 0.65 * np.exp(-self.dy * 7)).astype(np.float32)
        self.depth_fog = smoothstep(0.0, 0.05, self.dy).astype(np.float32)

    def _sky(self, t):
        hy, w = self.hy, self.w
        c = loop_mix(*self.cloud_ab, t, n=1) / 1.4
        dens = np.clip(c * 0.6 - 0.1, 0, 1) * self.cloud_band
        dens = resize(dens.astype(np.float32), w, hy)
        lit = ramp(np.broadcast_to(np.clip(self.ys[:hy] / hy, 0, 1), (hy, w)),
                   [(0.0, P["violet"] * 0.45), (0.6, P["sakura"] * 0.75), (1.0, P["orange"])])
        sky = self.sky0 * (1 - dens[..., None] * 0.7) + lit * (dens * 0.55)[..., None]
        isl = self.island[..., None]
        return sky * (1 - isl) + (P["ink"] * 0.6 + P["violet"] * 0.12) * isl

    def frame(self, t: float) -> np.ndarray:
        w, h, hy = self.w, self.h, self.hy
        sky = self._sky(t)
        gx = np.zeros_like(self.X)
        gz = np.zeros_like(self.X)
        for n, kx, kz, amp, ph, fade in self.waves:
            arg = kx * self.X + kz * self.Z - TAU * n * t + ph
            s = np.sin(arg) * (amp * fade)
            gx += s * kx / math.hypot(kx, kz)
            gz += s * kz / math.hypot(kx, kz)
        # reflect: mirror row, bent by the wave slope (more so up close)
        rows = np.arange(hy, h)[:, None]
        mirror = 2 * hy - rows - 1
        bend = (self.dy * h * 0.9 + 6 * self.s)
        ry = np.clip(mirror + gz * bend * 2.2, 0, hy - 1).astype(np.int32)
        rx = np.clip(np.arange(w)[None, :] + gx * bend * 1.2, 0, w - 1).astype(np.int32)
        refl = glow(sky, 3.0, down=2, pad_mode="edge")[ry, rx]   # water reflections are soft
        glint = self.disc[ry, rx] * smoothstep(0.0, 0.08, self.dy)
        body = P["wave2"] * (0.55 + 0.45 * np.clip(0.5 + gz * 4, 0, 1))[..., None]
        sea = body * (1 - self.fres[..., None]) + refl * self.fres[..., None]
        sea = sea * (0.8 + 0.2 * self.depth_fog[..., None])
        sea = 1 - (1 - sea) * (1 - P["yellow"] * (glint * 0.7)[..., None])
        img = np.concatenate([sky, sea], axis=0)
        haze = np.exp(-((self.ys - hy) / (0.012 * h)) ** 2) * 0.35
        img = 1 - (1 - img) * (1 - (P["orange"] * 0.5 + P["sakura"] * 0.5) * haze[..., None])
        xs, ys = self.xs, self.ys
        vig = 1 - 0.30 * (((xs / w - 0.5) * 1.4) ** 2 + ((ys / h - 0.5) * 1.3) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(OceanDusk, "ocean-dusk", fps=24, seconds=SECONDS, crf=26, doc=__doc__)
