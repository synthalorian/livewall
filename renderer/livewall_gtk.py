#!/usr/bin/env python3
"""Fallback Livewall player: one GTK4 layer-shell surface per output.

Used by the `gtk` backend when mpvpaper is not installed. Plays a looping video
(GtkMediaFile, which uses GStreamer) or a frame sequence, fills the output
(cover), and never takes input or keyboard focus.

    livewall_gtk.py --video loop.mp4 [--output DP-1] [--layer bottom]
    livewall_gtk.py --frames f0001.png f0002.png ... --fps 30
    livewall_gtk.py --probe loop.mp4      # exit 0 only if GStreamer can play it

A video surface is shown only once GStreamer has opened the file. If the video
fails to open, decode or reach its first frame within --prepare-timeout
seconds, the player exits with code 3 (EXIT_UNDECODABLE) without ever covering
the wallpaper, and the daemon falls back to static.

SIGUSR1 pauses (holds the current frame), SIGUSR2 resumes, SIGTERM/SIGINT quit.
gtk4-layer-shell must be loaded before libwayland-client; the backend sets
LD_PRELOAD for that.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

import gi

EXIT_UNDECODABLE = 3


def probe(video: str, timeout_s: float = 8.0) -> int:
    """0 if GStreamer can demux and decode every video stream in the file,
    EXIT_UNDECODABLE otherwise (missing qtdemux or H.264 decoder, broken file)."""
    try:
        gi.require_version("Gst", "1.0")
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import Gst, GstPbutils
    except (ValueError, ImportError) as e:
        print(f"livewall_gtk: GStreamer bindings missing: {e}", file=sys.stderr)
        return EXIT_UNDECODABLE
    Gst.init(None)
    try:
        info = GstPbutils.Discoverer.new(int(timeout_s * Gst.SECOND)).discover_uri(
            Path(video).resolve().as_uri())
    except Exception as e:  # GLib.Error: missing plugin, unreadable file, timeout
        print(f"livewall_gtk: cannot decode {video}: {e}", file=sys.stderr)
        return EXIT_UNDECODABLE
    if info.get_result() != GstPbutils.DiscovererResult.OK or not info.get_video_streams():
        missing = ", ".join(info.get_missing_elements_installer_details() or []) or "-"
        print(f"livewall_gtk: cannot decode {video}: {info.get_result().value_nick} "
              f"(missing: {missing})", file=sys.stderr)
        return EXIT_UNDECODABLE
    return 0


def _signal_add(sig, cb):
    """Unix signal source without PyGObject's GLib.unix_signal_add deprecation:
    GLibUnix (GLib >= 2.80) first, the old GLib name only on older systems."""
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
    except (ValueError, ImportError):
        return GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, cb)
    add = getattr(GLibUnix, "signal_add", None) or GLibUnix.signal_add_full
    return add(GLib.PRIORITY_DEFAULT, sig, cb)


if __name__ == "__main__" and "--probe" in sys.argv[1:]:
    _i = sys.argv.index("--probe")
    if _i + 1 >= len(sys.argv):
        sys.exit("livewall_gtk: --probe needs a file")
    sys.exit(probe(sys.argv[_i + 1]))

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS  # noqa: E402


def find_monitor(name: str | None):
    if not name:
        return None
    mons = Gdk.Display.get_default().get_monitors()
    for i in range(mons.get_n_items()):
        m = mons.get_item(i)
        if m.get_connector() == name:
            return m
    return None


class Player:
    def __init__(self, a):
        self.a = a
        self.paused = False
        self.media = None
        self.frames: list[Gdk.Texture] = []
        self.idx = 0
        self.timer = 0
        self.win = None
        self.exit_code = 0
        self.app = Gtk.Application(application_id=None)
        self.app.connect("activate", self.activate)

    def activate(self, app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_decorated(False)
        win.set_can_focus(False)
        LS.init_for_window(win)
        LS.set_namespace(win, "livewall")
        LS.set_layer(win, LS.Layer.BACKGROUND if self.a.layer == "background" else LS.Layer.BOTTOM)
        for edge in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(win, edge, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        mon = find_monitor(self.a.output)
        if self.a.output and mon is None:
            print(f"livewall_gtk: output {self.a.output} not found", file=sys.stderr)
            app.quit()
            return
        if mon is not None:
            LS.set_monitor(win, mon)

        pic = Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_can_target(False)
        win.set_child(pic)
        self.win = win
        for sig, fn in ((signal.SIGUSR1, lambda: self.pause(True)),
                        (signal.SIGUSR2, lambda: self.pause(False)),
                        (signal.SIGTERM, self.quit), (signal.SIGINT, self.quit)):
            _signal_add(sig, self._wrap(fn))

        if self.a.video:
            # Not presented until the stream is prepared and has a frame, so a
            # player that cannot decode never paints a grey panel over the wallpaper.
            self.media = Gtk.MediaFile.new_for_filename(self.a.video)
            self.media.set_loop(True)
            self.media.set_muted(True)
            pic.set_paintable(self.media)
            self.media.connect("notify::error", self._on_media)
            self.media.connect("notify::prepared", self._on_media)
            self.media.connect("invalidate-contents", self._on_media)
            GLib.timeout_add_seconds(max(1, round(self.a.prepare_timeout)), self._prepare_timeout)
            self.media.play()
        else:
            self.frames = [Gdk.Texture.new_from_filename(f) for f in self.a.frames]
            pic.set_paintable(self.frames[0])
            self.pic = pic
            self.timer = GLib.timeout_add(max(1, round(1000 / self.a.fps)), self.tick)
            win.present()

    def _ready(self) -> bool:
        m = self.media
        return (m is not None and m.get_error() is None and m.is_prepared()
                and m.has_video() and m.get_intrinsic_width() > 0)

    def _on_media(self, *_):
        if self.media.get_error() is not None:
            self.fail(f"cannot play {self.a.video}: {self.media.get_error().message}")
        elif self._ready() and not self.win.get_visible():
            self.win.present()

    def _prepare_timeout(self):
        if not self._ready():
            self.fail(f"{self.a.video} did not reach a first frame in "
                      f"{self.a.prepare_timeout:g}s (missing demuxer or decoder?)")
        return GLib.SOURCE_REMOVE

    def fail(self, msg: str):
        if self.exit_code:
            return
        print(f"livewall_gtk: {msg}; exiting so Livewall falls back to static", file=sys.stderr)
        self.exit_code = EXIT_UNDECODABLE
        if self.win is not None:
            self.win.set_visible(False)
        self.app.quit()

    @staticmethod
    def _wrap(fn):
        def cb(*_):
            fn()
            return GLib.SOURCE_CONTINUE
        return cb

    def tick(self):
        if not self.paused and self.frames:
            self.idx = (self.idx + 1) % len(self.frames)
            self.pic.set_paintable(self.frames[self.idx])
        return GLib.SOURCE_CONTINUE

    def pause(self, on: bool):
        self.paused = on
        if self.media is not None:
            self.media.pause() if on else self.media.play()

    def quit(self):
        self.app.quit()

    def run(self) -> int:
        self.app.hold()          # stay alive while the surface exists
        rc = self.app.run([sys.argv[0]])
        return self.exit_code or rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Livewall GTK4 layer-shell player")
    ap.add_argument("--output", help="connector name, e.g. DP-1 (default: compositor's choice)")
    ap.add_argument("--layer", choices=("background", "bottom"), default="bottom")
    ap.add_argument("--fps", type=float, default=30.0, help="frame-sequence rate")
    ap.add_argument("--prepare-timeout", type=float, default=10.0,
                    help="seconds a video may take to show its first frame")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video")
    src.add_argument("--frames", nargs="+")
    return Player(ap.parse_args(argv)).run()


if __name__ == "__main__":
    sys.exit(main())
