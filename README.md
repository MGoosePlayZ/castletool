# castletool

Castletool is a terminal tool for injecting files into Castle decks You can inject full color images, GIFs, videos, SVGs, MIDI music, and fonts. (Not affiliated with Monterey's Coast, Inc.)

### Installation

```
pip install castletool
```

Requires Python 3.10+ and the [Castle CLI](https://docs.castle.xyz/docs/cli) logged in for deck uploads to work.

### Usage

Run `castletool` from inside (or above) a folder containing your Castle
deck(s), and follow the prompts. `cd` into where your decks are located (usually `~/decks`) if it says it can't find any.

There are two modes:

- **`castletool`** opens the default TUI (built with [Textual](https://github.com/Textualize/textual)).
- **`castletool --cli`** (or `castletool-cli`) opens original terminal interface.

Either way, it works the same way: pick a **deck**, then a **card**, then a **blueprint** (aka. actor) to edit, then an **action** to perform.

`castletool --version` (or `-v`) prints the installed version.

### What you can do

- **Add image** — bitmap images, animated GIF/WEBP/APNG, video (via ffmpeg), and SVG are all supported. Raster images are scaled with nearest-neighbor (no color blending, stays crisp for pixel art). Optional per-frame quantizing and "keep every Nth frame" thinning if you're pushing Castle's size limit.
- **Add MIDI** — converts a MIDI file into a Castle `Music` component and syncs the card's tempo to match.
- **Add Font** — renders a font's glyphs as vector line art directly into the blueprint. See below for the two ways to pick which characters to render.
- **Edit Background Color** — sets the card's background color.
- **Upload Deck** — runs `castle save-deck` on the current deck.

### Add Font: Basic vs Advanced mode

**Basic mode** gives you a list of preset unicode ranges select as many as you want:

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

Multiple sets are merged together (without duplicates), so picking Mathematical Operators + Miscellaneous Technical + Greek Characters or something else in one pass works fine.

**Advanced mode** lets you specify exact characters and/or codepoints
yourself, either typed directly or loaded from a file:

- Plain characters are typed as-is: `0123456789ABCDEF`.
- A specific codepoint is written `U+XXXX` (hex): `U+03A9` is Ω.
- Separate every `U+XXXX` codepoint with a space something like `U+03A9U+0021` is invalid.
- Any character or codepoint used twice is is rejected.

Loading from a file uses the same rules, plus:
- Newlines are ignored
- `--` starts a comment that runs to the end of the line.

### FAQ

Q: It says I don't have any decks, what do I do?

A: You can initialize a deck by running `castle init <name>` or get a pre-existing one by running `castle get-deck <id> folder`

---

Q: What does quantizing mean?

A: Quantizing automatically makes your image use less data, but it may look worse if the value is too low.

---

Q: What does it mean by "frame split"?

A: It divides your frames by the value you input. For example, if you enter "2", you will get half the frames.

---

Q: Why does it say I don't have any decks?

A: You are probably running the command while in a different directory. `cd` into where your deck folder is located (usually `~/decks`)

---

Q: Add Font says a character set/file has no matches, or skipped some characters — why?

A: Not every font implements every unicode block. Codepoints the font has no glyph for are skipped automatically (you'll get a warning listing how many).