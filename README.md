# castletool
[![PyPI Version](https://img.shields.io/pypi/v/castletool.svg)](https://pypi.org/project/castletool/)
[![Python Versions](https://img.shields.io/pypi/pyversions/castletool.svg)](https://pypi.org/project/castletool/)
[![Downloads](https://img.shields.io/pypi/dm/castletool.svg)](https://pypistats.org/packages/castletool)
[![License](https://img.shields.io/github/license/MGoosePlayZ/castletool.svg)](https://github.com/MGoosePlayZ/castletool)
[![Build Status](https://img.shields.io/github/actions/workflow/status/MGoosePlayZ/castletool/python-publish.yml)](https://github.com/MGoosePlayZ/castletool)


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

- **Add image** — bitmap images, animated GIF/WEBP/APNG, video (with sound), and SVG are all supported. SVGs can be drawn as vector line segments or as a filled bitmap.
- **Add audio** — uploads a sound to Castle and plays it from the actor on create (looped), the same way a video's sound is added. Castle limits sounds to 30 seconds, so longer audio (and longer video soundtracks) is split into parts just under 30s, uploaded one by one, and chained to play back to back.
- **Add MIDI** — converts a MIDI file into a Castle `Music` component.
- **Add Font** — renders a font's characters as vector outlines or as filled bitmap glyphs.
- **Edit Background Color** — sets the card's background color.
- **Upload Deck** — runs `castle save-deck` on the current deck.

## Supported file types

| Purpose | Extensions |
| --- | --- |
| Images | png, jpg/jpeg, bmp, tif/tiff, ico, heic/heif, gif, webp, apng |
| Video | mp4, mov, webm, avi, mkv, flv, m4v, 3gp, ogv |
| Vector graphics | svg |
| Audio | mp3, wav, ogg/oga, m4a, flac, aac |
| Fonts | ttf, otf, woff, eot |

- `.ico` files hold several resolutions; castletool asks which one to use.
- `.heic`/`.heif` need the optional `pillow-heif` package (`pip install castletool[heif]`); castletool tries to install it the first time you use one.
- Video, audio conversion and the sound of videos need `ffmpeg`. MTX-compressed `.eot` fonts aren't supported.
- Anything else is rejected with a message. If you want a format added, [open an issue](https://github.com/MGoosePlayZ/castletool/issues).

## Archives

Anywhere castletool asks for a file you can give a `.zip`, `.tar`, `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2` or `.tar.xz`/`.txz` instead. Subdirectories are searched and unsupported files inside are ignored.

- All supported files in an archive must have the **same purpose** (all images, all videos, all audio, ...). Otherwise you get `Supported files are of different purpose`.
- **Still images and SVGs**: you choose between putting them all in the current actor as frames (in natural filename order), or making each its own actor. You also choose how sizes are handled:
  - *Scale images to fit* keeps all images the same size.
  - *Don't scale images* keeps 1 pixel = 1 pixel no matter what (every image shares one pixel density, so bigger images appear bigger). Best for pixel art or small images where accuracy matters.
- **Animated images, videos, SVGs, audio and fonts**: each file automatically becomes its own actor. The first goes into the actor you selected; the rest are forked from it as new blueprints in the same card.
- The same settings (scale, quantize, characters, ...) are used for every file in the archive.

## Bitmap SVGs and fonts

- **SVG** — in an archive, SVGs can also go in one actor as frames (vector or bitmap). Choose *Vector* (line segments, the default) or *Bitmap* (filled in, keeps its colors; even-odd fill, so holes work). Not supported: gradients, transforms, `<style>` blocks/classes.
- **Font** — choose *Vector* (outlines) or *Bitmap* (one filled image per glyph, drawn with FreeType at a pixel size you choose). Glyphs share one canvas and baseline so frames don't jump.
- **Colors** — an SVG's own colors (attributes, inline `style`, inherited from groups) are used by default. If a shape doesn't specify one, you pick a color for those shapes. Fonts always ask you to pick a color.
- **Bilinear interpolation** — off by default (crisp nearest-neighbor pixels). Turn it on for smooth scaling of images and video, and for anti-aliased edges on bitmap SVGs and fonts.

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
