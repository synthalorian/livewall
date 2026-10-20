#!/usr/bin/env python3
"""Measure a loop's seam: the last->first frame change should look like any
other frame-to-frame change. Prints the ratio; ~1.0 means no visible jump."""
import subprocess
import sys

import numpy as np


def frames(path, w=480, h=270):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)


def main():
    for path in sys.argv[1:]:
        f = frames(path)
        d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2, 3))
        seam = np.abs(f[0] - f[-1]).mean()
        print(f"{path}: {len(f)} frames, step mean {d.mean():.3f} max {d.max():.3f}, "
              f"seam {seam:.3f}, ratio {seam / max(d.mean(), 1e-6):.2f}")


if __name__ == "__main__":
    main()
