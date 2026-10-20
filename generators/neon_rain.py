#!/usr/bin/env python3
"""neon-rain: a rainy city at night under neon, in the Tokyo Night palette.

Three skyline layers with lit windows, a few neon signs that pulse and
stutter, slanted rain in three depths, and a wet street that mirrors it all.
Raindrops fall a whole number of screen-heights per loop; window and sign
changes are scheduled per loop, so the clip wraps exactly.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, Canvas, coords, glow, loop_mix, palette, resize, run,  # noqa: E402
                     static_dither, tile_noise, vgradient)

P = palette({
    "night": "#0f0f17", "dark": "#16161e", "bg": "#1a1b26", "storm": "#24283b", "line": "#414868",
    "blue": "#7aa2f7", "cyan": "#7dcfff", "magenta": "#bb9af7", "red": "#f7768e",
    "orange": "#ff9e64", "yellow": "#e0af68", "fg": "#c0caf5",
})


class NeonRain:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.gy = int(0.80 * h)                                    # street line
        self.ys, self.xs = coords(w, h)
        self.dither = static_dither(h, w, seed=43)
        rng = np.random.default_rng(19)
        gy = self.gy
        sky = vgradient(w, gy, [(0.0, P["night"]), (0.55, P["dark"]), (0.85, P["storm"]),
                                (1.0, 0.7 * P["storm"] + 0.3 * P["magenta"] * 0.5)])
        img = sky.copy()
        # skyline layers, far to near: (colour, haze, min/max height, width range, windows)
        self.blinks = []
        layers = [(P["storm"] * 0.75 + P["dark"] * 0.25, (0.25, 0.55), (0.03, 0.07), 0.03),
                  (P["bg"] * 0.85, (0.18, 0.45), (0.05, 0.10), 0.10),
                  (P["night"], (0.08, 0.38), (0.07, 0.15), 0.16)]
        win_cols = [P["yellow"] * 0.85, P["fg"] * 0.8, P["cyan"] * 0.8, P["orange"] * 0.8]
        self.signs = []
        for li, (col, (hmin, hmax), (wmin, wmax), lit) in enumerate(layers):
            mask = Canvas(w, gy, ss=2)
            wins = np.zeros((gy, w, 3), np.float32)
            x = -rng.uniform(0, wmax) * w
            while x < w:
                bw = rng.uniform(wmin, wmax) * w
                bh = rng.uniform(hmin, hmax) * h
                top = gy - bh
                mask.rect(x, top, x + bw, gy)
                if rng.random() < 0.35:                            # roof box / antenna
                    mask.rect(x + bw * 0.2, top - 0.02 * h, x + bw * 0.45, top + 1)
                if rng.random() < 0.3:
                    ax = x + bw * rng.uniform(0.5, 0.9)
                    mask.rect(ax, top - 0.06 * h, ax + 2 * s, top + 1)
                if lit:
                    cw, chh = max(4, int(0.008 * h)), max(4, int(0.012 * h))
                    gap = int(cw * 1.1)
                    for wy in np.arange(top + chh, gy - chh, chh * 1.8):
                        for wx in np.arange(x + gap, x + bw - cw - gap, cw + gap):
                            if not (0 <= wx < w - cw) or rng.random() > lit * (1.4 if li == 2 else 1.0):
                                continue
                            c = win_cols[int(rng.integers(len(win_cols)))] * rng.uniform(0.35, 0.9)
                            wy0, wx0 = int(wy), int(wx)
                            wins[wy0:wy0 + chh, wx0:wx0 + cw] = c
                            if rng.random() < 0.05:
                                self.blinks.append((wy0, wx0, chh, cw, c, int(rng.integers(1, 4)),
                                                    rng.uniform(), rng.uniform(0.3, 0.7)))
                if li == 2 and rng.random() < 0.7 and len(self.signs) < 7:
                    self.signs.append((x, top, bw, bh))
                x += bw + rng.uniform(0.0, 0.02) * w
            m = mask.get()[..., None]
            img = img * (1 - m) + col * m + wins * m
            # haze between layers
            haze = np.exp(-((self.ys[:gy] - gy) / (0.18 * h)) ** 2) * (0.25 if li < 2 else 0.12)
            img = 1 - (1 - img) * (1 - (0.5 * P["magenta"] + 0.5 * P["blue"]) * 0.35 * haze[..., None])
        self.city = img.astype(np.float32)
        # neon signs: vertical bars with a frame, placed on near buildings
        self.sign_layers = []
        sign_cols = [P["magenta"], P["cyan"], P["red"], P["orange"], P["blue"]]
        for i, (bx, top, bw, bh) in enumerate(self.signs):
            c = Canvas(w, gy, ss=2)
            col = sign_cols[i % len(sign_cols)]
            if rng.random() < 0.6:                                 # vertical sign
                sw, sh = 0.028 * h, rng.uniform(0.14, 0.24) * h
                sx = bx + bw * rng.uniform(0.1, 0.6)
                sy = top + rng.uniform(0.04, 0.12) * h
                for k in range(4):                                 # outline
                    pts = [(sx, sy), (sx + sw, sy), (sx + sw, sy + sh), (sx, sy + sh), (sx, sy)]
                    c.line(pts, 1.0, 2.2 * s)
                for j in range(int(sh // (sw * 1.15))):            # glyph-ish bars inside
                    yy = sy + sw * 0.35 + j * sw * 1.15
                    if yy + sw * 0.6 > sy + sh:
                        break
                    if rng.random() < 0.5:
                        c.line([(sx + sw * 0.25, yy), (sx + sw * 0.75, yy)], 1.0, 2.0 * s)
                        c.line([(sx + sw * 0.5, yy), (sx + sw * 0.5, yy + sw * 0.55)], 1.0, 2.0 * s)
                    else:
                        c.line([(sx + sw * 0.25, yy), (sx + sw * 0.75, yy), (sx + sw * 0.75, yy + sw * 0.55),
                                (sx + sw * 0.25, yy + sw * 0.55)], 1.0, 2.0 * s)
            else:                                                  # horizontal bar sign
                sw, sh = rng.uniform(0.08, 0.14) * h, 0.022 * h
                sx = bx + bw * rng.uniform(0.05, 0.4)
                sy = top + rng.uniform(0.05, 0.15) * h
                c.line([(sx, sy), (sx + sw, sy), (sx + sw, sy + sh), (sx, sy + sh), (sx, sy)], 1.0, 2.2 * s)
                c.line([(sx + sh * 0.6, sy + sh / 2), (sx + sw - sh * 0.6, sy + sh / 2)], 1.0, 2.6 * s)
            m = c.get()
            # flicker: a short stutter at one fixed point of the loop for some signs
            stutter = rng.uniform(0.1, 0.9) if rng.random() < 0.5 else None
            self.sign_layers.append((m, glow(m, 14 * s, down=4), col, int(rng.integers(1, 3)),
                                     rng.uniform(), stutter))
        # rain: (x, phase, length, layer)
        self.rain = []
        for depth, n, ln, br, k in ((0, 260, 0.025, 0.10, 2), (1, 200, 0.045, 0.18, 3), (2, 80, 0.09, 0.30, 4)):
            self.rain.append(dict(x=rng.uniform(-0.1, 1.15, n) * w, ph=rng.uniform(0, 1, n),
                                  len=ln * h * rng.uniform(0.7, 1.3, n), b=br * rng.uniform(0.6, 1.0, n),
                                  k=k, width=(0.8, 1.1, 1.6)[depth] * s))
        self.slant = -0.12
        # drifting mist at street level, morphing in place
        self.mist = (tile_noise(h // 8, w // 8, beta=2.8, seed=51, sx=3.0),
                     tile_noise(h // 8, w // 8, beta=2.8, seed=52, sx=3.0))
        self.splash = [(rng.uniform(0, w), rng.uniform(gy + 0.02 * h, h), int(rng.integers(2, 5)), rng.uniform())
                       for _ in range(60)]

    def _rain(self, t: float) -> np.ndarray:
        w, h = self.w, self.h
        c = Canvas(w, h, ss=2)
        span = h * 1.25
        for r in self.rain:
            y = ((r["ph"] + r["k"] * t) % 1.0) * span - 0.12 * h
            for x0, yy, ln, b in zip(r["x"], y, r["len"], r["b"]):
                x = x0 + self.slant * yy
                c.line([(x, yy), (x + self.slant * ln, yy + ln)], b, r["width"])
        for sx, sy, k, ph in self.splash:
            a = (k * t + ph) % 1.0
            if a < 0.18:
                rr = (2 + 40 * a) * self.s
                c.d.ellipse([(sx - rr) * 2, (sy - rr * 0.3) * 2, (sx + rr) * 2, (sy + rr * 0.3) * 2],
                            outline=int(255 * 0.25 * (1 - a / 0.18)), width=2)
        return c.get()

    def frame(self, t: float) -> np.ndarray:
        w, h, gy, s = self.w, self.h, self.gy, self.s
        city = self.city.copy()
        for wy, wx, chh, cw, col, n, ph, duty in self.blinks:
            if (n * t + ph) % 1.0 > duty:
                city[wy:wy + chh, wx:wx + cw] *= 0.25
        glow_acc = np.zeros_like(city)
        for m, g, col, n, ph, stutter in self.sign_layers:
            k = 0.85 + 0.15 * math.sin(TAU * (n * t + ph))
            if stutter is not None:
                d = (t - stutter) % 1.0
                if d < 0.05:
                    k *= 0.15 if int(d * 120) % 2 else 0.9
            core = np.clip(col * 1.15 + 0.25 * m[..., None] ** 2, 0, 1)
            city = city * (1 - (m * k)[..., None]) + core * (m * k)[..., None]
            glow_acc += col * (g * 4.5 * k)[..., None]
        city = 1 - (1 - city) * (1 - np.clip(glow_acc, 0, 1))
        # wet street: blurred, rippled mirror of the city
        rows = np.arange(gy, h)
        src = np.clip(2 * gy - rows - 1, 0, gy - 1)
        dist = (rows - gy) / (h - gy)
        rip = (1.5 + 6 * dist) * s * np.sin(TAU * (rows / (5 * s) - 3 * t))
        xi = np.clip((np.arange(w)[None, :] + rip[:, None]).astype(np.int32), 0, w - 1)
        soft = glow(city, 3 * s, down=2, pad_mode="edge")
        street = soft[src[:, None], xi] * (0.42 - 0.12 * dist)[:, None, None] + P["night"] * 0.6
        img = np.concatenate([city, street], axis=0)
        mist = loop_mix(*self.mist, t, n=1) / 1.4
        mist = resize(np.clip(0.5 + 0.5 * mist, 0, 1).astype(np.float32), w, h)
        band = np.exp(-((self.ys - gy) / (0.10 * h)) ** 2)
        img = 1 - (1 - img) * (1 - P["line"] * (mist * band * 0.45)[..., None])
        rain = self._rain(t)
        img = 1 - (1 - img) * (1 - (0.6 * P["fg"] + 0.4 * P["cyan"]) * rain[..., None])
        xs, ys = self.xs, self.ys
        vig = 1 - 0.32 * (((xs / w - 0.5) * 1.5) ** 2 + ((ys / h - 0.5) * 1.2) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(NeonRain, "neon-rain", fps=24, seconds=8.0, crf=29, doc=__doc__)
