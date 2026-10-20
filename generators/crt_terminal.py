#!/usr/bin/env python3
"""crt-terminal: a green phosphor terminal typing and scrolling on an old CRT.

Text uses a 5x7 bitmap font defined below, so no system font is needed. The
session is a fixed list of lines that is typed and scrolled through exactly
once per loop; the screen at the end of the loop is the screen at the start.
Scanlines, bloom, a rolling refresh band and a curved glass edge finish it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopkit import TAU, coords, glow, palette, run, smoothstep, static_dither  # noqa: E402

P = palette({
    "bezel": "#060709", "glass": "#0b0c16", "phosphor": "#7dfc9c", "hot": "#d8ffe4", "dim": "#1f5a35",
})
SECONDS = 12.0

FONT = {
    "A": ".###.#...##...#######...##...##...#", "B": "####.#...##...#####.#...##...#####.",
    "C": ".###.#...##....#....#....#...#.###.", "D": "####.#...##...##...##...##...#####.",
    "E": "######....#....####.#....#....#####", "F": "######....#....####.#....#....#....",
    "G": ".###.#...##....#.####...##...#.####", "H": "#...##...##...#######...##...##...#",
    "I": ".###...#....#....#....#....#...###.", "J": "..###...#....#....#....#.#..#..##..",
    "K": "#...##..#.#.#..##...#.#..#..#.#...#", "L": "#....#....#....#....#....#....#####",
    "M": "#...###.###.#.##...##...##...##...#", "N": "#...###..##.#.##..###...##...##...#",
    "O": ".###.#...##...##...##...##...#.###.", "P": "####.#...##...#####.#....#....#....",
    "Q": ".###.#...##...##...##.#.##..#..##.#", "R": "####.#...##...#####.#.#..#..#.#...#",
    "S": ".#####....#.....###.....#....#####.",
    "T": "#####..#....#....#....#....#....#..", "U": "#...##...##...##...##...##...#.###.",
    "V": "#...##...##...##...##...#.#.#...#..", "W": "#...##...##...##.#.##.#.##.#.#.#.#.",
    "X": "#...##...#.#.#...#...#.#.#...##...#", "Y": "#...##...#.#.#...#....#....#....#..",
    "Z": "#####....#...#...#...#...#....#####",
    "0": ".###.#...##..###.#.###..##...#.###.", "1": "..#...##....#....#....#....#...###.",
    "2": ".###.#...#....#...#...#...#...#####", "3": "#####...#...#.....#.....##...#.###.",
    "4": "...#...##..#.#.#..#.#####...#....#.", "5": "######....####.....#....##...#.###.",
    "6": "..##..#...#....####.#...##...#.###.", "7": "#####....#...#...#...#....#....#...",
    "8": ".###.#...##...#.###.#...##...#.###.", "9": ".###.#...##...#.####....#...#..##..",
    " ": "." * 35, ".": "." * 30 + "..#..", ",": "." * 25 + "..#....#..",
    ":": "......##...##........##...##.......",
    "-": "." * 15 + "#####" + "." * 15, "_": "." * 30 + "#####",
    "/": "....#....#...#...#...#...#....#....", "[": ".###..#....#....#....#....#....###.",
    "]": ".###....#....#....#....#....#..###.", ">": ".#.....#.....#.....#...#...#...#...",
    "<": "...#...#...#...#.....#.....#.....#.", "=": "." * 10 + "#####" + "." * 5 + "#####" + "." * 10,
    "+": "." * 5 + "..#....#..#####..#....#.." + "." * 5, "#": ".#.#..#.#.#####.#.#.#####.#.#..#.#.",
    "%": "##...##..#...#...#...#...#..##...##", "*": ".....#.#.#.###.#####.###.#.#.#.....",
    "|": "..#....#....#....#....#....#....#..", "'": "..#....#...#.......................",
    "(": "...#...#...#....#....#.....#.....#.", ")": ".#.....#.....#....#....#...#...#...",
}
CHARS = "".join(FONT)

VERBS = ["SCAN", "SYNC", "MOUNT", "TRACE", "PATCH", "INDEX", "VERIFY", "ROUTE", "COMPILE", "PROBE"]
NOUNS = ["SECTOR", "RELAY", "ARRAY", "CACHE", "UPLINK", "NODE", "LATTICE", "VAULT", "BUFFER", "BEACON"]
STATES = ["OK", "OK", "OK", "DONE", "WAIT", "SKIP"]


def session(n: int, cols: int, seed: int) -> list[tuple[str, bool]]:
    """n lines of plausible terminal chatter: (text, typed?)."""
    rng = np.random.default_rng(seed)
    out: list[tuple[str, bool]] = []
    while len(out) < n:
        v, o = rng.choice(VERBS), rng.choice(NOUNS)
        out.append((f"> {v} {o}-{rng.integers(0, 256):02X}", True))
        for _ in range(int(rng.integers(2, 5))):
            kind = rng.random()
            if kind < 0.35:
                addr = rng.integers(0, 1 << 16)
                data = " ".join(f"{b:02X}" for b in rng.integers(0, 256, 8))
                out.append((f"  {addr:04X}  {data}", False))
            elif kind < 0.65:
                st = rng.choice(STATES)
                out.append((f"[{st:^6}] {rng.choice(NOUNS)} {rng.integers(1, 99):02d} {rng.choice(VERBS)}", False))
            else:
                pct = int(rng.integers(5, 101))
                bar = "#" * (pct // 5) + "." * (20 - pct // 5)
                out.append((f"  {rng.choice(NOUNS):<8}[{bar}] {pct:3d}%", False))
    return [(text[:cols - 1], typed) for text, typed in out[:n]]


class CRTTerminal:
    def __init__(self, w: int, h: int, seconds: float = SECONDS):
        self.w, self.h, self.T = w, h, seconds
        s = h / 1080.0
        self.px = max(2, int(round(4 * s)))                   # screen pixels per font pixel
        self.cw, self.ch = 6, 9                               # font cell in font pixels
        margin_x, margin_y = int(0.09 * w), int(0.10 * h)
        self.cols = (w - 2 * margin_x) // (self.cw * self.px)
        self.rows = (h - 2 * margin_y) // (self.ch * self.px)
        self.ox = (w - self.cols * self.cw * self.px) // 2
        self.oy = (h - self.rows * self.ch * self.px) // 2
        # font atlas: (n_chars, 9, 6) with one blank column and two blank rows
        self.atlas = np.zeros((len(CHARS) + 1, self.ch, self.cw), np.float32)
        for i, c in enumerate(CHARS):
            g = np.array([ch == "#" for ch in FONT[c]], np.float32).reshape(7, 5)
            self.atlas[i, 1:8, 0:5] = g
        self.atlas[-1, 0:8, 0:5] = 1.0                        # cursor block
        self.index = {c: i for i, c in enumerate(CHARS)}
        # one loop = this session, typed and scrolled through once
        self.lines = session(max(self.rows + 6, 32), self.cols, seed=5)
        dur = np.array([0.55 + len(txt) / 16.0 if typed else 0.16 + 0.10 * (len(txt) % 3)
                        for txt, typed in self.lines])
        self.dur = dur / dur.sum() * seconds
        self.start = np.concatenate([[0], np.cumsum(self.dur)[:-1]])
        self.ys, self.xs = ys, xs = coords(w, h)
        self.dither = static_dither(h, w, seed=73)
        # curved glass: sample positions for each output pixel, and the screen mask
        u = (xs / w - 0.5) * 2
        v = (ys / h - 0.5) * 2
        r2 = (u * 0.9) ** 2 + v ** 2
        k = 1 + 0.045 * r2
        su, sv = u * k, v * k
        self.map_x = np.clip(((su / 2 + 0.5) * w), 0, w - 1).astype(np.int32)
        self.map_y = np.clip(((sv / 2 + 0.5) * h), 0, h - 1).astype(np.int32)
        ax, ay = np.abs(su), np.abs(sv)
        corner = np.sqrt(np.maximum(ax - 0.90, 0) ** 2 + np.maximum(ay - 0.86, 0) ** 2)
        inside = smoothstep(0.012, 0.0, np.maximum(np.maximum(ax - 1, ay - 1), corner - 0.08))
        self.inside = inside.astype(np.float32)
        self.glass_v = (1 - 0.55 * (su ** 2 * 0.5 + sv ** 2 * 0.6)).astype(np.float32)
        self.scan = (0.72 + 0.28 * (np.cos(TAU * (ys / self.px)) * 0.5 + 0.5)).astype(np.float32)

    def _text(self, t: float) -> np.ndarray:
        tau = (t * self.T + 0.5 * self.dur[0]) % self.T      # no scroll right at the wrap
        M = len(self.lines)
        i = int(np.searchsorted(self.start, tau, side="right") - 1)
        prog = tau - self.start[i]
        R, C = self.rows, self.cols
        grid = np.full((R, C), self.index[" "], np.int64)
        for r in range(R):
            j = (i - (R - 1 - r)) % M
            txt, typed = self.lines[j]
            if r == R - 1 and typed:
                n = int(max(0.0, prog - 0.35) * 16.0)
                txt = txt[:min(n, len(txt))]
            for c, ch in enumerate(txt[:C]):
                grid[r, c] = self.index.get(ch, self.index[" "])
            if r == R - 1:
                cur = min(len(txt) + (0 if typed else -len(txt)), C - 1)
                if typed and int(tau * 2.0) % 2 == 0:
                    grid[r, cur] = len(CHARS)
        g = self.atlas[grid]                                         # R, C, 9, 6
        bits = g.transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)
        return bits

    def frame(self, t: float) -> np.ndarray:
        w, h, px = self.w, self.h, self.px
        bits = self._text(t)
        text = np.kron(bits, np.ones((px, px), np.float32))
        screen = np.zeros((h, w), np.float32)
        th, tw = text.shape
        screen[self.oy:self.oy + th, self.ox:self.ox + tw] = text
        bloom = glow(screen, 5 * px, down=4)
        lum = screen * self.scan + bloom * 0.9
        # rolling refresh band, twice per loop
        band_y = ((2 * t) % 1.0) * 1.3 - 0.15
        band = np.exp(-((self.ys / h - band_y) / 0.05) ** 2) * 0.10
        lum = lum * (1 + band) + band * 0.12
        lum = lum[self.map_y, self.map_x]
        img = (P["glass"][None, None, :] * 1.15 + P["dim"] * 0.06
               + P["phosphor"] * np.clip(lum, 0, 1.2)[..., None] * 0.9
               + P["hot"] * np.clip(lum - 0.85, 0, 1)[..., None] * 0.6)
        img = img * self.glass_v[..., None]
        img = img * self.inside[..., None] + P["bezel"] * (1 - self.inside[..., None])
        # a soft reflection on the glass, top left
        refl = np.exp(-(((self.xs / w - 0.25) / 0.30) ** 2 + ((self.ys / h - 0.18) / 0.16) ** 2)) * 0.035
        img = img + refl[..., None] * self.inside[..., None]
        return np.clip(img + self.dither, 0, 1).astype(np.float32)


if __name__ == "__main__":
    run(CRTTerminal, "crt-terminal", fps=24, seconds=SECONDS, crf=27, doc=__doc__)
