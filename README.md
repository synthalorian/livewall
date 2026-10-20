# Livewall

Animated, palette-matched wallpapers for Hyprland / Omarchy. Livewall follows the
active Omarchy theme and plays that theme's seamless loop on the wallpaper layer.
It pauses while a window is fullscreen or the machine is on battery. If there is
no scene for the theme, no player is installed, or you ran `livewall set static`,
it draws nothing and your normal static background shows.

![Livewall: Neon Horizon](scenes/neon-horizon/poster.jpg)

Preview clip: [`scenes/neon-horizon/loop-1080p.webm`](scenes/neon-horizon/loop-1080p.webm).

## Requirements

- Hyprland (Omarchy for automatic theme following)
- Python 3.11+
- One player:
  - **mpvpaper** (recommended), or
  - GTK4 + gtk4-layer-shell + PyGObject (the bundled `renderer/livewall_gtk.py`),
    which plays video through GStreamer, so it also needs `gst-plugins-good` and an
    H.264 decoder (`gst-libav` or `gst-plugin-va`), or
  - **swww**, for GIF scenes only

`install.sh` tells you if a player or GStreamer plugin is missing.

## Install

```bash
git clone https://github.com/synthalorian/livewall.git
cd livewall
./install.sh            # install for the current user
./install.sh --enable   # same, and also enable + start the systemd user unit
```

The installer needs no root and touches only these paths:

| Path | What |
|---|---|
| `~/.local/share/livewall/` | the program, GTK player, built-in scenes, README |
| `~/.local/bin/livewall` | the `livewall` command |
| `~/.config/systemd/user/livewall.service` | systemd user unit (skip with `--no-systemd`) |

Plain `./install.sh` copies the unit but doesn't enable it, so nothing runs until
you `livewall start` (or install with `--enable`). It will not overwrite an
existing `~/.local/bin/livewall` that isn't Livewall's. Make sure `~/.local/bin`
is on your `PATH`.

At run time Livewall also uses `~/.config/livewall/` (config, chosen scene, your
scenes) and `~/.local/state/livewall/livewall.log`.

## Usage

```
livewall start [--foreground] [--no-systemd]   start the daemon
livewall stop                                  stop; the static background returns
livewall status [--json]                       what is playing and why
livewall list                                  installed scenes (* = current)
livewall set <scene> | auto | static           pick a scene, follow the theme, or turn off
livewall config                                create/print ~/.config/livewall/config.toml
```

The scene is picked by theme name first (`theme.name` or the `current/theme` symlink,
or `$LIVEWALL_THEME`), then by palette (`[match]` keys compared with the theme's
`colors.toml`).

`livewall config` writes a commented default config. Options: `backend`
(`auto`, `mpvpaper`, `gtk`, `swww`, `static`), `layer` (`bottom` or `background`),
`pause_on_fullscreen`, `pause_on_battery`, `resolution` (`auto` or e.g. `3840x2160`),
`poll_interval` and `mpv_options`.

## Scenes

| Scene | Theme | Loops | Source |
|---|---|---|---|
| `neon-horizon` | Neon Horizon | 1080p, 2160p (8 s, 30 fps) | fully procedural, `generators/neon_horizon.py` |

### Presets

Twelve more built-in scenes, each matched to an Omarchy theme. They are all fully
procedural (one generator script each, no footage or fonts) and built to be light:
one 1080p H.264 loop of 8 to 12 s at 24 fps, around 1 MB, that plays on any output
size. Each one wraps seamlessly; `generators/check_seam.py` checks that.

| Preview | Scene | Themes | Loop | Generator |
|---|---|---|---|---|
| <img src="scenes/sunset-drive/poster.jpg" width="240" alt="Sunset Drive"> | `sunset-drive`<br>wireframe mountains, low sun | catppuccin | 10 s | `sunset_drive.py` |
| <img src="scenes/neon-rain/poster.jpg" width="240" alt="Neon Rain"> | `neon-rain`<br>rainy city under neon | tokyo-night | 8 s | `neon_rain.py` |
| <img src="scenes/nebula-drift/poster.jpg" width="240" alt="Nebula Drift"> | `nebula-drift`<br>stars drifting past a nebula | ethereal | 8 s | `nebula_drift.py` |
| <img src="scenes/aurora/poster.jpg" width="240" alt="Aurora"> | `aurora`<br>polar lights over a lake | nord | 10 s | `aurora.py` |
| <img src="scenes/ocean-dusk/poster.jpg" width="240" alt="Ocean Dusk"> | `ocean-dusk`<br>rolling sea at dusk | kanagawa | 8 s | `ocean_dusk.py` |
| <img src="scenes/crt-terminal/poster.jpg" width="240" alt="CRT Terminal"> | `crt-terminal`<br>phosphor terminal, scanlines | hackerman | 12 s | `crt_terminal.py` |
| <img src="scenes/forge-sparks/poster.jpg" width="240" alt="Forge Sparks"> | `forge-sparks`<br>sparks over dark steel and red | blackshield, matte-black | 8 s | `forge_sparks.py` |
| <img src="scenes/glyph-rain/poster.jpg" width="240" alt="Glyph Rain"> | `glyph-rain`<br>falling teal runes | glyphsmith, osaka-jade | 8 s | `glyph_rain.py` |
| <img src="scenes/candlelight/poster.jpg" width="240" alt="Candlelight"> | `candlelight`<br>one calm, warm candle | lampstand, ristretto | 8 s | `candlelight.py` |
| <img src="scenes/lofi-window/poster.jpg" width="240" alt="Lo-fi Window"> | `lofi-window`<br>rainy night window, desk, cat | gruvbox | 8 s | `lofi_window.py` |
| <img src="scenes/vaporwave/poster.jpg" width="240" alt="Vaporwave"> | `vaporwave`<br>crystal, columns, checkered floor | rose-pine | 10 s | `vaporwave.py` |
| <img src="scenes/breathe/poster.jpg" width="240" alt="Breathe"> | `breathe`<br>minimal breathing gradient | everforest | 10 s | `breathe.py` |

A theme name picks its scene directly. If the theme name isn't listed, the
`[match] background` key can still pick a scene by palette (see below). To use a
preset with any theme, run `livewall set <scene>`.

A scene is a folder with a `scene.toml`:

```toml
name = "my-scene"
theme = "my-theme"            # or themes = ["a", "b"]
fps = 30
poster = "poster.jpg"         # optional still
[video]                       # or video = "loop.mp4", or frames = "frames/", or gif = "loop.gif"
1920x1080 = "loop-1080p.mp4"
3840x2160 = "loop-2160p.mp4"
[match]                       # optional palette fallback
background = "#1a1029"
```

Media paths must stay inside the scene folder. Put your own scenes in
`~/.config/livewall/scenes/` and packs (`pack.toml` + `scenes/`) in
`~/.config/livewall/packs/`. Your scenes win over built-ins with the same name.

## Uninstall

```bash
./uninstall.sh
```

This stops Livewall, disables and removes the systemd unit, and deletes only
the files `install.sh` put in place. Your `~/.config/livewall/` (config and own
scenes), the log, and anything you added to `~/.local/share/livewall/` yourself
are kept. Delete those by hand if you want them gone.

## Rebuilding the media

You need `ffmpeg`, `numpy` and `Pillow`. Neon Horizon also needs its theme's
`colors.toml`; the presets carry their palettes in their generators.
Every loop renders frame *i* at t = i/N so it wraps without a jump. Check that with
`generators/check_seam.py loop.mp4`. It measures the last-to-first frame change at
two scales. At 120x68 codec noise averages out and what's left is structure, and a
seam no larger than the max frame step there means no visible jump. In near-still
scenes every step is tiny, so a seam under a quarter of a grey level on average also
passes. (At full detail, slow scenes show some keyframe noise at the seam. It's well
under one grey level.) The script exits non-zero if a loop jumps. The generators use `$LIVEWALL_THREADS`
(default 2) for both render processes and ffmpeg. 4K takes about 2 GB per process and
about 7 minutes with 2.

```bash
C=~/.config/omarchy/themes/neon-horizon/colors.toml
nice -n 19 python3 generators/neon_horizon.py --colors $C --out scenes/neon-horizon/loop-1080p.mp4
nice -n 19 python3 generators/neon_horizon.py --colors $C --size 3840x2160 --out scenes/neon-horizon/loop-2160p.mp4
generators/make_previews.sh $C    # previews/{hero.png,preview.webm,preview.mp4}

generators/build_presets.sh             # every preset: loop-1080p.mp4 + poster.jpg, then seam check
generators/build_presets.sh aurora      # just one
python3 generators/aurora.py --size 3840x2160 --out ~/aurora-4k.mp4   # a local 4K render
```

The presets share `generators/loopkit.py` (tileable noise, looping blends, particles,
the command line). Each loop is a single GOP, so the frame before the wrap has to
match the keyframe after it. The settings that make that work: mbtree and psy-rd
off, a high `ipratio` so the keyframe is no softer than the P-frames, a VBV buffer
big enough not to starve it, and more bits over the last two seconds. Without that
last part, slow changes in the quantizer's dead zone would pile up and land at the
wrap.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

No Hyprland, mpv or battery is needed. Hyprland and sysfs are faked. The tests
also check every built-in scene: it parses, its files and poster exist, sizes are
bounded, and its generator is present. With `numpy` and `Pillow` installed they
also render each preset small and check that its loop closes.

## License

MIT. See [LICENSE](LICENSE).
