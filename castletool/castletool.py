#!/usr/bin/env python3
"""
castle_tool.py — Interactive Castle deck editor
Streamlines injecting images/GIFs and MIDI into Castle blueprint JSON files.
"""

import base64
import copy
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

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

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import PathCompleter
    from prompt_toolkit.styles import Style
    HAS_PT = True
except ImportError:
    HAS_PT = False

HAS_FZF = shutil.which("fzf") is not None

try:
    from svg_to_castle import svg_to_path_data, build_drawing2_vector
    HAS_SVG = True
except ImportError:
    HAS_SVG = False
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
    while True:
        ans = ask(prompt + " (y/n)", default=default).lower()
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

def fzf_pick_file(start_dir: Path) -> str | None:
    """Open fzf to fuzzy-find a file under start_dir. Returns path string or None."""
    try:
        # find all files under start_dir, pipe into fzf
        find = subprocess.run(
            ["find", str(start_dir), "-type", "f"],
            capture_output=True, text=True
        )
        fzf = subprocess.run(
            ["fzf", "--prompt", "Select file> ", "--height", "40%",
             "--layout", "reverse", "--border"],
            input=find.stdout,
            capture_output=True, text=True
        )
        result = fzf.stdout.strip()
        return result if result else None
    except Exception:
        return None


def ask_path(prompt, default=None, search_dir: Path | None = None):
    """
    File path input. Priority:
      1. fzf fuzzy picker (if fzf installed)
      2. prompt_toolkit tab-complete (if installed)
      3. plain input fallback
    """
    suffix = f" [{default}]" if default is not None else ""
    pb(prompt + suffix)

    if HAS_FZF:
        start = search_dir or Path.cwd()
        ps(f"Opening fzf in {start} — type to fuzzy search, Enter to select, Esc to type manually.")
        picked = fzf_pick_file(start)
        if picked:
            ps(f"Selected: {picked}")
            return picked
        pw("fzf cancelled, falling back to manual input.")

    if HAS_PT:
        try:
            from prompt_toolkit.formatted_text import FormattedText
            val = pt_prompt(
                FormattedText([("bold", "Path: ")]),
                completer=PathCompleter(expanduser=True),
                complete_while_typing=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            p(); sys.exit(0)
    else:
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

def check_storage_setup() -> bool:
    return (Path.home() / "storage").exists()

def setup_termux_storage():
    p()
    pw("It looks like you do not have storage set up.")
    if yn("Would you like to set it up now?"):
        pb("Running 'termux-setup-storage'...")
        subprocess.run(["termux-setup-storage"])
        ps("Setup complete! You may need to restart the script.")
        sys.exit(0)

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

# ── image/gif → Drawing2 ─────────────────────────────────────────────────────

def load_image_frames(path: Path, size: int):
    img = Image.open(path)

    # Normal image
    if not getattr(img, "is_animated", False):
        frame = img.convert("RGBA").resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        return [buf.getvalue()], 1.0

    # Animated GIF
    frames = []
    durations = []

    try:
        while True:
            frame = img.convert("RGBA").resize((size, size), Image.LANCZOS)
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

def extract_mp4_frames(path: Path, size: int, every_n: int = 1) -> tuple[list[bytes], float]:
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

    # Extract frames as PNG via pipe
    result = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-vf", f"select='not(mod(n\\,{every_n}))',scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2",
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

import base64
import math

def build_drawing2(
    frames: list[bytes],
    fps: float,
    size: int,
    play_mode: str = "loop"
) -> dict:
    # Empirical scale formula
    scale = max(1, round(size / 20))

    half = size / 2
    bounds = {
        "minX": -half,
        "maxX": half,
        "minY": -half,
        "maxY": half,
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
                "p1": {"x": half / scale, "y": half / scale},
                "p2": {"x": -half / scale, "y": -half / scale},
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

# ── midi → Music ─────────────────────────────────────────────────────────────

def beat_key(b): return f"{b:.6f}"
def make_color(): return {"r": 0.19607, "g": 0.16862, "b": 0.15681, "a": 1.0}

def collect_midi_tracks(mid) -> list[list[tuple[float,int]]]:
    tpb = mid.ticks_per_beat
    result = []
    for track in mid.tracks:
        events, abs_tick = [], 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                events.append((abs_tick / tpb, msg.note))
        if events:
            result.append(events)
    return result

def events_to_bars(events, beats_per_bar):
    bars = {}
    for beat, note in events:
        idx = int(beat // beats_per_bar)
        rel = round(beat - idx * beats_per_bar, 9)
        bars.setdefault(idx, {}).setdefault(rel, []).append(note)
    return [(idx * beats_per_bar, notes) for idx, notes in sorted(bars.items())]

def build_music(midi_path: Path, beats_per_bar: int = 4) -> dict:
    mid = mido.MidiFile(midi_path)
    midi_tracks = collect_midi_tracks(mid)
    patterns, castle_tracks = {}, []
    for t_idx, events in enumerate(midi_tracks):
        seq = {}
        for bar_beat, notes_by_beat in events_to_bars(events, beats_per_bar):
            pid = str(uuid.uuid4())
            notes = {beat_key(b): [{"key": n} for n in ns]
                     for b, ns in sorted(notes_by_beat.items())}
            patterns[pid] = {
                "patternId": pid,
                "name": f"t{t_idx}-b{int(bar_beat//beats_per_bar)+1}",
                "color": make_color(), "loop": "nextBar", "loopLength": 0,
                "notes": notes,
            }
            seq[bar_beat] = pid
        castle_tracks.append({
            "instrument": {
                "type": "sampler",
                "props": {"name": "tone", "muted": False, "volume": 1},
                "sample": {
                    "type": "tone",
                    "playbackRate": {"value": 1}, "amplitude": {"value": 1},
                    "pan": {"value": 0}, "recordingUrl": "", "uploadUrl": "",
                    "category": "random", "seed": 1337, "mutationSeed": 0,
                    "mutationAmount": 5, "midiNote": 48, "waveform": "sawtooth",
                    "attack": 0, "release": 0.4, "wait": False,
                },
            },
            "sequence": {
                beat_key(b): {"patternId": pid, "loop": False}
                for b, pid in sorted(seq.items())
            },
        })
    return {
        "song": {"patterns": patterns, "tracks": castle_tracks},
        "autoplay": "loop", "disabled": False,
    }

# ── main flow ─────────────────────────────────────────────────────────────────

def main():
    p()
    pb("═══════════════════════════════════")
    pb("       Castle Blueprint Tool       ")
    pb("═══════════════════════════════════")
    p()

    # ── check deps ──
    missing = []
    if not HAS_PIL:   missing.append("Pillow        (pip install Pillow)")
    if not HAS_MIDO:  missing.append("mido          (pip install mido)")
    if not HAS_PT:    missing.append("prompt_toolkit (pip install prompt_toolkit)  — enables tab-complete for file paths")
    if not HAS_FZF:
        print(f"  {DIM}tip: install fzf for fuzzy file finding   (pkg install fzf){RESET}")
    if not HAS_FFMPEG:
        print(f"  {DIM}tip: install ffmpeg for MP4/video support  (pkg install ffmpeg){RESET}")
    if missing:
        pw("Missing optional dependencies (only needed for relevant features):")
        for m in missing: print(f"   • {m}")
        p()

    # ── android warning ──
    termux = is_termux()
    if termux:
        pw("Android/Termux detected. Use ~/storage/... paths for files.")
        if not check_storage_setup():
            setup_termux_storage()
        p()

    # ── select deck ──
    home = Path.cwd()
    decks = find_decks(home)
    if not decks:
        pe("No Castle decks found in the current directory.")
        pe("Run 'castle get-deck <id> <folder>' first.")
        sys.exit(1)

    deck_names = [d.name for d in decks]
    pb(f"Detected decks: {', '.join(deck_names)}")
    if len(decks) == 1:
        deck = decks[0]
        ps(f"Only one deck ({deck.name}), auto-selecting.")
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
        ps(f"Only one card ({card.name}), auto-selecting.")
    else:
        chosen = choose("Select the card you would like to edit:", card_names)
        card = deck / "cards" / chosen
    p()

    # ── select blueprint ──
    blueprints = find_blueprints(card)
    if not blueprints:
        pe(f"No blueprints found in {card}.")
        sys.exit(1)
    bp_names = [b.name for b in blueprints]
    if len(blueprints) == 1:
        bp_path = blueprints[0]
        ps(f"Only one blueprint ({bp_path.name}), auto-selecting.")
    else:
        chosen = choose("Select the blueprint you would like to edit:", bp_names)
        bp_path = card / "scene" / "blueprints" / chosen
    p()

    # ── load blueprint ──
    with open(bp_path, "r", encoding="utf-8") as f:
        actor = json.load(f)

    # ── image/gif? ──
    drawing2 = None
    if not HAS_PIL:
        pw("Pillow not installed, skipping image/GIF option.")
        do_image = False
    else:
        do_image = yn("Would you like to add an image or animation?")

    if do_image:
        while True:
            raw = ask_path("Enter the file path for your image")
            img_path = resolve_path(raw)
            if img_path.exists():
                break
            pe(f"File not found: {img_path}")

        ext = img_path.suffix.lower()
        is_anim = ext in (".gif", ".mp4", ".mov", ".webm", ".avi")
        is_video = ext in (".mp4", ".mov", ".webm", ".avi")
        is_vector = ext in (".svg",)
        file_size = img_path.stat().st_size

        p()
        if not is_vector:
            pw("Make sure this file is formatted correctly. You can verify by importing it in the Castle app.")
            pw("If it's corrupt and you ignore this, the card may become corrupted.")
            if not yn("Continue?"):
                sys.exit(0)

        # size
        p()
        resize = (not is_vector) and yn("Would you like to resize this image?", default="n")
        size, every, quantize = None, 1, 0
        if not is_vector:
            if resize:
                while True:
                    raw = ask("Enter size (e.g. 64x64 or just 64)", default="64x64")
                    raw = raw.strip().lower().replace("x", " ").split()
                    try:
                        size = int(raw[0])
                        break
                    except:
                        pe("Invalid size.")
            else:
                with Image.open(img_path) as _img:
                    size = max(_img.size)

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
            if file_size > 500_000 or yn("Would you like to quantize this image? (reduces file size, usually no visible difference at ≥256 colors)", default="n"):
                if file_size > 500_000:
                    pw(f"This file is abnormally large ({file_size//1024}KB). Quantizing is recommended.")
                while True:
                    raw = ask("Select number of colors", default="256")
                    if raw.isdigit() and 1 <= int(raw) <= 256:
                        quantize = int(raw)
                        break
                    pe("Enter a number between 1 and 256.")

        p()
        if is_vector:
            if not HAS_SVG:
                pe("svg_to_castle.py not found — place it in the same folder as castle_tool.py")
                sys.exit(1)
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
                    sys.exit(1)
                frames, fps = extract_mp4_frames(img_path, size, every_n=every)
            else:
                frames, fps = load_image_frames(img_path, size)
                if every > 1:
                    frames = frames[::every]
                    fps = fps / every

            if quantize:
                pb(f"Quantizing {len(frames)} frame(s) to {quantize} colors...")
                frames = [quantize_frame(f, quantize) for f in frames]

            play_mode = "loop" if is_anim else "still"
            drawing2 = build_drawing2(frames, fps, size)
            ps(f"Image ready: {len(frames)} frame(s), {fps} FPS, {size}×{size}px")

    # ── midi? ──
    music = None
    if not HAS_MIDO:
        pw("mido not installed, skipping MIDI option.")
        do_midi = False
    else:
        p()
        do_midi = yn("Would you like to add a MIDI file?")

    if do_midi:
        while True:
            raw = ask_path("Enter your MIDI file path")
            midi_path = resolve_path(raw)
            if midi_path.exists():
                break
            pe(f"File not found: {midi_path}")

        p()
        pb(f"Loading MIDI: {midi_path.name}")
        mid = mido.MidiFile(midi_path)
        midi_track_count = sum(
            1 for t in mid.tracks
            if any(m.type == "note_on" and m.velocity > 0 for m in t)
        )
        music = build_music(midi_path)
        pat_count = len(music["song"]["patterns"])
        trk_count = len(music["song"]["tracks"])
        ps(f"MIDI ready: {pat_count} patterns, {trk_count} tracks")

    if drawing2 is None and music is None:
        pw("Nothing to do. Exiting.")
        sys.exit(0)

    # ── confirm overwrite ──
    p()
    what = []
    if drawing2: what.append("image/animation (Drawing2)")
    if music:    what.append("music (Music)")
    pw(f"This will overwrite {' and '.join(what)} in:\n   {bp_path}")
    if not yn("Are you sure you want to modify this blueprint?"):
        sys.exit(0)

    # ── inject ──
    if drawing2:
        actor["actorBlueprint"]["components"]["Drawing2"] = drawing2
    if music:
        actor["actorBlueprint"]["components"]["Music"] = music

    with open(bp_path, "w", encoding="utf-8") as f:
        json.dump(actor, f, indent=2)
    ps(f"Blueprint written to {bp_path}")

    # ── save ──
    p()
    if yn("Would you like to save this deck now?"):
        result = subprocess.run(["castle", "save-deck", str(deck)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            ps("Saved!")
            for line in result.stdout.strip().splitlines():
                print(f"   {line}")
        else:
            pe("Save failed:")
            print(result.stdout)
            print(result.stderr)
    p()


if __name__ == "__main__":
    main()
