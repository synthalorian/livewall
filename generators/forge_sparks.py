#!/usr/bin/env python3
"""forge-sparks: sparks and embers rising from a forge in front of dark steel.

Dark brushed steel with an embossed shield, lit red from below by an ember bed.
Each spark flies a ballistic arc and is re-launched a whole number of times per
loop, so the shower never stops and the clip wraps exactly. The steel's
lighting is precomputed; a frame only scales it by the forge's flicker.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, Canvas, blur, coords, glow, loop_mix, palette, ramp, resize, run,  # noqa: E402
                     smoothstep, static_dither, tile_noise)

P = palette({
    "black": "#0b0c0e", "steel": "#1c1f24", "steel2": "#2c3037", "edge": "#565c66",
    "red": "#c8102e", "ember": "#ff3b1f", "orange": "#ff8a2a", "yellow": "#ffd27a", "white": "#fff4e0",
})
SECONDS = 8.0


class ForgeSparks:
    def __init__(self, w: int, h: int, seconds: float = SECONDS):
        self.w, self.h, self.T = w, h, seconds
        self.s = s = h / 1080.0
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=61)
        # brushed steel: horizontal streaks plus a faint broad mottling
        brush = tile_noise(h // 2, w // 2, beta=1.4, seed=3, sx=12.0, sy=0.6)
        mott = tile_noise(h // 8, w // 8, beta=3.0, seed=4)
        brush = resize(brush, w, h, smooth=False)
        mott = resize(mott, w, h)
        tex = 0.5 + 0.10 * brush + 0.12 * mott
        v = ys / h
        base = P["black"] + (P["steel"] - P["black"]) * np.clip(1.15 - 0.9 * np.abs(v - 0.45) * 2, 0, 1)[..., None]
        amb = base * (0.75 + 0.5 * tex)[..., None]
        # shield: a mask, blurred into a height map, shaded like a raised plate
        c = Canvas(w, h, ss=2)
        cx, top, sw, sh = 0.5 * w, 0.17 * h, 0.21 * h, 0.52 * h
        pts = []
        for i in range(41):                                   # right half, top -> point
            u = i / 40
            if u < 0.45:
                x, y = sw, top + 0.02 * h + u / 0.45 * 0.40 * sh
            else:
                a = (u - 0.45) / 0.55
                x = sw * math.cos(a * math.pi / 2) ** 0.9
                y = top + 0.02 * h + 0.40 * sh + a * 0.60 * sh
            pts.append((cx + x, y))
        top_edge = [(cx + sw * (1 - 2 * i / 20), top + 0.02 * h - 0.025 * h * math.sin(math.pi * i / 20))
                    for i in range(21)]
        poly = top_edge + [(2 * cx - x, y) for x, y in pts] + pts[::-1]
        c.polygon(poly)
        mask = c.get()
        inner = Canvas(w, h, ss=2)
        k = 0.80
        inner.polygon([(cx + (x - cx) * k, top + 0.05 * h + (y - top - 0.02 * h) * k * 1.02) for x, y in poly])
        imask = inner.get()
        height = blur(mask, 5 * s) + 0.5 * blur(imask, 3 * s)
        gy_, gx_ = np.gradient(height)
        facing_down = np.clip(gy_ * 30, -1, 1)                # faces that look down catch the forge
        facing_up = np.clip(-gy_ * 30, 0, 1)
        rim = np.clip(np.abs(gx_) * 25, 0, 1)
        plate = P["steel"] * (0.6 + 0.5 * tex)[..., None]
        amb = amb * (1 - mask[..., None]) + plate * mask[..., None]
        amb = amb + P["edge"] * (facing_up * 0.16 + rim * 0.04)[..., None]
        amb = amb * (1 - 0.35 * np.clip(-facing_down, 0, 1))[..., None]
        self.amb = amb.astype(np.float32)
        # how much each pixel answers the forge light (from below, centre)
        d = np.sqrt(((xs - 0.5 * w) / (0.75 * w)) ** 2 + ((ys - 1.05 * h) / (0.85 * h)) ** 2)
        light = np.exp(-d * d * 2.2)
        resp = light * (0.35 + 0.65 * tex) + np.clip(facing_down, 0, 1) * light * 1.4 + rim * light * 0.3
        self.resp = resp.astype(np.float32)
        # ember bed: churning heat at the bottom
        bw, bh = w // 6, int(0.10 * h) // 6
        self.bed_ab = (tile_noise(bh, bw, beta=2.8, seed=8, sx=1.6), tile_noise(bh, bw, beta=2.8, seed=9, sx=1.6))
        self.bed_y = h - int(0.10 * h)
        rng = np.random.default_rng(71)
        self.flick = [(rng.uniform(0.3, 1.0) / n ** 0.6, n, rng.uniform()) for n in (1, 3, 5, 8, 13)]
        # sparks
        n = 340
        self.sp = dict(
            x0=0.5 * w + rng.normal(0, 0.14, n) * w,
            vx=rng.normal(0, 0.16, n) * h,
            vy=rng.uniform(0.55, 1.35, n) * h,
            life=rng.uniform(0.6, 1.7, n),
            k=rng.integers(3, 8, n), ph=rng.uniform(0, 1, n),
            b=rng.uniform(0.5, 1.0, n), wob=rng.uniform(0, TAU, n))
        self.sp["k"] = np.minimum(self.sp["k"], np.floor(seconds / self.sp["life"])).astype(int)
        self.g = 0.75 * h
        m = 45
        self.em = dict(x0=rng.uniform(0.15, 0.85, m) * w, k=rng.integers(1, 3, m), ph=rng.uniform(0, 1, m),
                       amp=rng.uniform(0.01, 0.04, m) * w, n=rng.integers(1, 4, m), r=rng.uniform(1.2, 2.6, m) * s,
                       b=rng.uniform(0.25, 0.7, m))

    def _flicker(self, t):
        return 1.0 + 0.10 * sum(a * math.sin(TAU * (n * t + p)) for a, n, p in self.flick)

    def _sparks(self, t):
        w, h, s = self.w, self.h, self.s
        c = Canvas(w, h, ss=2)
        sp = self.sp
        period = self.T / sp["k"]
        age = ((sp["k"] * t + sp["ph"]) % 1.0) * period
        alive = age < sp["life"]
        for i in np.nonzero(alive)[0]:
            a, a0 = age[i], max(age[i] - 0.045, 0)
            def pos(tt):
                x = sp["x0"][i] + sp["vx"][i] * tt + 0.012 * w * math.sin(sp["wob"][i] + 9 * tt)
                y = 1.02 * h - sp["vy"][i] * tt + 0.5 * self.g * tt * tt
                return x, y
            fade = (1 - a / sp["life"][i]) ** 1.3 * min(1.0, a / 0.05)
            c.line([pos(a0), pos(a)], sp["b"][i] * fade, 1.6 * s)
        em = self.em
        u = (em["k"] * t + em["ph"]) % 1.0                     # 0 bottom .. 1 top
        x = em["x0"] + em["amp"] * np.sin(TAU * (em["n"] * t + em["ph"]))
        y = h * (1.0 - 1.05 * u)
        b = em["b"] * smoothstep(0.0, 0.08, u) * smoothstep(1.0, 0.6, u)
        for xi, yi, ri, bi in zip(x, y, em["r"], b):
            c.ellipse(xi, yi, ri, ri, bi)
        return c.get()

    def frame(self, t: float) -> np.ndarray:
        w, h = self.w, self.h
        k = self._flicker(t)
        forge = P["red"] * 0.55 + P["ember"] * 0.35
        img = self.amb + forge * (self.resp * 0.55 * k)[..., None]
        # ember bed
        heat = loop_mix(*self.bed_ab, t, n=1) / 1.4
        heat = resize(np.clip(0.40 + 0.45 * heat, 0, 1).astype(np.float32), w, h - self.bed_y)
        ramp_v = smoothstep(0.0, 1.0, (self.ys[self.bed_y:] - self.bed_y) / (h - self.bed_y))
        heat = heat * ramp_v * k
        bed = ramp(np.clip(heat, 0, 1), [(0.0, P["black"] * 0), (0.35, P["red"] * 0.7), (0.65, P["ember"]),
                                         (0.85, P["orange"]), (1.0, P["yellow"])])
        img[self.bed_y:] = 1 - (1 - img[self.bed_y:]) * (1 - bed)
        # sparks with a hot core and a soft glow
        sp = self._sparks(t)
        halo = glow(sp, 6 * self.s, down=2)
        img = 1 - (1 - img) * (1 - P["ember"] * np.clip(halo * 2.2, 0, 1)[..., None])
        col = ramp(np.clip(sp, 0, 1), [(0.0, P["red"]), (0.4, P["orange"]), (0.75, P["yellow"]), (1.0, P["white"])])
        img = img * (1 - sp[..., None]) + col * sp[..., None]
        xs, ys = self.xs, self.ys
        vig = 1 - 0.35 * (((xs / w - 0.5) * 1.4) ** 2 + ((ys / h - 0.55) * 1.2) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(ForgeSparks, "forge-sparks", fps=24, seconds=SECONDS, crf=31, doc=__doc__)
