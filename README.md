# castletool
[![PyPI Version](https://img.shields.io/pypi/v/castletool.svg)](https://pypi.org/project/castletool/)
[![Python Versions](https://img.shields.io/pypi/pyversions/castletool.svg)](https://pypi.org/project/castletool/)
[![Downloads](https://img.shields.io/pypi/dm/castletool.svg)](https://pypistats.org/packages/castletool)
[![License](https://img.shields.io/github/license/MGoosePlayZ/castletool.svg)](https://github.com/MGoosePlayZ/castletool)

Images, vector graphics, videos, audio. You name it, castletool (probably) supports it.

Castletool is a custom tool that lets you import things to castle more easily.

## Installation

```
pip install castletool
```

Requires Python and the [Castle CLI](https://docs.castle.xyz/docs/cli)

## Usage

Run `castletool` inside a folder containing your Castle deck(s).
You may also use `castletool --cli` for the legacy interface.
`castletool --version` (or `-v`) prints the installed version.

## Capabilities

- **Add image** — bitmap images, animated GIF/WEBP/APNG, video (with sound), and SVG are all supported.
- **Add MIDI** — converts a MIDI file into a Castle `Music` component.
- **Add Font** — renders a font's characters as vectors.
- **Edit Background Color** — sets the card's background color.
- **Upload Deck** — runs `castle save-deck` on the current deck.

## Add Font: Basic

Choose from preset unicode ranges and select as many as you want:

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

## Add Font: Advanced
Choose all characters/codepoints yourself:

- Plain characters are typed as-is: `0123456789ABCDEF`.
- A specific codepoint is written `U+XXXX` (hex): `U+03A9` is Ω.
- Separate every codepoint with a space: Something like `U+03A9U+0021` is invalid.
- Any character or codepoint used twice is rejected.

Loading from a file uses the same rules, plus `--` starts a comment that runs to the end of the line.

## Star History

<a href="https://www.star-history.com/?repos=mgooseplayz%2Fcastletool&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=mgooseplayz/castletool&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=mgooseplayz/castletool&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=mgooseplayz/castletool&type=date&legend=top-left" />
 </picture>
</a>
