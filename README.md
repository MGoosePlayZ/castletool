# castletool

Castletool is a terminal tool for building out Castle - Make and Play decks
without opening the app: injecting images, GIFs, videos, SVGs, MIDI music,
and vector-rendered fonts into Castle blueprint JSON files, and uploading
decks straight from the command line. (Not affiliated with Monterey's Coast, Inc.)

### Installation

```
pip install castletool[all]
```

Requires Python 3.10+ and the [Castle CLI](https://docs.playcastle.io) already
set up and logged in (`castle login`) for deck uploads to work. Castletool will
auto-install its own Python dependencies (Pillow, mido, fonttools) and ffmpeg
on first run if they're missing, so a plain `pip install castletool` also
works — `[all]` just avoids that first-run pause.

### Usage

Run `castletool` from inside (or above) a folder containing your Castle
deck(s), and follow the prompts. `cd` into where your decks live first
(usually `~/decks`) if it says it can't find any.

Two interfaces ship in the same package:

- **`castletool`** — the default tap/click TUI (built with
  [Textual](https://github.com/Textualize/textual)). Menus are tapped or
  clicked instead of typed.
- **`castletool --cli`** (or the separate `castletool-cli` command) — the
  original plain-typing terminal interface. Useful on setups where a full
  TUI doesn't render well.

Either way, the flow is the same: pick a **deck**, then a **card**, then a
**blueprint** (actor) to edit, then an **action** to perform. Every step has
an `Exit Tool` option, and once you're past the first pick you can jump
back with `« Change Deck` / `« Change Card` / `« Change Blueprint` instead
of restarting.

`castletool --version` (or `-v`) prints the installed version.

### What you can do to a blueprint

- **Add image** — bitmap images, animated GIF/WEBP/APNG, video (via
  ffmpeg), and SVG are all supported. Raster images are scaled with
  nearest-neighbor (no color blending, stays crisp for pixel art).
  Optional per-frame quantizing and "keep every Nth frame" thinning if
  you're pushing Castle's size limit.
- **Add MIDI** — converts a MIDI file into a Castle `Music` component and
  syncs the card's tempo to match. Note velocity (0-127) is carried over
  into each note's `vel` field.
- **Add Font** — renders a font's glyphs as vector line art directly into
  the blueprint's `Drawing2`, one frame per character (not one actor per
  character — it's all one actor you can flip through by frame). See
  below for the two ways to pick which characters to render.
- **Edit Background Color** — sets the card's background color.
- **Upload Deck** — runs `castle save-deck` on the current deck.

### Add Font: Basic vs Advanced mode

**Basic mode** gives you a checklist of preset unicode ranges — tap/click
(or number-select in `--cli`) as many as you want, then confirm:

- Standard (0-255, excluding control characters)
- ASCII
- Alphanumeric
- Numeric
- Currency Symbols
- Greek Characters
- Fraction Symbols
- Arrows
- Mathematical Operators
- Miscellaneous Technical
- Box Drawing
- Block Elements
- Dingbats
- Braille Patterns
- Musical Symbols

Multiple sets are unioned together (duplicates removed automatically), so
picking Mathematical Operators + Miscellaneous Technical + Greek Characters
in one pass works fine.

**Advanced mode** lets you specify exact characters and/or codepoints
yourself, either typed directly or loaded from a file:

- Plain characters are typed as-is: `0123456789ABCDEF`.
- A specific codepoint is written `U+XXXX` (hex): `U+03A9` is Ω.
- Separate every `U+XXXX` codepoint with a space — gluing two together
  (`U+03A9U+0021`) is invalid.
- Any character or codepoint used twice is a duplicate and is rejected.

Recognized characters/codepoints are shown in **blue** as you type;
duplicates or malformed `U+....` tokens are shown in **red**. In the TUI
this updates live as you type; the entry won't submit until every token is
blue.

```
Valid:   0123456789ABCDEF U+03A9
Invalid: 001234565789ABCCDEF U+03A9 U+03A9U+0021
         (duplicate 0/5/C, and U+03A9U+0021 isn't space-separated)
```

Loading from a file uses the same rules, plus:

- Newlines are ignored — the whole file is treated as one continuous spec.
- `--` starts a comment that runs to the end of the line (two hyphens
  specifically, so it isn't triggered by accident).

```
0123456789 -- numbers
ABCDEF -- hex
U+03A9 -- omega symbol
-- this whole line is a comment
```

A file is validated the same way as typed input; if it contains
duplicates or malformed tokens, castletool shows you the colored
breakdown and stops without touching the blueprint.

### FAQ

Q: It says I don't have any decks, what do I do?

A: You can initialize a deck by running `castle init <name>` or get a pre-existing one by running `castle get-deck <id> folder`

---

Q: Why does it say "nothing to do"?

A: You either forgot to install Pillow/ffmpeg/mido/fonttools, or you said no to all the prompts.

---

Q: What does quantizing mean?

A: Quantizing automatically makes your image use less data, but it may look worse if the value is too low.

---

Q: What does it mean by "frame split"?

A: It divides your frames by the value you input. For example, if you enter "2", you will get half the frames.

---

Q: What does "Memory Access Out of Bounds" mean?

A: That means the image or MIDI file you input caused your deck to exceed Castle's 10MB limit. You need to quantize it or use less frames.

---

Q: Why does it say I don't have any decks?

A: You are probably running the command while in a different directory. `cd` into where your deck is (usually `~/decks`)

---

Q: Add Font says a character set/file has no matches, or skipped some characters — why?

A: Not every font implements every unicode block. Codepoints the font has no glyph for are skipped automatically (you'll get a warning listing how many); if none of the requested codepoints exist in the font at all, nothing is written and the blueprint is left untouched.

---

Q: Can I still upload raw HTML into a card?

A: No — this was removed. Castle's Cauldron editor (currently in beta) ignores requests containing `experimentalWeb`, which made the HTML upload feature nonfunctional.
