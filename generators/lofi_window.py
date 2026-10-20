#!/usr/bin/env python3
"""lofi-window: a desk by a rainy window at night, in the Gruvbox palette.

A flat, cosy illustration: a lamp, a steaming mug, books, a plant and a cat on
the sill, with a rainy city outside. The room is drawn once; each frame adds
the moving parts. Rain, sliding drops and steam move a whole number of cycles
per loop, distant windows switch on a per-loop schedule, and the cat's tail
sways once per loop.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import (TAU, Canvas, Stars, coords, palette, ramp, roll, run, smoothstep,  # noqa: E402
                     static_dither, tile_noise)

P = palette({
    "bg0h": "#1d2021", "bg": "#282828", "bg1": "#3c3836", "bg2": "#504945", "bg3": "#665c54",
    "fg": "#ebdbb2", "red": "#cc241d", "green": "#98971a", "green2": "#79740e", "yellow": "#d79921",
    "yellow2": "#fabd2f", "blue": "#458588", "blue_dark": "#076678", "aqua": "#689d6a",
    "orange": "#d65d0e", "orange2": "#fe8019", "purple": "#b16286",
})


class LofiWindow:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.s = s = h / 1080.0
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=101)
        rng = np.random.default_rng(13)
        wx0, wx1, wy0, wy1 = 0.40 * w, 0.90 * w, 0.08 * h, 0.66 * h
        self.win = (wx0, wx1, wy0, wy1)
        ft, mt = 0.022 * h, 0.014 * h
        mx, my = (wx0 + wx1) / 2, 0.36 * h
        # --- outside ---
        out = ramp(np.broadcast_to(np.clip((ys - wy0) / (wy1 - wy0), 0, 1), (h, w)),
                   [(0.0, P["bg0h"] * 0.7 + P["blue_dark"] * 0.25), (0.6, P["bg0h"] * 0.5 + P["blue"] * 0.3),
                    (1.0, P["bg1"] * 0.6 + P["purple"] * 0.25)])
        stars = Stars(w, h, 160, seed=3, top=0.08, bottom=0.40, bias=1.0, groups=3)
        self.stars = stars
        mcx, mcy, mr = 0.80 * w, 0.17 * h, 0.035 * h
        md = np.sqrt((xs - mcx) ** 2 + (ys - mcy) ** 2)
        out = 1 - (1 - out) * (1 - P["fg"] * (np.exp(-(md / (3.5 * mr)) ** 2) * 0.25)[..., None])
        moon = smoothstep(mr + 1, mr - 1, md)
        crater = smoothstep(mr * 0.9, mr * 0.2, np.sqrt((xs - mcx - 0.3 * mr) ** 2 + (ys - mcy + 0.2 * mr) ** 2)) * 0.08
        out = out * (1 - moon[..., None]) + P["fg"] * (0.95 - crater[..., None]) * moon[..., None]
        city_lights = []
        for layer, (top_lo, top_hi, col, lit) in enumerate(((0.40, 0.50, P["bg1"] * 0.75 + P["blue_dark"] * 0.2, 0.08),
                                                            (0.47, 0.58, P["bg0h"] * 1.1, 0.16))):
            c = Canvas(w, h, ss=2)
            x = wx0 - 0.02 * w
            while x < wx1:
                bw = rng.uniform(0.025, 0.06) * w
                top = rng.uniform(top_lo, top_hi) * h
                c.rect(x, top, x + bw, wy1 + 1)
                for wy in np.arange(top + 0.012 * h, wy1, 0.022 * h):
                    for wxx in np.arange(x + 0.006 * h, x + bw - 0.012 * h, 0.016 * h):
                        if rng.random() < lit:
                            city_lights.append((wxx, wy, layer, rng.choice([0, 1, 1, 2]),
                                                int(rng.integers(1, 3)), rng.uniform(), rng.random() < 0.12))
                x += bw + rng.uniform(0, 0.01) * w
            m = c.get()
            out = out * (1 - m[..., None]) + col * m[..., None]
        self.lights = city_lights
        self.light_cols = [P["yellow2"] * 0.8, P["orange2"] * 0.75, P["fg"] * 0.6]
        self.outside = out.astype(np.float32)
        # panes: inside the frame and not under the mullions
        panes = ((xs > wx0 + ft) & (xs < wx1 - ft) & (ys > wy0 + ft) & (ys < wy1 - ft)
                 & ~(np.abs(xs - mx) < mt / 2) & ~(np.abs(ys - my) < mt / 2))
        self.panes = panes.astype(np.float32)
        # --- room ---
        lamp = (0.17 * w, 0.56 * h)
        self.lamp = lamp
        ld = np.sqrt(((xs - lamp[0]) / w * 1.6) ** 2 + ((ys - lamp[1]) / h) ** 2)
        wall = ramp(np.clip(ld / 0.9, 0, 1), [(0.0, P["bg2"] * 0.9 + P["yellow"] * 0.12), (0.35, P["bg1"] * 0.85),
                                              (1.0, P["bg0h"] * 0.8)])
        room = wall
        c = Canvas(w, h, ss=2)                                  # window frame
        c.rect(wx0, wy0, wx1, wy1)
        frame = c.get() * (1 - self.panes)
        room = room * (1 - self.panes[..., None]) + self.outside * self.panes[..., None]
        room = room * (1 - frame[..., None]) + (P["bg1"] * 0.9) * frame[..., None]
        c = Canvas(w, h, ss=2)                                  # sill
        c.rect(wx0 - 0.02 * w, wy1, wx1 + 0.02 * w, wy1 + 0.028 * h)
        sill = c.get()
        room = room * (1 - sill[..., None]) + P["bg2"] * sill[..., None]
        dy = 0.80 * h                                           # desk
        desk = (ys >= dy).astype(np.float32) * np.ones((1, w), np.float32)
        dcol = ramp(np.broadcast_to(np.clip((ys - dy) / (h - dy), 0, 1), (h, w)),
                    [(0.0, P["bg3"] * 0.85), (0.08, P["bg2"] * 0.9), (1.0, P["bg1"] * 0.8)])
        room = room * (1 - desk[..., None]) + dcol * desk[..., None]
        shapes = []                                             # (canvas, colour)

        def shape(col, draw):
            cv = Canvas(w, h, ss=2)
            draw(cv)
            shapes.append((cv.get(), col))
        # lamp: base, arm, shade
        shape(P["bg0h"], lambda cv: (cv.ellipse(lamp[0] - 0.01 * w, dy - 0.008 * h, 0.045 * h, 0.012 * h),
                                     cv.line([(lamp[0] - 0.01 * w, dy - 0.01 * h), (lamp[0] - 0.03 * w, 0.62 * h),
                                              (lamp[0], lamp[1] - 0.02 * h)], 1.0, 0.009 * h)))
        shape(P["orange"] * 0.85, lambda cv: cv.polygon([(lamp[0] - 0.045 * h, lamp[1] - 0.06 * h),
                                                         (lamp[0] + 0.03 * h, lamp[1] - 0.075 * h),
                                                         (lamp[0] + 0.085 * h, lamp[1] + 0.02 * h),
                                                         (lamp[0] - 0.02 * h, lamp[1] + 0.04 * h)]))
        # books
        bx = 0.76 * w
        for i, (bw_, bh_, col) in enumerate(((0.16, 0.030, P["blue"]), (0.14, 0.026, P["green"] * 0.9),
                                             (0.15, 0.028, P["yellow"] * 0.9))):
            yb = dy - sum(b for _, b, _ in ((0.16, 0.030, 0), (0.14, 0.026, 0), (0.15, 0.028, 0))[:i]) * h
            shape(col * 0.8, lambda cv, yb=yb, bw_=bw_, bh_=bh_, i=i: cv.rect(bx + i * 0.004 * w, yb - bh_ * h,
                                                                            bx + i * 0.004 * w + bw_ * h, yb))
        # mug
        mx_, mw, mh = 0.62 * w, 0.065 * h, 0.085 * h
        self.mug = (mx_, dy - mh, mw)
        shape(P["red"] * 0.8, lambda cv: (cv.rect(mx_ - mw / 2, dy - mh, mx_ + mw / 2, dy),
                                          cv.ellipse(mx_ - mw / 2, dy - mh / 2, mw * 0.32, mh * 0.28)))
        shape(P["bg1"], lambda cv: cv.ellipse(mx_ - mw / 2, dy - mh / 2, mw * 0.17, mh * 0.15))
        shape(P["bg0h"] * 1.2, lambda cv: cv.ellipse(mx_, dy - mh + 2 * s, mw / 2 - 2 * s, 0.008 * h))
        # plant on the sill
        px_ = wx0 + 0.05 * w
        leaves = Canvas(w, h, ss=2)
        for k in range(9):                                      # tapered, gently curved leaves
            a = -math.pi / 2 + (k - 4) * 0.30 + rng.uniform(-0.1, 0.1)
            ln = rng.uniform(0.08, 0.14) * h
            bend = rng.uniform(-0.5, 0.5)
            left, right = [], []
            for i in range(13):
                u = i / 12
                aa = a + bend * u * u
                cx0 = px_ + math.cos(a) * ln * u + math.cos(aa) * 0.0
                cy0 = wy1 - 0.04 * h + math.sin(a) * ln * u + bend * u * u * 0.03 * h
                hw = 0.012 * h * math.sin(math.pi * min(u * 1.1, 1.0)) + 0.001 * h
                nx, ny = -math.sin(a), math.cos(a)
                left.append((cx0 + nx * hw, cy0 + ny * hw))
                right.append((cx0 - nx * hw, cy0 - ny * hw))
            leaves.polygon(left + right[::-1])
        shapes.append((leaves.get(), P["green2"] * 0.9))
        shape(P["orange"] * 0.7, lambda cv: cv.polygon([(px_ - 0.035 * h, wy1 - 0.055 * h), (px_ + 0.035 * h, wy1 - 0.055 * h),
                                                        (px_ + 0.026 * h, wy1), (px_ - 0.026 * h, wy1)]))
        # cat on the sill (tail drawn per frame)
        cx_, cy_ = 0.82 * w, wy1
        self.cat = (cx_, cy_)
        shape(P["bg0h"] * 0.8, lambda cv: (cv.ellipse(cx_, cy_ - 0.055 * h, 0.05 * h, 0.058 * h),
                                           cv.ellipse(cx_ + 0.004 * h, cy_ - 0.125 * h, 0.032 * h, 0.030 * h),
                                           cv.polygon([(cx_ - 0.028 * h, cy_ - 0.135 * h), (cx_ - 0.022 * h, cy_ - 0.175 * h),
                                                       (cx_ - 0.002 * h, cy_ - 0.148 * h)]),
                                           cv.polygon([(cx_ + 0.010 * h, cy_ - 0.148 * h), (cx_ + 0.030 * h, cy_ - 0.175 * h),
                                                       (cx_ + 0.034 * h, cy_ - 0.133 * h)])))
        front = np.zeros((h, w), np.float32)
        for m, col in shapes:
            room = room * (1 - m[..., None]) + col * m[..., None]
            front = np.maximum(front, m)
        self.glass = (self.panes * (1 - front)).astype(np.float32)   # what can be seen through the glass
        # lamp light: a warm pool on the desk and wall
        cone = np.exp(-(((xs - lamp[0] - 0.05 * w) / (0.16 * w)) ** 2 + ((ys - dy) / (0.10 * h)) ** 2)) * desk
        self.lamp_light = (cone * 0.35 + np.exp(-(ld / 0.22) ** 2) * 0.10).astype(np.float32)
        self.bulb = np.exp(-(((xs - lamp[0] - 0.03 * h) / (0.03 * h)) ** 2 + ((ys - lamp[1] - 0.025 * h) / (0.012 * h)) ** 2)).astype(np.float32)
        self.room = room.astype(np.float32)
        # rain outside and drops on the glass
        self.rain = dict(x=rng.uniform(wx0, wx1 + 0.05 * w, 140), ph=rng.uniform(0, 1, 140),
                         ln=rng.uniform(0.02, 0.04, 140) * h, k=rng.integers(2, 4, 140))
        self.drops = [(rng.uniform(wx0 + ft, wx1 - ft), rng.uniform(wy0 + ft, wy1 - ft),
                       rng.uniform(1.2, 3.2) * s) for _ in range(110)]
        self.sliders = [(rng.uniform(wx0 + ft, wx1 - ft), int(rng.integers(1, 3)), rng.uniform(),
                         rng.uniform(2.5, 4.0) * s) for _ in range(12)]
        # steam: a tile of noise that scrolls up exactly one tile per loop
        self.st_h, self.st_w = int(0.22 * h), int(0.10 * h)
        self.steam = tile_noise(self.st_h, self.st_w, beta=3.4, seed=7)

    def frame(self, t: float) -> np.ndarray:
        w, h, s = self.w, self.h, self.s
        img = self.room.copy()
        wx0, wx1, wy0, wy1 = self.win
        panes = self.glass
        # distant windows switching on and off
        sz = max(2, int(0.007 * h))
        for x, y, layer, ci, n, ph, blinks in self.lights:
            if blinks and (n * t + ph) % 1.0 < 0.35:
                continue
            y0, x0 = int(y), int(x)
            col = self.light_cols[ci] * (0.55 if layer == 0 else 0.9)
            img[y0:y0 + sz, x0:x0 + sz] = np.where(panes[y0:y0 + sz, x0:x0 + sz, None] > 0, col,
                                                   img[y0:y0 + sz, x0:x0 + sz])
        st = self.stars.at(t) * panes * 0.7
        img = 1 - (1 - img) * (1 - P["fg"] * st[..., None])
        # rain outside, drops on the glass
        c = Canvas(w, h, ss=2)
        r = self.rain
        y = wy0 + ((r["ph"] + r["k"] * t) % 1.0) * (wy1 - wy0 + 0.06 * h) - 0.04 * h
        for x0, yy, ln in zip(r["x"], y, r["ln"]):
            c.line([(x0 - 0.15 * (yy - wy0), yy), (x0 - 0.15 * (yy - wy0 + ln), yy + ln)], 0.22, 1.0 * s)
        for dx, dy_, rr in self.drops:
            c.ellipse(dx, dy_, rr, rr * 1.1, 0.35)
        for sx, n, ph, rr in self.sliders:
            u = (n * t + ph) % 1.0
            sy = wy0 + u * (wy1 - wy0)
            fade = smoothstep(0.0, 0.08, u) * smoothstep(1.0, 0.9, u)
            c.line([(sx, sy - 0.05 * h * fade), (sx, sy)], 0.25 * fade, rr * 0.7)
            c.ellipse(sx, sy, rr, rr * 1.2, 0.6 * fade)
        wet = c.get() * panes
        img = 1 - (1 - img) * (1 - (P["fg"] * 0.7 + P["blue"] * 0.3) * wet[..., None])
        # lamp, with the faintest breathing
        k = 1.0 + 0.03 * math.sin(TAU * t)
        img = 1 - (1 - img) * (1 - P["yellow2"] * (self.lamp_light * k)[..., None])
        img = 1 - (1 - img) * (1 - P["fg"] * self.bulb[..., None])
        # steam
        mx_, my_, mw = self.mug
        sh, sw = self.st_h, self.st_w
        field = roll(self.steam, dy=-t * sh)
        yy = np.linspace(1, 0, sh, dtype=np.float32)[:, None]            # 1 at the mug
        xx = np.linspace(-1, 1, sw, dtype=np.float32)[None, :]
        sway = 0.25 * np.sin(TAU * (t + yy * 0.8)) * (1 - yy)
        shape = np.exp(-((xx - sway) / (0.22 + 0.40 * (1 - yy))) ** 2) * smoothstep(0.0, 0.7, yy) * smoothstep(1.0, 0.88, yy)
        dens = np.clip(0.35 + 0.5 * field, 0, 1) * shape * 0.24
        y0, x0 = int(my_ - sh), int(mx_ - sw / 2)
        box = img[y0:y0 + sh, x0:x0 + sw]
        img[y0:y0 + sh, x0:x0 + sw] = 1 - (1 - box) * (1 - P["fg"] * dens[..., None])
        # the cat's tail
        cx_, cy_ = self.cat
        c = Canvas(w, h, ss=2)
        a = 0.35 * math.sin(TAU * t)
        pts = []
        for i in range(12):
            u = i / 11
            ang = -0.3 + a * u * u + 1.4 * u
            pts.append((cx_ + 0.045 * h + 0.11 * h * u * math.cos(ang) * 0.8,
                        cy_ - 0.01 * h - 0.10 * h * u * math.sin(ang) * 0.9))
        c.line(pts, 1.0, 0.014 * h)
        tail = c.get()
        img = img * (1 - tail[..., None]) + (P["bg0h"] * 0.8) * tail[..., None]
        xs, ys = self.xs, self.ys
        vig = 1 - 0.30 * (((xs / w - 0.5) * 1.4) ** 2 + ((ys / h - 0.5) * 1.3) ** 2)
        return np.clip(img * vig[..., None] + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(LofiWindow, "lofi-window", fps=24, seconds=8.0, crf=26, doc=__doc__)
