"""Livewall unit tests: no Hyprland, mpv or battery needed.

    python3 -m unittest discover -s tests -v      # from the repository root
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from livewall import backends, cli, config, scenes, system, theme  # noqa: E402
from livewall.daemon import resolve  # noqa: E402


def write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class Env(unittest.TestCase):
    """Each test gets a private HOME/XDG tree and no inherited overrides."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="livewall-test-"))
        self.home = self.tmp / "home"
        self._env = dict(os.environ)
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "LIVEWALL_THEME",
                  "LIVEWALL_SCENES", "LIVEWALL_PACKS", "HYPRLAND_INSTANCE_SIGNATURE"):
            os.environ.pop(k, None)
        os.environ.update(HOME=str(self.home), XDG_RUNTIME_DIR=str(self.tmp / "run"),
                          LIVEWALL_NO_SYSTEMD="1", LIVEWALL_SCENES=str(self.tmp / "scenes"),
                          LIVEWALL_PACKS=str(self.tmp / "packs"))

    def tearDown(self):
        import shutil
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scene(self, name, toml, files=("loop-1080p.mp4",), root=None):
        d = (root or self.tmp / "scenes") / name
        for f in files:
            write(d / f)
        write(d / "scene.toml", toml)
        return d


class SceneTests(Env):
    def test_parse_sizes_and_pick(self):
        d = self.scene("neon", 'theme="Neon Horizon"\nfps=30\n[video]\n1920x1080="a.mp4"\n3840x2160="b.mp4"\n',
                       files=("a.mp4", "b.mp4"))
        s = scenes.parse_scene(d)
        self.assertEqual(s.id, "neon")
        self.assertTrue(s.matches_theme("neon-horizon"))
        self.assertEqual(s.video_for(1920, 1080).name, "a.mp4")
        self.assertEqual(s.video_for(2560, 1440).name, "b.mp4")
        self.assertEqual(s.video_for(7680, 4320).name, "b.mp4")      # largest when none covers
        self.assertEqual(s.video_for().name, "a.mp4")               # unknown output -> 1080p
        self.assertEqual(s.video_for(1920, 1080, force="3840x2160").name, "b.mp4")

    def test_errors(self):
        bad = {
            "nofps": 'theme="x"\nvideo="loop-1080p.mp4"\n',
            "notheme": 'fps=30\nvideo="loop-1080p.mp4"\n',
            "escape": 'theme="x"\nfps=30\nvideo="../../etc/passwd"\n',
            "missing": 'theme="x"\nfps=30\nvideo="nope.mp4"\n',
            "badkey": 'theme="x"\nfps=30\n[video]\nbig="loop-1080p.mp4"\n',
            "nomedia": 'theme="x"\nfps=30\n',
            "badtoml": 'theme = \n',
        }
        for name, toml in bad.items():
            with self.subTest(name):
                with self.assertRaises(scenes.SceneError):
                    scenes.parse_scene(self.scene(name, toml))

    def test_discover_packs_and_skips_broken(self):
        self.scene("good", 'theme="a"\nfps=30\nvideo="loop-1080p.mp4"\n')
        self.scene("broken", 'theme="a"\n')
        pk = self.tmp / "packs" / "mypack"
        write(pk / "pack.toml", 'id="My Pack"\nname="Mine"\n')
        self.scene("glow", 'theme="b"\nfps=24\nvideo="loop-1080p.mp4"\n', root=pk / "scenes")
        errs = []
        found = scenes.discover(errors=errs)
        ids = [s.id for s in found]
        self.assertIn("good", ids)
        self.assertIn("my-pack/glow", ids)
        self.assertNotIn("broken", ids)
        self.assertEqual(len(errs), 1)
        self.assertEqual(scenes.find(found, "glow").id, "my-pack/glow")

    def test_builtin_scenes_are_valid(self):
        errs = []
        found = scenes.discover([ROOT / "scenes"], [], errors=errs)
        self.assertEqual(errs, [])
        self.assertEqual({s.id for s in found}, {"neon-horizon"})
        for s in found:
            self.assertTrue(s.poster and s.poster.is_file(), s.id)
            for v in s.videos.values():
                self.assertGreater(v.stat().st_size, 100_000, f"{v} looks truncated")


class ThemeTests(Env):
    def test_name_file_and_symlink(self):
        write(self.home / ".config/omarchy/current/theme.name", "Neon Horizon\n")
        self.assertEqual(theme.detect_theme().name, "neon-horizon")
        os.remove(self.home / ".config/omarchy/current/theme.name")
        (self.home / ".config/omarchy/themes/steel-and-ember").mkdir(parents=True)
        os.symlink("../themes/steel-and-ember", self.home / ".config/omarchy/current/theme")
        self.assertEqual(theme.detect_theme().name, "steel-and-ember")
        os.environ["LIVEWALL_THEME"] = "Other"
        self.assertEqual(theme.detect_theme().name, "other")

    def test_palette_match(self):
        write(self.home / ".config/omarchy/current/theme/colors.toml", 'background="#1A1029"\naccent="#ff4fa3"\n')
        self.scene("n", 'theme="zzz"\nfps=30\nvideo="loop-1080p.mp4"\n[match]\nbackground="#1a1029"\naccent="#FF4FA3"\n')
        th = theme.detect_theme()
        self.assertIsNone(th.name)
        sc, why = theme.pick_scene(th, scenes.discover())
        self.assertEqual(sc.id, "n")
        self.assertIn("palette", why)

    def test_resolve_override(self):
        self.scene("n", 'theme="neon-horizon"\nfps=30\nvideo="loop-1080p.mp4"\n')
        os.environ["LIVEWALL_THEME"] = "neon-horizon"
        self.assertEqual(resolve(config.Config())[0].id, "n")
        write(self.home / ".config/livewall/scene", "static\n")
        self.assertIsNone(resolve(config.Config())[0])
        write(self.home / ".config/livewall/scene", "gone\n")
        sc, why, _ = resolve(config.Config())
        self.assertIsNone(sc)
        self.assertIn("not found", why)


class ConfigTests(Env):
    def test_defaults_and_validation(self):
        self.assertEqual(config.Config.load(), config.Config())
        write(self.home / ".config/livewall/config.toml",
              'backend="swww"\nlayer="top"\npoll_interval=-1\npause_on_battery=false\nbogus=1\n')
        c = config.Config.load()
        self.assertEqual((c.backend, c.layer, c.poll_interval, c.pause_on_battery),
                         ("swww", "bottom", 3.0, False))
        write(self.home / ".config/livewall/config.toml", "not toml [[[")
        self.assertEqual(config.Config.load(), config.Config())

    def test_default_config_parses(self):
        import tomllib
        tomllib.loads(config.DEFAULT_CONFIG)


class SystemTests(Env):
    def test_outputs_and_fullscreen(self):
        mons = [{"name": "DP-1", "width": 3840, "height": 2160, "activeWorkspace": {"id": 1}},
                {"name": "HDMI-A-1", "width": 1920, "height": 1080, "transform": 1,
                 "activeWorkspace": {"id": 2}, "specialWorkspace": {"id": -98}},
                {"name": "off", "disabled": True}]
        wss = [{"id": 1, "hasfullscreen": False}, {"id": 2, "hasfullscreen": False},
               {"id": -98, "hasfullscreen": True}]
        run = lambda cmd: json.dumps(mons if cmd[-1] == "monitors" else wss)  # noqa: E731
        outs = system.outputs(run)
        self.assertEqual([(o.name, o.width, o.height) for o in outs],
                         [("DP-1", 3840, 2160), ("HDMI-A-1", 1080, 1920)])
        self.assertEqual(system.fullscreen_outputs(run, outs), {"HDMI-A-1"})
        self.assertEqual(system.outputs(lambda cmd: None), [])

    def test_battery(self):
        root = self.tmp / "ps"
        self.assertFalse(system.on_battery(root))                     # no sysfs at all
        write(root / "BAT0/type", "Battery"); write(root / "BAT0/status", "Discharging")
        self.assertTrue(system.on_battery(root))
        write(root / "AC/type", "Mains"); write(root / "AC/online", "0")
        self.assertTrue(system.on_battery(root))
        write(root / "AC/online", "1")
        self.assertFalse(system.on_battery(root))
        write(root / "mouse/type", "Battery"); write(root / "mouse/scope", "Device")
        write(root / "AC/online", "1")
        self.assertFalse(system.on_battery(root))


class BackendTests(Env):
    def test_choose_falls_back_to_static(self):
        s = scenes.parse_scene(self.scene("n", 'theme="a"\nfps=30\nvideo="loop-1080p.mp4"\n'))
        self.assertIs(backends.choose(None), backends.StaticBackend)
        os.environ["PATH"] = str(self.tmp / "empty")                   # no mpvpaper/swww
        backends.GtkBackend._avail = False
        self.assertIs(backends.choose(s), backends.StaticBackend)
        self.assertIs(backends.choose(s, "mpvpaper"), backends.StaticBackend)

    def test_gtk_renderer_present(self):
        self.assertTrue(backends.GtkBackend.renderer().is_file())

    def fake_renderer(self, probe_rc: int, run_rc: int = 0) -> None:
        """A stand-in renderer: --probe exits probe_rc, playing exits run_rc."""
        r = write(self.tmp / "fake_gtk.py",
                  "import sys\n"
                  f"sys.exit({probe_rc} if '--probe' in sys.argv else {run_rc})\n")
        if not hasattr(self, "_orig_renderer"):
            self._orig_renderer = backends.GtkBackend.__dict__["renderer"]
            self.addCleanup(self._restore_gtk)
        backends.GtkBackend.renderer = staticmethod(lambda: r)
        backends.GtkBackend._avail = True
        backends.GtkBackend._decodable = {}

    def _restore_gtk(self):
        backends.GtkBackend.renderer = self._orig_renderer
        backends.GtkBackend._avail = None
        backends.GtkBackend._decodable = {}

    def test_gtk_needs_decodable_video(self):
        s = scenes.parse_scene(self.scene("n", 'theme="a"\nfps=30\nvideo="loop-1080p.mp4"\n'))
        os.environ["PATH"] = str(self.tmp / "empty")
        self.fake_renderer(probe_rc=3)                                  # no qtdemux / H.264
        self.assertFalse(backends.GtkBackend.supports(s))
        self.assertIs(backends.choose(s), backends.StaticBackend)
        self.assertIs(backends.choose(s, "gtk"), backends.StaticBackend)
        self.fake_renderer(probe_rc=0)
        self.assertIs(backends.choose(s), backends.GtkBackend)

    def test_gtk_skips_undecodable_size(self):
        d = self.scene("n", 'theme="a"\nfps=30\n[video]\n1920x1080="a.mp4"\n3840x2160="b.mp4"\n',
                       files=("a.mp4", "b.mp4"))
        s = scenes.parse_scene(d)
        self.fake_renderer(probe_rc=0)
        backends.GtkBackend._decodable = {str(d / "b.mp4"): False}
        self.assertEqual(list(backends.GtkBackend.playable_videos(s).values()), [d / "a.mp4"])

    def test_undecodable_exit_goes_static(self):
        import time
        from livewall.daemon import Daemon
        s = scenes.parse_scene(self.scene("n", 'theme="a"\nfps=30\nvideo="loop-1080p.mp4"\n'))
        self.fake_renderer(probe_rc=0, run_rc=backends.EXIT_UNDECODABLE)
        d = Daemon(cfg=config.Config())
        d.backend = backends.GtkBackend(d.cfg)
        d.backend.start(s, [])
        for p in d.backend.procs.values():
            p.wait(10)
        self.assertTrue(d.backend.undecodable())
        d.check_alive()
        self.assertIsInstance(d.backend, backends.StaticBackend)
        self.assertIn("cannot decode", d.error)
        self.assertEqual(d.failures, 0)                                 # no retry loop


class CliTests(Env):
    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(list(args))
        return rc, buf.getvalue()

    def test_list_set_status(self):
        self.scene("neon-horizon", 'theme="neon-horizon"\nfps=30\nvideo="loop-1080p.mp4"\n')
        os.environ["LIVEWALL_THEME"] = "neon-horizon"
        rc, out = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("* neon-horizon", out)
        rc, out = self.run_cli("status")
        self.assertEqual(rc, 3)                                         # not running
        self.assertIn("would play: neon-horizon", out)
        self.assertEqual(self.run_cli("set", "static")[0], 0)
        self.assertEqual((self.home / ".config/livewall/scene").read_text().strip(), "static")
        self.assertEqual(self.run_cli("set", "nope")[0], 2)
        self.assertEqual(self.run_cli("set", "auto")[0], 0)
        self.assertFalse((self.home / ".config/livewall/scene").exists())
        rc, out = self.run_cli("config")
        self.assertTrue(Path(out.strip()).is_file())


if __name__ == "__main__":
    unittest.main()
