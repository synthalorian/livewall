"""Can GStreamer (and so GTK's GtkMediaFile) play this video file?

GTK + layer-shell being importable proves nothing about decoding: without a
demuxer or decoder GtkMediaFile paints a flat grey panel. This module works out
what the file needs (container + codec, sniffed from the file itself, with no
GStreamer involved), checks that those elements exist, and finally asks
gst-discoverer to confirm the file really decodes.

    python3 -m livewall.gstprobe [--json] FILE...   exit 0 = all playable, 3 = not

The element lookup is injectable (`have=`) so the tests run without GStreamer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

EXIT_UNDECODABLE = 3

# What each container / codec needs, as (label, candidate elements, packages).
CONTAINERS = {
    "mp4": ("MP4 demuxer", ["qtdemux"], "gst-plugins-good"),
    "matroska": ("WebM/Matroska demuxer", ["matroskademux"], "gst-plugins-good"),
}
CODECS = {
    "h264": ("H.264 decoder",
             ["avdec_h264", "vah264dec", "vaapih264dec", "openh264dec", "nvh264dec",
              "v4l2slh264dec", "v4l2h264dec"],
             "gst-libav or gst-plugin-va"),
    "hevc": ("H.265 decoder", ["avdec_h265", "vah265dec", "vaapih265dec", "nvh265dec"],
             "gst-libav or gst-plugin-va"),
    "vp9": ("VP9 decoder", ["vp9dec", "avdec_vp9", "vavp9dec", "vaapivp9dec", "nvvp9dec"],
            "gst-plugins-good"),
    "vp8": ("VP8 decoder", ["vp8dec", "avdec_vp8", "vavp8dec"], "gst-plugins-good"),
    "av1": ("AV1 decoder", ["dav1ddec", "av1dec", "vaav1dec", "nvav1dec", "avdec_av1"],
            "gst-plugins-rs (dav1d) or gst-plugin-va"),
}
CORE = [("GStreamer playback (playbin)", ["playbin"], "gst-plugins-base"),
        ("video converter (videoconvert)", ["videoconvert"], "gst-plugins-base")]

MP4_CODECS = {b"avc1": "h264", b"avc3": "h264", b"hvc1": "hevc", b"hev1": "hevc",
              b"vp09": "vp9", b"vp08": "vp8", b"av01": "av1"}
MKV_CODECS = {b"V_MPEG4/ISO/AVC": "h264", b"V_MPEGH/ISO/HEVC": "hevc", b"V_VP9": "vp9",
              b"V_VP8": "vp8", b"V_AV1": "av1"}


@dataclass
class Need:
    what: str
    elements: list[str]
    packages: str

    def text(self) -> str:
        return f"{self.what} ({' / '.join(self.elements[:3])}; install {self.packages})"


@dataclass
class Result:
    path: str
    ok: bool
    container: str | None = None
    codec: str | None = None
    missing: list[Need] = field(default_factory=list)
    error: str = ""

    @property
    def reason(self) -> str:
        """One line for `livewall status`: names what is missing."""
        if self.ok:
            return f"{self.container}/{self.codec} decodes"
        if self.missing:
            return "missing " + ", ".join(n.text() for n in self.missing)
        return self.error or "cannot decode"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reason"] = self.reason
        return d


# ------------------------------------------------------------------ sniffing
def sniff(path: Path, limit: int = 4 << 20) -> tuple[str | None, str | None]:
    """(container, codec) from the file bytes. MP4: the stsd sample entry
    fourcc; Matroska/WebM: the CodecID string."""
    with open(path, "rb") as f:
        head = f.read(limit)
        if len(head) < 12:
            return None, None
        if head[:4] == b"\x1a\x45\xdf\xa3":
            for tag, codec in MKV_CODECS.items():
                if tag in head:
                    return "matroska", codec
            return "matroska", None
        if head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"):
            data = head
            if b"stsd" not in data:          # moov at the end (no faststart)
                try:
                    f.seek(-limit, 2)
                except OSError:
                    f.seek(0)
                data = f.read(limit)
            i = data.find(b"stsd")
            if i >= 0:
                entry = data[i + 16:i + 24]       # version/flags, count, size, fourcc
                fourcc = entry[4:8]
                if fourcc in MP4_CODECS:
                    return "mp4", MP4_CODECS[fourcc]
                for k, v in MP4_CODECS.items():   # tolerate odd layouts
                    if k in data[i:i + 256]:
                        return "mp4", v
            return "mp4", None
    return None, None


def needs(container: str | None, codec: str | None) -> list[Need]:
    out = [Need(*c) for c in CORE]
    if container in CONTAINERS:
        out.append(Need(*CONTAINERS[container]))
    if codec in CODECS:
        out.append(Need(*CODECS[codec]))
    return out


# --------------------------------------------------------- element lookups
def _gst():
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        return Gst
    except (ImportError, ValueError):
        return None


def default_have() -> Callable[[str], bool]:
    """Element lookup through the Gst bindings, else gst-inspect-1.0."""
    Gst = _gst()
    if Gst is not None:
        return lambda name: Gst.ElementFactory.find(name) is not None
    if shutil.which("gst-inspect-1.0"):
        def have(name: str) -> bool:
            try:
                return subprocess.run(["gst-inspect-1.0", "--exists", name], capture_output=True,
                                      timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError):
                return False
        return have
    return lambda name: False


def discover(path: Path, timeout_s: float = 8.0) -> str:
    """'' if gst-discoverer decodes the file, else the error text."""
    Gst = _gst()
    if Gst is None:
        return ""        # elements were found by gst-inspect; trust them
    try:
        import gi
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import GstPbutils
        info = GstPbutils.Discoverer.new(int(timeout_s * Gst.SECOND)).discover_uri(path.resolve().as_uri())
    except Exception as e:      # GLib.Error: missing plugin, unreadable, timeout
        return f"gst-discoverer: {getattr(e, 'message', e)}"
    if info.get_result() != GstPbutils.DiscovererResult.OK:
        return f"gst-discoverer: {info.get_result().value_nick}"
    if not info.get_video_streams():
        return "gst-discoverer: no video stream"
    return ""


def check(path: Path | str, have: Callable[[str], bool] | None = None,
          confirm: Callable[[Path], str] | None = discover) -> Result:
    path = Path(path)
    try:
        container, codec = sniff(path)
    except OSError as e:
        return Result(str(path), False, error=f"cannot read {path.name}: {e.strerror}")
    if container is None:
        return Result(str(path), False, error=f"{path.name}: unknown container")
    if codec is None:
        return Result(str(path), False, container, error=f"{path.name}: unknown video codec")
    have = have or default_have()
    missing = [n for n in needs(container, codec) if not any(have(e) for e in n.elements)]
    if missing:
        return Result(str(path), False, container, codec, missing)
    err = confirm(path) if confirm else ""
    return Result(str(path), not err, container, codec, error=err)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    files = [a for a in argv if a != "--json"]
    if not files:
        print("usage: python3 -m livewall.gstprobe [--json] FILE...", file=sys.stderr)
        return 2
    results = [check(f) for f in files]
    if as_json:
        print(json.dumps([r.to_dict() for r in results]))
    else:
        for r in results:
            print(f"{'ok ' if r.ok else 'NO '} {r.path}: {r.reason}")
    return 0 if all(r.ok for r in results) else EXIT_UNDECODABLE


if __name__ == "__main__":
    sys.exit(main())
