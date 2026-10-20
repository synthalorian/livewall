"""Scene and scene-pack parsing.

A scene is a folder:

    my-scene/
      scene.toml          name, theme, fps (+ media)
      loop-1080p.mp4      a seamless loop (H.264/AV1/VP9), or
      frames/0001.png ... a frame sequence, or
      loop.gif            for the swww backend
      poster.jpg          optional still

A pack is a folder under packs/ with a pack.toml and a scenes/ dir of scenes;
its scene ids are "<pack-id>/<scene-name>".
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from livewall import paths

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
FRAME_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SIZE_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$")


class SceneError(ValueError):
    pass


def norm(name: str) -> str:
    """Normalise a theme/scene name: 'Neon Horizon' -> 'neon-horizon'."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


@dataclass
class Scene:
    id: str
    name: str
    title: str
    themes: list[str]
    fps: float
    path: Path
    videos: dict[str, Path] = field(default_factory=dict)   # "WxH" or "default" -> file
    frames: list[Path] = field(default_factory=list)
    gif: Path | None = None
    poster: Path | None = None
    duration: float | None = None
    match: dict[str, str] = field(default_factory=dict)
    pack: str | None = None
    source: str = "builtin"

    @property
    def kind(self) -> str:
        return "video" if self.videos else ("frames" if self.frames else "gif")

    def matches_theme(self, theme: str) -> bool:
        return norm(theme) in {norm(t) for t in self.themes}

    def video_for(self, width: int | None = None, height: int | None = None,
                  force: str | None = None) -> Path | None:
        """Pick the loop for an output: the smallest variant that covers it,
        else the largest one, else the default."""
        if not self.videos:
            return None
        if force and force != "auto" and force in self.videos:
            return self.videos[force]
        sized = []
        for key, p in self.videos.items():
            m = SIZE_RE.match(key)
            if m:
                sized.append((int(m[1]) * int(m[2]), int(m[1]), int(m[2]), p))
        if not sized:
            return self.videos.get("default") or next(iter(self.videos.values()))
        sized.sort(key=lambda s: s[0])
        if width and height:
            for _, w, h, p in sized:
                if w >= width and h >= height:
                    return p
            return sized[-1][3]
        if "default" in self.videos:
            return self.videos["default"]
        for _, w, h, p in sized:      # sensible default when the output is unknown
            if w >= 1920:
                return p
        return sized[-1][3]


def _media(base: Path, rel: str, what: str) -> Path:
    if not isinstance(rel, str) or not rel:
        raise SceneError(f"{what} must be a non-empty string")
    p = (base / rel).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise SceneError(f"{what} points outside the scene folder: {rel}")
    if not p.exists():
        raise SceneError(f"{what} not found: {rel}")
    return p


def parse_scene(folder: Path, pack: str | None = None, source: str = "builtin") -> Scene:
    folder = Path(folder)
    toml = folder / "scene.toml"
    if not toml.is_file():
        raise SceneError(f"{folder}: no scene.toml")
    try:
        data = tomllib.loads(toml.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SceneError(f"{toml}: {e}") from None

    name = data.get("name", folder.name)
    if not isinstance(name, str) or not norm(name):
        raise SceneError(f"{toml}: name must be a string")
    name = norm(name)

    themes = data.get("themes", data.get("theme"))
    if isinstance(themes, str):
        themes = [themes]
    if not themes or not all(isinstance(t, str) and t for t in themes):
        raise SceneError(f"{toml}: theme (string) or themes (list) is required")

    fps = data.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 1 <= fps <= 240:
        raise SceneError(f"{toml}: fps must be a number between 1 and 240")

    videos: dict[str, Path] = {}
    v = data.get("video")
    if isinstance(v, str):
        videos["default"] = _media(folder, v, "video")
    elif isinstance(v, dict):
        for key, rel in v.items():
            if key != "default" and not SIZE_RE.match(key):
                raise SceneError(f"{toml}: video key {key!r} must be 'default' or WIDTHxHEIGHT")
            videos[key] = _media(folder, rel, f"video.{key}")
    elif v is not None:
        raise SceneError(f"{toml}: video must be a path or a table")
    for p in videos.values():
        if p.suffix.lower() not in VIDEO_EXT:
            raise SceneError(f"{toml}: unsupported video type {p.name}")

    frames: list[Path] = []
    fr = data.get("frames")
    if fr is not None:
        if isinstance(fr, str):
            fr = {"dir": fr}
        if not isinstance(fr, dict):
            raise SceneError(f"{toml}: frames must be a path or a table")
        fdir = _media(folder, fr.get("dir", "frames"), "frames.dir")
        pattern = fr.get("pattern", "*")
        frames = sorted(p for p in fdir.glob(pattern) if p.suffix.lower() in FRAME_EXT)
        if not frames:
            raise SceneError(f"{toml}: frames dir has no images")

    gif = _media(folder, data["gif"], "gif") if "gif" in data else None
    if not videos and not frames and gif is None:
        raise SceneError(f"{toml}: needs a video, frames or gif")

    poster = None
    if "poster" in data:
        poster = _media(folder, data["poster"], "poster")

    match = data.get("match", {})
    if not isinstance(match, dict):
        raise SceneError(f"{toml}: [match] must be a table")
    match = {k: v.lower() for k, v in match.items() if isinstance(v, str)}

    dur = data.get("duration")
    sid = f"{pack}/{name}" if pack else name
    return Scene(id=sid, name=name, title=str(data.get("title", name)), themes=list(themes),
                 fps=float(fps), path=folder, videos=videos, frames=frames, gif=gif,
                 poster=poster, duration=float(dur) if isinstance(dur, (int, float)) else None,
                 match=match, pack=pack, source=source)


@dataclass
class Pack:
    id: str
    name: str
    version: str
    author: str
    path: Path
    scenes_dir: Path
    meta: dict


def parse_pack(folder: Path) -> Pack:
    toml = Path(folder) / "pack.toml"
    if not toml.is_file():
        raise SceneError(f"{folder}: no pack.toml")
    try:
        data = tomllib.loads(toml.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SceneError(f"{toml}: {e}") from None
    pid = norm(str(data.get("id", folder.name)))
    if not pid:
        raise SceneError(f"{toml}: id is required")
    sdir = Path(folder) / str(data.get("scenes", "scenes"))
    return Pack(id=pid, name=str(data.get("name", pid)), version=str(data.get("version", "0")),
                author=str(data.get("author", "")), path=Path(folder), scenes_dir=sdir, meta=data)


def discover(scene_paths: list[Path] | None = None, pack_paths: list[Path] | None = None,
             errors: list[str] | None = None) -> list[Scene]:
    """All valid scenes. Earlier search paths win on id clashes. Broken scenes
    are skipped and described in `errors`."""
    scene_paths = paths.scene_search_paths() if scene_paths is None else scene_paths
    pack_paths = paths.pack_search_paths() if pack_paths is None else pack_paths
    found: dict[str, Scene] = {}
    errs = errors if errors is not None else []

    def add(folder: Path, pack: str | None, source: str):
        try:
            sc = parse_scene(folder, pack=pack, source=source)
        except SceneError as e:
            errs.append(str(e))
            return
        found.setdefault(sc.id, sc)

    builtin_roots = {str((paths.data_dir() / "scenes").resolve()), str((paths.SRC_ROOT / "scenes").resolve())}
    for root in scene_paths:
        if not root.is_dir():
            continue
        source = "builtin" if str(root.resolve()) in builtin_roots else "user"
        for d in sorted(root.iterdir()):
            if (d / "scene.toml").is_file():
                add(d, None, source)
    for root in pack_paths:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if not (d / "pack.toml").is_file():
                continue
            try:
                pk = parse_pack(d)
            except SceneError as e:
                errs.append(str(e))
                continue
            if pk.scenes_dir.is_dir():
                for sd in sorted(pk.scenes_dir.iterdir()):
                    if (sd / "scene.toml").is_file():
                        add(sd, pk.id, f"pack:{pk.id}")
    return sorted(found.values(), key=lambda s: (s.pack or "", s.name))


def find(scenes: list[Scene], key: str) -> Scene | None:
    """Look a scene up by full id, or by bare name when that is unambiguous."""
    k = key.strip().lower()
    for s in scenes:
        if s.id == k:
            return s
    hits = [s for s in scenes if s.name == norm(k)]
    return hits[0] if len(hits) == 1 else None
