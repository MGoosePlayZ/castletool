#!/usr/bin/env python3
"""
castle_tool.py — Interactive Castle deck editor
Streamlines injecting images/GIFs and MIDI into Castle blueprint JSON files.
"""

import base64
import bisect
import copy
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

CURRENT_VERSION = "0.3.4"
PYPI_URL = "https://pypi.org/pypi/castletool/json"

# ── optional deps ────────────────────────────────────────────────────────────
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import mido
    HAS_MIDO = True
except ImportError:
    HAS_MIDO = False

HAS_FFMPEG = shutil.which("ffmpeg") is not None

# ── helpers ──────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"
WARN  = "\033[33m"
OK    = "\033[32m"
ERR   = "\033[31m"

def p(msg=""):        print(msg)
def pb(msg):          print(f"{BOLD}{msg}{RESET}")
def pw(msg):          print(f"{WARN}⚠  {msg}{RESET}")
def pe(msg):          print(f"{ERR}✗  {msg}{RESET}")
def ps(msg):          print(f"{OK}✓  {msg}{RESET}")

def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    try:
        val = input(f"{BOLD}{prompt}{suffix}{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        p(); sys.exit(0)
    return val if val else (default or "")

def yn(prompt, default="y"):
    hint = "Y/n" if default == "y" else "y/N"
    while True:
        try:
            ans = input(f"{BOLD}{prompt} ({hint}){RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            p(); sys.exit(0)
        if ans == "":
            return default == "y"
        if ans in ("y", "n"):
            return ans == "y"
        p("Please enter y or n.")

def choose(prompt, options):
    """Pick from a numbered list. Returns chosen item."""
    p()
    pb(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}")
    while True:
        raw = ask(f"Enter number (1-{len(options)})")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        p("Invalid choice.")

def ask_path(prompt, default=None, search_dir: Path | None = None):
    """Plain file path input."""
    suffix = f" [{default}]" if default is not None else ""
    pb(prompt + suffix)
    try:
        val = input(f"{BOLD}Path: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        p(); sys.exit(0)
    return val if val else (default or "")


def resolve_path(raw: str) -> Path:
    raw = raw.strip().strip("'\"")
    if raw.startswith("~/"):
        raw = str(Path.home()) + raw[1:]
    return Path(raw).expanduser().resolve()

# ── android / termux detection ───────────────────────────────────────────────

def is_termux() -> bool:
    return "com.termux" in str(Path.home()) or os.environ.get("TERMUX_VERSION") is not None

# ── update check ─────────────────────────────────────────────────────────────

def _version_tuple(v: str) -> tuple:
    parts = []
    for x in v.split("."):
        num = "".join(ch for ch in x if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)

def get_installed_version() -> str:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("castletool")
        except PackageNotFoundError:
            return CURRENT_VERSION
    except ImportError:
        return CURRENT_VERSION

def check_for_update():
    """Best-effort check against PyPI. Never blocks or errors on failure."""
    current = get_installed_version()
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=3) as resp:
            latest = json.loads(resp.read())["info"]["version"]
    except Exception:
        return

    if _version_tuple(latest) > _version_tuple(current):
        pw(f"A newer version is available: {latest} (you have {current})")
        if yn("Install it now?"):
            subprocess.run([sys.executable, "-m", "pip", "install",
                             "--quiet", "--upgrade", "castletool"])
            ps("Updated! Please restart Castletool.")
            sys.exit(0)
        p()

# ── dependency auto-install ──────────────────────────────────────────────────

def ensure_dependencies():
    """Best-effort auto-install of missing dependencies."""
    global HAS_PIL, HAS_MIDO, HAS_FFMPEG, Image, mido

    pip_missing = []
    if not HAS_PIL:  pip_missing.append("Pillow")
    if not HAS_MIDO: pip_missing.append("mido")

    if pip_missing:
        pb(f"Installing {', '.join(pip_missing)}...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *pip_missing])

    if not HAS_FFMPEG:
        pb("Installing ffmpeg...")
        if is_termux():
            subprocess.run(["pkg", "install", "-y", "ffmpeg"])
        elif shutil.which("apt-get"):
            subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"])
        elif shutil.which("brew"):
            subprocess.run(["brew", "install", "ffmpeg"])
        else:
            pw("Could not auto-install ffmpeg. Please install it manually.")

    if pip_missing or not HAS_FFMPEG:
        try:
            from PIL import Image as _Image
            Image = _Image
            HAS_PIL = True
        except ImportError:
            HAS_PIL = False
        try:
            import mido as _mido
            mido = _mido
            HAS_MIDO = True
        except ImportError:
            HAS_MIDO = False
        HAS_FFMPEG = shutil.which("ffmpeg") is not None

# ── deck / card / blueprint discovery ────────────────────────────────────────

def find_decks(search_dir: Path) -> list[Path]:
    """Return folders that look like Castle decks (contain deck.json)."""
    return sorted([d for d in search_dir.iterdir()
                   if d.is_dir() and (d / "deck.json").exists()])

def find_cards(deck: Path) -> list[Path]:
    cards_dir = deck / "cards"
    if not cards_dir.exists():
        return []
    return sorted([c for c in cards_dir.iterdir() if c.is_dir()])

def find_blueprints(card: Path) -> list[Path]:
    bp_dir = card / "scene" / "blueprints"
    if not bp_dir.exists():
        return []
    return sorted([f for f in bp_dir.glob("*.json")])

# ── card.json helpers ────────────────────────────────────────────────────────

def load_card_json(card: Path) -> dict:
    with open(card / "card.json", "r", encoding="utf-8") as f:
        return json.load(f)

def save_card_json(card: Path, data: dict):
    with open(card / "card.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def hex_to_rgba(hex_str: str) -> dict:
    """Convert a '#rrggbb' string to Castle's 0-1 float RGBA dict."""
    hex_str = hex_str.strip().lstrip("#")
    r = int(hex_str[0:2], 16) / 255
    g = int(hex_str[2:4], 16) / 255
    b = int(hex_str[4:6], 16) / 255
    return {"r": round(r, 5), "g": round(g, 5), "b": round(b, 5), "a": 1}

def do_edit_background_color(card: Path):
    card_data = load_card_json(card)
    current = card_data.get("backgroundColor", "#000000")
    p()
    pb(f"Current background color: {current}")
    while True:
        raw = ask("Enter new background color as hex", default=current).strip()
        if not raw.startswith("#"):
            raw = "#" + raw
        if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
            break
        pe("Enter a hex color like #09101a.")

    card_data["backgroundColor"] = raw
    card_data.setdefault("sceneProperties", {})["backgroundColor"] = hex_to_rgba(raw)
    save_card_json(card, card_data)
    ps(f"Background color set to {raw}.")

def set_card_tempo(card: Path, bpm: float):
    """Write the given BPM into card.json's sceneProperties.clock.tempo."""
    card_data = load_card_json(card)
    scene_props = card_data.setdefault("sceneProperties", {})
    clock = scene_props.setdefault("clock", {"beatsPerBar": 4, "stepsPerBeat": 4})
    clock["tempo"] = round(bpm, 2)
    save_card_json(card, card_data)

# ── image/gif → Drawing2 ─────────────────────────────────────────────────────

def load_image_frames(path: Path, width: int, height: int):
    img = Image.open(path)

    # Normal image
    if not getattr(img, "is_animated", False):
        frame = img.convert("RGBA").resize((width, height), Image.NEAREST)
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        return [buf.getvalue()], 1.0

    # Animated GIF/WEBP
    frames = []
    durations = []

    try:
        while True:
            frame = img.convert("RGBA").resize((width, height), Image.NEAREST)
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            frames.append(buf.getvalue())
            durations.append(max(img.info.get("duration", 100), 1))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    avg_ms = sum(durations) / len(durations)
    fps = round(1000 / avg_ms, 2)

    return frames, fps

def probe_video_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) of a video file via ffprobe."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True
    )
    raw = probe.stdout.strip()
    try:
        w, h = raw.split("x")
        return int(w), int(h)
    except Exception:
        return 64, 64


def extract_mp4_frames(path: Path, width: int, height: int, every_n: int = 1) -> tuple[list[bytes], float]:
    """Extract frames from MP4 using ffmpeg. Returns (png_frames, fps)."""
    if not HAS_FFMPEG:
        pe("ffmpeg not found. Install with: pkg install ffmpeg")
        sys.exit(1)

    # Get fps via ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    raw_fps = probe.stdout.strip()
    try:
        num, den = raw_fps.split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 30.0

    effective_fps = fps / every_n

    # Extract frames as PNG via pipe. width/height already share the source's
    # aspect ratio (scaled), so a plain nearest-neighbor scale is exact — no
    # padding/cropping needed.
    result = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-vf", f"select='not(mod(n\\,{every_n}))',scale={width}:{height}:flags=neighbor",
         "-vsync", "vfr",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True
    )

    # Split raw stdout into individual PNGs by PNG magic bytes
    raw = result.stdout
    png_magic = bytes([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a])
    frames = []
    start = 0
    while True:
        idx = raw.find(png_magic, start)
        if idx == -1:
            break
        next_idx = raw.find(png_magic, idx + 1)
        chunk = raw[idx:next_idx] if next_idx != -1 else raw[idx:]
        frames.append(chunk)
        start = next_idx if next_idx != -1 else len(raw)

    if not frames:
        pe("ffmpeg returned no frames. Is the file a valid MP4?")
        sys.exit(1)

    return frames, effective_fps


def quantize_frame(png_bytes: bytes, colors: int) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    rgb = img.convert("RGB").quantize(colors=colors,
                                       method=Image.Quantize.MEDIANCUT).convert("RGB")
    result = Image.new("RGBA", img.size)
    result.paste(rgb)
    result.putalpha(img.split()[3])
    buf = io.BytesIO()
    result.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def build_drawing2(
    frames: list[bytes],
    fps: float,
    width: int,
    height: int,
    play_mode: str = "loop"
) -> dict:
    # Empirical scale formula
    scale = max(1, round(max(width, height) / 20))

    half_w, half_h = width / 2, height / 2
    bounds = {
        "minX": -half_w,
        "maxX": half_w,
        "minY": -half_h,
        "maxY": half_h,
}

    castle_frames = [{
        "isLinked": False,
        "pathDataList": [],
        "fillImageBounds": bounds,
        "fillPng": base64.b64encode(p).decode(),
        "avatarX": 0,
        "avatarY": 0,
        "avatarRadius": 5,
} for p in frames]

    return {
        "initialFrame": 1,
        "currentFrame": 1,
        "framesPerSecond": fps,
        "playMode": play_mode,
        "loopStartFrame": -1,
        "loopEndFrame": -1,
        "opacity": 1,
        "hash": str(abs(hash(frames[0])))[:19],
        "playing": False,
        "loop": play_mode != "still",

        "drawData": {
            "color": [1, 1, 1, 1],
            "lineColor": [0, 0, 0, 1],
            "gridSize": 0.71428,
            "scale": scale,
            "version": 3,
            "fillPixelsPerUnit": scale,
            "numTotalLayers": 1,
            "framesBounds": [bounds] * len(frames),
            "colors": [],
            "selectedFrame": 1,
            "layers": [{
                "title": "Layer 1",
                "id": "layer1",
                "isVisible": True,
                "isBitmap": True,
                "isAvatar": False,
                "frames": castle_frames,
        }],
        },

        "physicsBodyData": {
            "shapes": [{
                "p1": {"x": half_w / scale, "y": half_h / scale},
                "p2": {"x": -half_w / scale, "y": -half_h / scale},
                "p3": {"x": 0, "y": 0},
                "radius": 0,
                "x": 0,
                "y": 0,
                "type": "rectangle",
        }],
            "scale": scale,
            "version": 2,
            "zeroShapesInV1": False,
        },

        "disabled": False,
        } 

# ── svg → Drawing2 (vector) ──────────────────────────────────────────────────
# Merged from svg_to_castle.py: flattens all SVG paths to straight line
# segments (s:1, f:false). Bezier curves are sampled at `steps` intervals.

# Castle coordinate scale: SVG px → Castle units
# fillPixelsPerUnit = 25.6 by default
SVG_DEFAULT_PPU = 25.6
SVG_NS = "http://www.w3.org/2000/svg"


def _svg_lerp(a, b, t): return a + (b - a) * t

def _svg_quadratic_point(p0, p1, p2, t):
    x = (1-t)**2*p0[0] + 2*(1-t)*t*p1[0] + t**2*p2[0]
    y = (1-t)**2*p0[1] + 2*(1-t)*t*p1[1] + t**2*p2[1]
    return (x, y)

def _svg_cubic_point(p0, p1, p2, p3, t):
    x = (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0]
    y = (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1]
    return (x, y)


def _svg_arc_to_lines(x1, y1, rx, ry, x_rot, large, sweep, x2, y2, steps):
    """Convert SVG arc to polyline points."""
    if x1 == x2 and y1 == y2:
        return []
    if rx == 0 or ry == 0:
        return [(x1, y1), (x2, y2)]

    phi = math.radians(x_rot)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p =  cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    rx, ry = abs(rx), abs(ry)
    x1p2, y1p2, rx2, ry2 = x1p**2, y1p**2, rx**2, ry**2
    lam = x1p2/rx2 + y1p2/ry2
    if lam > 1:
        sq = math.sqrt(lam)
        rx, ry = sq * rx, sq * ry
        rx2, ry2 = rx**2, ry**2

    num = max(0, rx2*ry2 - rx2*y1p2 - ry2*x1p2)
    den = rx2*y1p2 + ry2*x1p2
    sq = math.sqrt(num / den) if den else 0
    if large == sweep:
        sq = -sq

    cxp =  sq * rx * y1p / ry
    cyp = -sq * ry * x1p / rx

    cx = cos_phi*cxp - sin_phi*cyp + (x1+x2)/2
    cy = sin_phi*cxp + cos_phi*cyp + (y1+y2)/2

    def angle(ux, uy, vx, vy):
        n = math.sqrt(ux**2+uy**2) * math.sqrt(vx**2+vy**2)
        if n == 0: return 0
        c = max(-1, min(1, (ux*vx+uy*vy)/n))
        a = math.acos(c)
        if ux*vy - uy*vx < 0: a = -a
        return a

    theta1 = angle(1, 0, (x1p-cxp)/rx, (y1p-cyp)/ry)
    dtheta = angle((x1p-cxp)/rx, (y1p-cyp)/ry, (-x1p-cxp)/rx, (-y1p-cyp)/ry)

    if not sweep and dtheta > 0: dtheta -= 2*math.pi
    if sweep and dtheta < 0: dtheta += 2*math.pi

    pts = []
    for i in range(steps + 1):
        t = i / steps
        theta = theta1 + t * dtheta
        x = cos_phi*rx*math.cos(theta) - sin_phi*ry*math.sin(theta) + cx
        y = sin_phi*rx*math.cos(theta) + cos_phi*ry*math.sin(theta) + cy
        pts.append((x, y))
    return pts


def _svg_parse_numbers(s: str) -> list[float]:
    return [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', s)]


def _svg_path_to_polylines(d: str, steps: int = 16) -> list[list[tuple]]:
    """
    Parse SVG path 'd' attribute, return list of polylines.
    Each polyline is a list of (x, y) tuples.
    Beziers are sampled at 'steps' intervals.
    """
    tokens = re.findall(r'[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d)
    cmd = None
    pos = (0.0, 0.0)
    start = (0.0, 0.0)
    last_ctrl = None
    polylines = []
    current = []

    def flush():
        nonlocal current
        if len(current) >= 2:
            polylines.append(current)
        current = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r'[MmZzLlHhVvCcSsQqTtAa]', t):
            cmd = t
            i += 1
            if cmd in ('Z', 'z'):
                if current and current[-1] != start:
                    current.append(start)
                flush()
                pos = start
                cmd = None
            continue

        if cmd in ('Z', 'z'):
            if current and current[-1] != start:
                current.append(start)
            flush()
            pos = start
            cmd = None
            continue

        nparams = {
            'M':2,'m':2,'L':2,'l':2,'H':1,'h':1,'V':1,'v':1,
            'C':6,'c':6,'S':4,'s':4,'Q':4,'q':4,'T':2,'t':2,
            'A':7,'a':7,
        }.get(cmd, 0)

        if nparams == 0:
            i += 1
            continue

        args = []
        while len(args) < nparams and i < len(tokens):
            tok = tokens[i]
            if re.match(r'[MmZzLlHhVvCcSsQqTtAa]', tok):
                break
            args.append(float(tok))
            i += 1

        if len(args) < nparams:
            continue

        rel = cmd.islower()
        base = pos if rel else (0.0, 0.0)

        if cmd in ('M', 'm'):
            flush()
            nx, ny = base[0]+args[0], base[1]+args[1]
            pos = (nx, ny)
            start = pos
            current = [pos]
            last_ctrl = None
            cmd = 'l' if rel else 'L'

        elif cmd in ('L', 'l'):
            nx, ny = base[0]+args[0], base[1]+args[1]
            pos = (nx, ny)
            current.append(pos)
            last_ctrl = None

        elif cmd in ('H', 'h'):
            nx = (pos[0] if rel else 0) + args[0]
            pos = (nx, pos[1])
            current.append(pos)
            last_ctrl = None

        elif cmd in ('V', 'v'):
            ny = (pos[1] if rel else 0) + args[0]
            pos = (pos[0], ny)
            current.append(pos)
            last_ctrl = None

        elif cmd in ('C', 'c'):
            p1 = (base[0]+args[0], base[1]+args[1])
            p2 = (base[0]+args[2], base[1]+args[3])
            p3 = (base[0]+args[4], base[1]+args[5])
            for s in range(1, steps+1):
                current.append(_svg_cubic_point(pos, p1, p2, p3, s/steps))
            last_ctrl = p2
            pos = p3

        elif cmd in ('S', 's'):
            p1 = (2*pos[0]-last_ctrl[0], 2*pos[1]-last_ctrl[1]) if last_ctrl else pos
            p2 = (base[0]+args[0], base[1]+args[1])
            p3 = (base[0]+args[2], base[1]+args[3])
            for s in range(1, steps+1):
                current.append(_svg_cubic_point(pos, p1, p2, p3, s/steps))
            last_ctrl = p2
            pos = p3

        elif cmd in ('Q', 'q'):
            p1 = (base[0]+args[0], base[1]+args[1])
            p2 = (base[0]+args[2], base[1]+args[3])
            for s in range(1, steps+1):
                current.append(_svg_quadratic_point(pos, p1, p2, s/steps))
            last_ctrl = p1
            pos = p2

        elif cmd in ('T', 't'):
            p1 = (2*pos[0]-last_ctrl[0], 2*pos[1]-last_ctrl[1]) if last_ctrl else pos
            p2 = (base[0]+args[0], base[1]+args[1])
            for s in range(1, steps+1):
                current.append(_svg_quadratic_point(pos, p1, p2, s/steps))
            last_ctrl = p1
            pos = p2

        elif cmd in ('A', 'a'):
            rx,ry,xr = args[0],args[1],args[2]
            large,sweep = int(args[3]),int(args[4])
            ex,ey = base[0]+args[5], base[1]+args[6]
            pts = _svg_arc_to_lines(pos[0],pos[1],rx,ry,xr,large,sweep,ex,ey,steps)
            if pts:
                current.extend(pts[1:])
            last_ctrl = None
            pos = (ex, ey)

    flush()
    return polylines


SVG_COLORS = {
    "black":(0,0,0),"white":(1,1,1),"red":(1,0,0),"green":(0,0.502,0),
    "blue":(0,0,1),"yellow":(1,1,0),"cyan":(0,1,1),"magenta":(1,0,1),
    "gray":(0.502,0.502,0.502),"grey":(0.502,0.502,0.502),
    "none":None,
}

def parse_svg_color(s: str, opacity: float = 1.0):
    if not s or s == "none": return None
    s = s.strip().lower()
    if s in SVG_COLORS:
        c = SVG_COLORS[s]
        return [*c, opacity] if c else None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3: h = h[0]*2+h[1]*2+h[2]*2
        r,g,b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
        return [r, g, b, opacity]
    m = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', s)
    if m:
        return [int(m.group(i))/255 for i in (1,2,3)] + [opacity]
    return [0, 0, 0, opacity]


def svg_to_path_data(svg_path, steps: int = 16, scale: float = 1.0,
                     ppu: float = SVG_DEFAULT_PPU, color=None):
    """
    Parse an SVG file and return a Castle pathDataList and framesBounds.
    scale: multiplier applied to Castle units (1.0 = default)
    ppu: pixels per unit (default 25.6)
    color: override color [r,g,b,a], None = use SVG colors
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()

    def tag(el): return el.tag.split('}')[-1] if '}' in el.tag else el.tag

    vb = root.get("viewBox")
    if vb:
        parts = _svg_parse_numbers(vb)
        vb_x, vb_y, vb_w, vb_h = parts
    else:
        vb_x, vb_y = 0, 0
        vb_w = float(root.get("width", 100))
        vb_h = float(root.get("height", 100))

    # SVG Y is flipped vs Castle Y
    def to_castle_raw(x, y):
        return (x / ppu * scale, -(y / ppu) * scale)

    _cx_offset = [0.0]
    _cy_offset = [0.0]

    def to_castle(x, y):
        rx, ry = to_castle_raw(x, y)
        return (rx - _cx_offset[0], ry - _cy_offset[0])

    path_data = []
    default_color = color or [0, 0, 0, 1]
    all_xs, all_ys = [], []

    def get_color(el):
        if color: return color
        stroke = el.get("stroke") or el.get("style", "")
        m = re.search(r'stroke\s*:\s*([^;]+)', stroke)
        stroke_val = m.group(1).strip() if m else (el.get("stroke") or "black")
        op_m = re.search(r'stroke-opacity\s*:\s*([^;]+)', el.get("style",""))
        opacity = float(op_m.group(1)) if op_m else float(el.get("stroke-opacity", 1))
        c = parse_svg_color(stroke_val, opacity)
        return c if c else default_color

    def process_element(el):
        t = tag(el)
        c = get_color(el)

        polylines = []

        if t == "path":
            d = el.get("d", "")
            polylines = _svg_path_to_polylines(d, steps)

        elif t == "line":
            x1,y1 = float(el.get("x1",0)), float(el.get("y1",0))
            x2,y2 = float(el.get("x2",0)), float(el.get("y2",0))
            polylines = [[(x1,y1),(x2,y2)]]

        elif t == "polyline" or t == "polygon":
            pts_raw = _svg_parse_numbers(el.get("points",""))
            pts = [(pts_raw[i],pts_raw[i+1]) for i in range(0,len(pts_raw)-1,2)]
            if t == "polygon" and pts: pts.append(pts[0])
            polylines = [pts]

        elif t == "rect":
            x,y = float(el.get("x",0)), float(el.get("y",0))
            w,h = float(el.get("width",0)), float(el.get("height",0))
            polylines = [[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]]

        elif t == "circle":
            cx2,cy2,r = float(el.get("cx",0)),float(el.get("cy",0)),float(el.get("r",1))
            pts = [(cx2+r*math.cos(2*math.pi*i/steps),
                    cy2+r*math.sin(2*math.pi*i/steps)) for i in range(steps+1)]
            polylines = [pts]

        elif t == "ellipse":
            cx2,cy2 = float(el.get("cx",0)),float(el.get("cy",0))
            rx2,ry2 = float(el.get("rx",1)),float(el.get("ry",1))
            pts = [(cx2+rx2*math.cos(2*math.pi*i/steps),
                    cy2+ry2*math.sin(2*math.pi*i/steps)) for i in range(steps+1)]
            polylines = [pts]

        for poly in polylines:
            if len(poly) < 2: continue
            castle_pts = [to_castle(x, y) for x, y in poly]
            for j in range(len(castle_pts)-1):
                x1,y1 = castle_pts[j]
                x2,y2 = castle_pts[j+1]
                path_data.append({
                    "p": [round(x1,5), round(y1,5), round(x2,5), round(y2,5)],
                    "s": 1,
                    "f": False,
                    "c": [round(v,5) for v in c],
                })
                all_xs.extend([x1, x2])
                all_ys.extend([y1, y2])

        for child in el:
            process_element(child)

    process_element(root)

    if not all_xs:
        return path_data, {"minX":-5,"maxX":5,"minY":-5,"maxY":5}, {"minX":-32,"maxX":32,"minY":-32,"maxY":32}

    mid_x = (min(all_xs) + max(all_xs)) / 2
    mid_y = (min(all_ys) + max(all_ys)) / 2
    for seg in path_data:
        seg["p"][0] = round(seg["p"][0] - mid_x, 5)
        seg["p"][1] = round(seg["p"][1] - mid_y, 5)
        seg["p"][2] = round(seg["p"][2] - mid_x, 5)
        seg["p"][3] = round(seg["p"][3] - mid_y, 5)
    all_xs = [x - mid_x for x in all_xs]
    all_ys = [y - mid_y for y in all_ys]

    bounds = {
        "minX": round(min(all_xs), 5),
        "maxX": round(max(all_xs), 5),
        "minY": round(min(all_ys), 5),
        "maxY": round(max(all_ys), 5),
    }

    fill_bounds = {
        "minX": round(min(all_xs) * ppu / scale),
        "maxX": round(max(all_xs) * ppu / scale),
        "minY": round(-max(all_ys) * ppu / scale),
        "maxY": round(-min(all_ys) * ppu / scale),
    }

    return path_data, bounds, fill_bounds


def build_drawing2_vector(path_data, bounds, fill_bounds,
                           scale=10, ppu=SVG_DEFAULT_PPU) -> dict:
    frame = {
        "isLinked": False,
        "pathDataList": path_data,
        "fillImageBounds": fill_bounds,
        "avatarX": 0, "avatarY": 0, "avatarRadius": 5,
    }
    return {
        "initialFrame": 1, "currentFrame": 1,
        "framesPerSecond": 4,
        "playMode": "still",
        "loopStartFrame": -1, "loopEndFrame": -1,
        "opacity": 1,
        "hash": str(abs(hash(str(path_data))))[:19],
        "playing": False, "loop": False,
        "drawData": {
            "color": [1,1,1,1], "lineColor": [0,0,0,1],
            "gridSize": 0.71428, "scale": scale, "version": 3,
            "fillPixelsPerUnit": ppu,
            "numTotalLayers": 1,
            "framesBounds": [bounds],
            "colors": [], "selectedFrame": 1,
            "layers": [{
                "title": "Layer 1", "id": "layer1",
                "isVisible": True, "isBitmap": False, "isAvatar": False,
                "frames": [frame],
            }],
        },
        "physicsBodyData": {
            "shapes": [{
                "p1": {"x": 5, "y": 5}, "p2": {"x": -5, "y": -5},
                "p3": {"x": 0, "y": 0}, "radius": 0, "x": 0, "y": 0,
                "type": "rectangle",
            }],
            "scale": scale, "version": 2, "zeroShapesInV1": False,
        },
        "disabled": False,
    }


# ── midi → Music ─────────────────────────────────────────────────────────────

def beat_key(b): return f"{b:.6f}"
def make_color(): return {"r": 0.19607, "g": 0.16862, "b": 0.15681, "a": 1.0}

DEFAULT_TEMPO = 500000  # microseconds per beat == 120 BPM, mido/MIDI spec default

def get_tempo_map(mid) -> list[tuple[int, int]]:
    """
    Scan every track for `set_tempo` meta messages and return a sorted,
    deduped list of (abs_tick, tempo_us_per_beat) covering the whole file.
    Tempo events can technically appear on any track, not just track 0,
    so all tracks are scanned and merged by absolute tick.
    """
    events = []
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                events.append((abs_tick, msg.tempo))
    if not events:
        return [(0, DEFAULT_TEMPO)]
    events.sort(key=lambda e: e[0])
    # if multiple tempo changes land on the same tick, keep the last one
    deduped = []
    for tick, tempo in events:
        if deduped and deduped[-1][0] == tick:
            deduped[-1] = (tick, tempo)
        else:
            deduped.append((tick, tempo))
    if deduped[0][0] != 0:
        deduped.insert(0, (0, DEFAULT_TEMPO))
    return deduped

def make_tick_scaler(tempo_map: list[tuple[int, int]]):
    """
    Build a function mapping abs_tick -> "scaled tick", where the scaling
    compresses/expands ticks by how much each tempo segment's speed differs
    from the file's reference (initial) tempo. Castle plays music at a
    single constant BPM, so a MIDI's tempo *changes* have to be baked into
    the beat spacing itself, otherwise sections that sped up or slowed down
    in the original file play back at the wrong relative speed in Castle.
    A file with only one tempo (the common case) scales by exactly 1.0
    everywhere, so this is a no-op for tempo-stable MIDIs.
    """
    reference_tempo = tempo_map[0][1]
    ticks = [t for t, _ in tempo_map]
    # cumulative scaled-tick value at the start of each tempo segment.
    # A segment's real duration is delta_ticks * tempo (µs/beat); dividing
    # that real duration back through reference_tempo gives how many ticks
    # it "would have been" at the reference tempo, so faster segments
    # (smaller µs/beat) compress and slower segments expand.
    cum_at_start = [0.0]
    for i in range(1, len(tempo_map)):
        prev_tick, prev_tempo = tempo_map[i - 1]
        cur_tick, _ = tempo_map[i]
        delta_ticks = cur_tick - prev_tick
        cum_at_start.append(cum_at_start[-1] + delta_ticks * (prev_tempo / reference_tempo))

    def scale(abs_tick: int) -> float:
        idx = bisect.bisect_right(ticks, abs_tick) - 1
        idx = max(0, idx)
        seg_tick, seg_tempo = tempo_map[idx]
        return cum_at_start[idx] + (abs_tick - seg_tick) * (seg_tempo / reference_tempo)

    return scale

def collect_midi_tracks(mid) -> list[dict]:
    """
    Returns one entry per non-empty MIDI track:
    {"events": [(beat, note), ...], "program": int, "is_drum": bool}

    Since a Castle track only has one instrument, each MIDI track is
    reduced to a single representative (channel, program) pair: whichever
    combination its note_on events use most. Channel 10 (index 9) is
    GM's reserved percussion channel regardless of its program number.
    """
    tpb = mid.ticks_per_beat
    scale = make_tick_scaler(get_tempo_map(mid))
    result = []
    for track in mid.tracks:
        events, abs_tick = [], 0
        programs = {}       # channel -> most recently seen program
        usage = Counter()   # (channel, program) -> note_on count
        for msg in track:
            abs_tick += msg.time
            if msg.type == "program_change":
                programs[msg.channel] = msg.program
            elif msg.type == "note_on" and msg.velocity > 0:
                events.append((scale(abs_tick) / tpb * 4, msg.note))
                channel = msg.channel
                usage[(channel, programs.get(channel, 0))] += 1
        if not events:
            continue
        (channel, program), _ = usage.most_common(1)[0]
        result.append({
            "events": events,
            "program": program,
            "is_drum": channel == 9,
        })
    return result

def get_bpm(mid) -> float:
    """BPM implied by the MIDI file's initial (reference) tempo."""
    tempo_us = get_tempo_map(mid)[0][1]
    return 60_000_000 / tempo_us

# GM instrument families, in program-number order (0-indexed, inclusive
# upper bound), each mapped to one of Castle's 4 tone waveforms plus an
# attack/release approximating that family's envelope. Castle only offers
# square/sawtooth/sine/noise, so this groups all 128 GM programs into
# their 16 official families rather than mapping note-for-note.
GM_FAMILIES = [
    (7,   "sine",     0.0,  0.35),  # Piano
    (15,  "sine",     0.0,  0.2),   # Chromatic Percussion
    (23,  "square",   0.0,  0.1),   # Organ
    (31,  "sawtooth", 0.0,  0.3),   # Guitar
    (39,  "square",   0.0,  0.3),   # Bass
    (47,  "sawtooth", 0.08, 0.45),  # Strings
    (55,  "sawtooth", 0.1,  0.45),  # Ensemble
    (63,  "square",   0.02, 0.25),  # Brass
    (71,  "square",   0.02, 0.2),   # Reed
    (79,  "sine",     0.03, 0.2),   # Pipe
    (87,  "sawtooth", 0.0,  0.15),  # Synth Lead
    (95,  "sine",     0.3,  0.6),   # Synth Pad
    (103, "sine",     0.15, 0.4),   # Synth Effects
    (111, "sawtooth", 0.0,  0.3),   # Ethnic
    (119, "noise",    0.0,  0.1),   # Percussive
    (127, "noise",    0.0,  0.2),   # Sound Effects
]

def gm_program_to_tone(program: int, is_drum: bool) -> tuple[str, float, float]:
    """Map a GM program (+ drum-channel flag) to (waveform, attack, release)."""
    if is_drum:
        return "noise", 0.0, 0.12
    program = max(0, min(127, program))
    for upper, waveform, attack, release in GM_FAMILIES:
        if program <= upper:
            return waveform, attack, release
    return "sawtooth", 0.0, 0.4  # unreachable, GM_FAMILIES covers 0-127

def build_music(mid, beats_per_bar: int = 4) -> dict:
    midi_tracks = collect_midi_tracks(mid)
    patterns, castle_tracks = {}, []
    for t_idx, track in enumerate(midi_tracks):
        waveform, attack, release = gm_program_to_tone(track["program"], track["is_drum"])

        # merge every note in the track into a single pattern, keyed by
        # its absolute beat position (instead of one pattern per bar).
        notes_by_beat = {}
        for beat, note in track["events"]:
            # "key" already sits at the same octave the MIDI file uses
            # (raw note number), so bump it one octave higher per spec.
            octave_note = min(127, note + 12)
            notes_by_beat.setdefault(round(beat, 9), []).append(octave_note)

        pid = str(uuid.uuid4())
        notes = {beat_key(b): [{"key": n} for n in ns]
                 for b, ns in sorted(notes_by_beat.items())}
        patterns[pid] = {
            "patternId": pid,
            "name": f"t{t_idx}",
            "color": make_color(), "loop": "nextBar", "loopLength": 0,
            "notes": notes,
        }
        castle_tracks.append({
            "instrument": {
                "type": "sampler",
                "props": {"name": "tone", "muted": False, "volume": 1},
                "sample": {
                    "type": "tone",
                    "playbackRate": {"value": 1}, "amplitude": {"value": 1},
                    "pan": {"value": 0}, "recordingUrl": "", "uploadUrl": "",
                    "category": "random", "seed": 1337, "mutationSeed": 0,
                    "mutationAmount": 5, "midiNote": 48, "waveform": waveform,
                    "attack": attack, "release": release, "wait": False,
                },
            },
            "sequence": {
                beat_key(0): {"patternId": pid, "loop": False}
            },
        })
    return {
        "song": {"patterns": patterns, "tracks": castle_tracks},
        "autoplay": "loop", "disabled": False,
    }

# ── main flow ─────────────────────────────────────────────────────────────────

# The CLI-scaffolded placeholder script Castle generates for a brand-new
# actor. If a blueprint still has exactly this (untouched) when an image
# is added to it, the placeholder is deleted since it's no longer needed.
AUTO_GENERATED_SCRIPT = """function onCreate()
  print("ready")
end

function onDraw()
  castle.draw.setColor(0.25, 0.9, 0.62, 1)
  castle.draw.circle("fill", 0, 0, 0.28)

  castle.draw.setLineWidth(0.035)
  castle.draw.setColor(1, 1, 1, 0.45)
  castle.draw.rectangle("line", -0.42, -0.42, 0.84, 0.84)
end"""

def maybe_delete_placeholder_script(card: Path, bp_path: Path):
    """
    If the blueprint's matching script (<card>/scripts/<blueprint-name>.lua)
    is exactly the CLI's auto-generated placeholder, clear its contents,
    since an image was just added to that actor and it needs no default
    script. The file itself is kept (rather than deleted) since Castle
    re-creates it with the placeholder code if it's missing.
    """
    script_path = card / "scripts" / f"{bp_path.stem}.lua"
    if not script_path.exists():
        return
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError:
        return
    if content.replace("\r\n", "\n").rstrip("\n") == AUTO_GENERATED_SCRIPT.rstrip("\n"):
        script_path.write_text("", encoding="utf-8")
        ps(f"Cleared placeholder script: {script_path.name}")

def do_add_image(bp_path: Path, actor: dict, card: Path):
    while True:
        raw = ask_path("Enter the file path for your image")
        img_path = resolve_path(raw)
        if img_path.exists():
            break
        pe(f"File not found: {img_path}")

    ext = img_path.suffix.lower()
    is_anim = ext in (".gif", ".webp", ".mp4", ".mov", ".webm", ".avi")
    is_video = ext in (".mp4", ".mov", ".webm", ".avi")
    is_vector = ext in (".svg",)
    file_size = img_path.stat().st_size

    # native size + scale
    p()
    width, height, every, quantize = None, None, 1, 0
    if not is_vector:
        if is_video:
            if not HAS_FFMPEG:
                pe("ffmpeg is required for video files. Install with: pkg install ffmpeg")
                return
            native_w, native_h = probe_video_dimensions(img_path)
        else:
            with Image.open(img_path) as _img:
                native_w, native_h = _img.size

        raw = ask("Scale (1 = full resolution, 0.5 = half, 2 = double)", default="1")
        try:
            img_scale = float(raw)
            if img_scale <= 0:
                raise ValueError
        except ValueError:
            pw("Invalid scale, using 1.")
            img_scale = 1.0

        width = max(1, round(native_w * img_scale))
        height = max(1, round(native_h * img_scale))

        # frame skip for animations
        if is_anim:
            p()
            if yn("Would you like to skip frames? (reduces file size for long GIFs)", default="n"):
                while True:
                    raw = ask("Keep every Nth frame (e.g. 2 = half frames, 4 = quarter)", default="2")
                    if raw.isdigit() and int(raw) >= 1:
                        every = int(raw)
                        break
                    pe("Enter a positive integer.")

        # quantize
        p()
        if file_size > 500_000:
            pw(f"This file is abnormally large ({file_size//1024}KB). Quantizing is recommended.")
        if yn("Would you like to quantize this image? (reduces file size)", default="y" if file_size > 500_000 else "n"):
            while True:
                raw = ask("Select number of colors", default="256")
                if raw.isdigit() and 1 <= int(raw) <= 256:
                    quantize = int(raw)
                    break
                pe("Enter a number between 1 and 256.")

    p()
    if is_vector:
        pb(f"Loading SVG: {img_path.name}")
        svg_scale = 1.0
        if yn("Would you like to scale the SVG output?", default="n"):
            while True:
                raw = ask("Enter scale multiplier (e.g. 2.0 = twice as large)", default="1.0")
                try:
                    svg_scale = float(raw)
                    break
                except ValueError:
                    pe("Enter a number like 1.0 or 0.5")
        steps = 16
        if yn("Customize bezier curve smoothness? (default 16 steps)", default="n"):
            while True:
                raw = ask("Steps per curve segment", default="16")
                if raw.isdigit() and int(raw) >= 2:
                    steps = int(raw)
                    break
                pe("Enter a number ≥ 2")
        path_data, bounds, fill_bounds = svg_to_path_data(
            img_path, steps=steps, scale=svg_scale)
        drawing2 = build_drawing2_vector(path_data, bounds, fill_bounds)
        ps(f"SVG ready: {len(path_data)} line segments")
    else:
        pb(f"Loading {'video' if is_video else 'image'}: {img_path.name}")
        if is_video:
            if not HAS_FFMPEG:
                pe("ffmpeg is required for video files. Install with: pkg install ffmpeg")
                return
            frames, fps = extract_mp4_frames(img_path, width, height, every_n=every)
        else:
            frames, fps = load_image_frames(img_path, width, height)
            if every > 1:
                frames = frames[::every]
                fps = fps / every

        if quantize:
            pb(f"Quantizing {len(frames)} frame(s) to {quantize} colors...")
            frames = [quantize_frame(f, quantize) for f in frames]

        play_mode = "loop" if is_anim else "still"
        drawing2 = build_drawing2(frames, fps, width, height, play_mode)
        ps(f"Image ready: {len(frames)} frame(s), {fps} FPS, {width}×{height}px")

    actor["actorBlueprint"]["components"]["Drawing2"] = drawing2
    with open(bp_path, "w", encoding="utf-8") as f:
        json.dump(actor, f, indent=2)
    ps("Image added.")

    maybe_delete_placeholder_script(card, bp_path)


def do_add_midi(bp_path: Path, actor: dict, card: Path):
    while True:
        raw = ask_path("Enter your MIDI file path")
        midi_path = resolve_path(raw)
        if midi_path.exists():
            break
        pe(f"File not found: {midi_path}")

    p()
    pb(f"Loading MIDI: {midi_path.name}")
    mid = mido.MidiFile(midi_path, clip=True)
    music = build_music(mid)
    pat_count = len(music["song"]["patterns"])
    trk_count = len(music["song"]["tracks"])
    ps(f"MIDI ready: {pat_count} patterns, {trk_count} tracks")

    actor["actorBlueprint"]["components"]["Music"] = music
    with open(bp_path, "w", encoding="utf-8") as f:
        json.dump(actor, f, indent=2)

    bpm = get_bpm(mid)
    try:
        set_card_tempo(card, bpm)
        ps(f"Card tempo set to {bpm:.2f} BPM.")
    except FileNotFoundError:
        pw(f"Could not find card.json in {card} — tempo was not updated.")

    ps("MIDI added.")


CASTLE_API_URL = "https://api.castle.xyz/graphql"

def _env_flag(name: str) -> bool:
    """True if an env var is set to a truthy value (unset/'0'/'false'/'' = off)."""
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no")

def find_castle_token() -> str | None:
    """Look for a Castle CLI login token in the usual config locations."""
    candidates = []
    for var in ("CASTLE_CLI_HOME", "CASTLE_HOME"):
        val = os.environ.get(var)
        if val:
            candidates.append(Path(val))
    candidates.append(Path.home() / ".castle")
    for d in candidates:
        cfg = d / "config.json"
        if cfg.exists():
            try:
                token = json.loads(cfg.read_text(encoding="utf-8")).get("token")
                if token:
                    return token
            except (json.JSONDecodeError, OSError):
                continue
    return None

def _castle_graphql(token: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        CASTLE_API_URL, data=payload, method="POST",
        headers={
            "X-OS": "cli",
            "X-CLI-API-Version": "4",
            "X-Scene-Creator-Version": "latest",
            "X-Auth-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def _multipart_post(url, fields: dict, file_field_name, file_bytes, file_name, content_type):
    boundary = uuid.uuid4().hex
    parts = []
    for key, val in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field_name}"; '
        f'filename="{file_name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
    parts.append(file_bytes)
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def do_upload_html(deck: Path, card: Path):
    while True:
        raw = ask_path("Enter the file path for your HTML file")
        html_path = resolve_path(raw)
        if html_path.exists():
            break
        pe(f"File not found: {html_path}")

    with open(deck / "deck.json", "r", encoding="utf-8") as f:
        deck_meta = json.load(f)
    deck_id = deck_meta.get("deckId")
    if not deck_id:
        pe("This deck hasn't been uploaded yet. Use Upload Deck first, then try again.")
        return
    card_id = card.name

    token = find_castle_token()
    if not token:
        pe("Castle token not found. Run 'castle login' first.")
        return

    p()
    pb("Reading target deck metadata...")
    try:
        deck_resp = _castle_graphql(token, """
            query($deckId: ID!) {
              deck(deckId: $deckId) {
                title visibility variables
                initialCard { cardId title sceneDataUrl }
                cards { cardId title sceneDataUrl }
              }
            }""", {"deckId": deck_id})
    except Exception as e:
        pe(f"Failed to reach Castle: {e}")
        return

    deck_data = (deck_resp.get("data") or {}).get("deck")
    if not deck_data:
        pe("Castle didn't return this deck. Check that it's still yours and still exists.")
        return

    cards = deck_data.get("cards") or [deck_data.get("initialCard")]
    card_json = next((c for c in cards if c and c.get("cardId") == card_id), None)
    if not card_json:
        pe(f"Card {card_id} is not inside deck {deck_id}.")
        return

    scene_url = card_json.get("sceneDataUrl")
    card_title = card_json.get("title") or "Card"
    is_initial = (deck_data.get("initialCard") or {}).get("cardId") == card_id
    deck_title = deck_data.get("title") or "Untitled"
    deck_visibility = deck_data.get("visibility") or "unlisted"
    deck_variables = deck_data.get("variables") or []

    if scene_url:
        pb("Downloading existing scene file...")
        try:
            with urllib.request.urlopen(scene_url, timeout=15) as resp:
                scene = json.loads(resp.read())
        except Exception as e:
            pe(f"Failed to download scene data: {e}")
            return
    else:
        pb("No scene data url found. Creating blank snapshot...")
        scene = {"snapshot": {}}

    pb("Injecting HTML file into experimentalWeb bundle...")
    scene["experimentalWeb"] = {"enabled": True, "bundle": html_path.read_text(encoding="utf-8")}
    scene_bytes = json.dumps(scene).encode("utf-8")

    pb("Requesting signed upload parameters...")
    try:
        upload_resp = _castle_graphql(token, """
            mutation($cardIds: [ID!]!) {
              createSceneDataUploadConfig(cardIds: $cardIds) {
                uploadId postUrl postFields
              }
            }""", {"cardIds": [card_id]})
    except Exception as e:
        pe(f"Failed to reach Castle: {e}")
        return

    configs = (upload_resp.get("data") or {}).get("createSceneDataUploadConfig") or []
    if not configs:
        pe("Castle did not return an upload configuration.")
        return
    upload_config = configs[0]
    post_fields = upload_config.get("postFields") or {}

    # If the presigned POST policy declares a max size, check up front so we
    # get a clear error instead of an opaque HTTP failure later.
    policy_b64 = post_fields.get("policy")
    if policy_b64:
        try:
            policy = json.loads(base64.b64decode(policy_b64))
            max_bytes = next(
                (c[2] for c in policy.get("conditions", [])
                 if isinstance(c, list) and c and c[0] == "content-length-range"),
                None)
            if max_bytes is not None and len(scene_bytes) > max_bytes:
                pe("Your file is too large!")
                return
        except Exception:
            pass

    upload_id = upload_config.get("uploadId")
    post_url = upload_config.get("postUrl")

    pb("Uploading patched scene payload...")
    fields = {"Content-Type": "application/json", **post_fields}
    try:
        status, body = _multipart_post(post_url, fields, "file", scene_bytes,
                                        "scene.json", "application/json")
    except Exception as e:
        pe(f"Scene data upload failed: {e}")
        return
    if status >= 300:
        pe(f"Scene data upload failed with HTTP {status}")
        return

    pb("Attaching upload reference to deck...")
    deck_input = {
        "deckId": deck_id,
        "title": deck_title,
        "visibility": deck_visibility,
        "contentFlags": {
            "bloodOrGuns": False, "profanity": False, "sexuallySuggestive": False,
            "horrorOrFear": False, "alcoholOrDrugs": False, "loudSounds": False,
            "flashingLights": False,
        },
    }
    card_input = {"cardId": card_id, "title": card_title, "blocks": [], "uploadId": upload_id}
    if is_initial:
        deck_input["initialCardId"] = card_id
        deck_input["variables"] = deck_variables
        card_input["makeInitialCard"] = True

    try:
        update_resp = _castle_graphql(token, """
            mutation($deck: DeckInput!, $card: CardInput!) {
              updateCardAndDeckV2(deck: $deck, card: $card) {
                deck { deckId }
                card { cardId }
              }
            }""", {"deck": deck_input, "card": card_input})
    except Exception as e:
        pe(f"Failed to reach Castle: {e}")
        return

    final_deck_id = (((update_resp.get("data") or {})
                      .get("updateCardAndDeckV2") or {})
                     .get("deck") or {}).get("deckId")
    if not final_deck_id:
        pe("Castle rejected the deck update.")
        return

    ps("HTML uploaded!")
    pb(f"Live at: https://castle.xyz/d/{deck_id}")


def do_upload_deck(deck: Path):
    castle_argv = ["castle", "save-deck", str(deck)]
    if os.name == "nt":
        # On Windows, CreateProcess (used when shell=False) only tries
        # appending .exe to a bare command name — it doesn't check
        # PATHEXT the way a real shell does. Most CLI tools (including
        # Castle's) install as a .cmd shim, so a bare "castle" call
        # fails with WinError 2 even though it's on PATH and works fine
        # when typed into a terminal. Routing through cmd.exe /c gives
        # it the same PATHEXT-aware resolution the shell uses.
        castle_argv = ["cmd", "/c", *castle_argv]
    try:
        result = subprocess.run(castle_argv, capture_output=True, text=True)
    except FileNotFoundError:
        pe("Could not find the 'castle' CLI. Is it installed and on your PATH?")
        return
    combined = (result.stdout + result.stderr).lower()
    if result.returncode == 0:
        ps("Saved!")
        for line in result.stdout.strip().splitlines():
            print(f"   {line}")
    elif "memory access out of bounds" in combined:
        pe("Your file is too large!")
    else:
        pe("Save failed:")
        print(result.stdout)
        print(result.stderr)


def main():
    if "--version" in sys.argv[1:] or "-v" in sys.argv[1:]:
        print(f"castletool {get_installed_version()}")
        return

    p()
    pb("═══════════════")
    pb("   Castletool   ")
    pb("═══════════════")
    p()

    check_for_update()
    ensure_dependencies()
    p()

    # ── select deck ──
    home = Path.cwd()
    decks = find_decks(home)
    if not decks:
        pe("No decks were found. Are you in the right directory?")
        sys.exit(1)

    deck_names = [d.name for d in decks]
    pb(f"Detected decks: {', '.join(deck_names)}")
    if len(decks) == 1:
        deck = decks[0]
        ps(f"Auto selecting {deck.name}")
    else:
        chosen = choose("Select the deck you would like to modify:", deck_names)
        deck = home / chosen
    p()

    # ── select card ──
    cards = find_cards(deck)
    if not cards:
        pe(f"No cards found in {deck}.")
        sys.exit(1)
    card_names = [c.name for c in cards]
    if len(cards) == 1:
        card = cards[0]
        ps(f"Auto selecting {card.name}")
    else:
        chosen = choose("Select the card you would like to edit:", card_names)
        card = deck / "cards" / chosen
    p()

    # ── select blueprint (actor) ──
    blueprints = find_blueprints(card)
    if not blueprints:
        pe(f"No blueprints found in {card}.")
        sys.exit(1)
    bp_names = [b.name for b in blueprints]
    if len(blueprints) == 1:
        bp_path = blueprints[0]
        ps(f"Auto selecting {bp_path.name}")
    else:
        chosen = choose("Select the actor you want to edit:", bp_names)
        bp_path = card / "scene" / "blueprints" / chosen
    p()

    with open(bp_path, "r", encoding="utf-8") as f:
        actor = json.load(f)

    # ── action menu ──
    while True:
        options = []
        if HAS_PIL:
            options.append("Add image")
        if HAS_MIDO:
            options.append("Add MIDI")
        options.append("Edit Background Color")
        if _env_flag("CASTLETOOL_HTML"):
            options.append("Upload HTML")
        options.append("Upload Deck")
        options.append("Exit Tool")

        action = choose("Select the action you want to perform:", options)

        if action == "Add image":
            do_add_image(bp_path, actor, card)
        elif action == "Add MIDI":
            do_add_midi(bp_path, actor, card)
        elif action == "Edit Background Color":
            do_edit_background_color(card)
        elif action == "Upload HTML":
            do_upload_html(deck, card)
        elif action == "Upload Deck":
            do_upload_deck(deck)
        elif action == "Exit Tool":
            break
    p()


if __name__ == "__main__":
    main()
