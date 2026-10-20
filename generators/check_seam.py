#!/usr/bin/env python3
"""Measure a loop's seam: the last->first frame change should look like any
other frame-to-frame change. Prints the ratio; ~1.0 means no visible jump.

Two scales are measured. At 480x270 the numbers include codec noise: a loop
has one keyframe, so in slow scenes the seam there is mostly the keyframe's
noise differing from the last P-frame's. At 120x68 that fine noise averages
out and what is left is structure (positions, brightness), which is what a
visible jump is made of. The verdict uses the coarse scale: the seam must be
no larger than the largest ordinary frame step (plus 10% for noise), unless
it is under a quarter of a grey level on average, which nothing can show.
That floor matters only for near-still scenes, where every step is tiny.

    check_seam.py loop.mp4 [...]      exit status 1 if any file has a jump
"""
import subprocess
import sys

import numpy as np


def frames(path, w=480, h=270):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)


def measure(path, w, h):
    f = frames(path, w, h)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2, 3))
    seam = np.abs(f[0] - f[-1]).mean()
    return len(f), d.mean(), d.max(), seam


def main():
    bad = 0
    for path in sys.argv[1:]:
        n, mean, mx, seam = measure(path, 480, 270)
        print(f"{path}: {n} frames, step mean {mean:.3f} max {mx:.3f}, "
              f"seam {seam:.3f}, ratio {seam / max(mean, 1e-6):.2f}")
        _, cmean, cmx, cseam = measure(path, 120, 68)
        ok = cseam <= 1.1 * cmx or cseam < 0.25
        bad += not ok
        print(f"  coarse: step mean {cmean:.3f} max {cmx:.3f}, seam {cseam:.3f}, "
              f"ratio {cseam / max(cmean, 1e-6):.2f} -> {'ok' if ok else 'JUMP'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
