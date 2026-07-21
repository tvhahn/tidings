"""Regenerate the Tidings wordmark SVGs with the text outlined to paths.

GitHub (and any renderer without Source Serif 4 installed) falls back to
Georgia for the wordmark's <text> element, so the canonical assets carry
the glyphs as outlined paths instead. This script rebuilds them from the
Source Serif 4 variable font, instanced to match what a browser renders
for the marketing site's wordmark: weight 600, optical size = font size.

Usage:
    uv run --with fonttools --with uharfbuzz \
        scripts/media/outline_wordmark.py path/to/SourceSerif4[opsz,wght].ttf

Font source (OFL): https://github.com/google/fonts/tree/main/ofl/sourceserif4

Writes logo-wordmark.svg and logo-wordmark-dark.svg into docs/brand/assets/.
The light file carries a prefers-color-scheme media query so it adapts when
rendered as a standalone image (e.g. the GitHub README); the dark file is a
static variant for surfaces where media queries do not apply.
"""

import sys
from io import BytesIO
from pathlib import Path

import uharfbuzz as hb
from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

TEXT = "Tidings"
FONT_SIZE = 54  # matches the retired <text font-size="54">
X_START = 100.0  # matches <text x="100">
BASELINE = 66.0  # matches <text y="66">
LETTER_SPACING = -1.0  # matches <text letter-spacing="-1">
AXES = {"wght": 600, "opsz": FONT_SIZE}

INK_LIGHT = "#1D1917"  # light-surface ink (--foreground light)
INK_DARK = "#FAFAFA"  # dark-surface ink (--foreground dark, oklch(0.985 0 0))
RUST = "#C4532C"

MARK = """  <svg x="12" y="13" width="80" height="70" viewBox="0 0 417 320" fill="none" stroke="#C4532C" stroke-width="20" stroke-linecap="round" stroke-linejoin="round" overflow="visible">
    <rect x="29" y="24" width="355" height="273" rx="41"></rect>
    <path d="M35 75 L103 129"></path>
    <path d="M91 242 C 131 212, 136 190, 164 190 C 192 190, 200 217, 228 217 C 256 217, 292 174, 332 144"></path>
  </svg>"""

# Painted horizontal extent of the mark in outer coordinates. The rounded rect
# (plus half its stroke) is the left-most and right-most painted part of the
# icon, and the icon is the left-most element of the whole lockup. These bound
# the viewBox so it hugs the content instead of trailing a wide empty gutter to
# the right of "Tidings" (which made the wordmark look left-shifted when a
# centered container — e.g. the GitHub README — centered the image box).
_MARK_SCALE = 80 / 417  # inner viewBox width (417) placed at 80px wide
_HALF_STROKE = 20 / 2
MARK_LEFT = 12 + (29 - _HALF_STROKE) * _MARK_SCALE
MARK_RIGHT = 12 + (29 + 355 + _HALF_STROKE) * _MARK_SCALE


def outline_text(font_path: Path) -> tuple[str, tuple[float, float, float, float]]:
    """Return (SVG path data for TEXT, (xMin, yMin, xMax, yMax) of the glyphs)."""
    font = TTFont(font_path)
    if "fvar" in font:
        instantiateVariableFont(font, AXES, inplace=True)
    upem = font["head"].unitsPerEm
    scale = FONT_SIZE / upem

    buf = BytesIO()
    font.save(buf)
    hb_font = hb.Font(hb.Face(buf.getvalue()))

    hb_buf = hb.Buffer()
    hb_buf.add_str(TEXT)
    hb_buf.guess_segment_properties()
    hb.shape(hb_font, hb_buf, {"kern": True, "liga": True})

    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    bounds_pen = BoundsPen(glyph_set)  # exact painted bounds (curve extrema)
    x = X_START
    parts = []
    for info, pos in zip(hb_buf.glyph_infos, hb_buf.glyph_positions):
        name = glyph_order[info.codepoint]
        pen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.1f}")
        transform = Transform(
            scale, 0, 0, -scale, x + pos.x_offset * scale, BASELINE - pos.y_offset * scale
        )
        glyph_set[name].draw(TransformPen(pen, transform))
        glyph_set[name].draw(TransformPen(bounds_pen, transform))
        if commands := pen.getCommands():
            parts.append(commands)
        x += pos.x_advance * scale + LETTER_SPACING
    return " ".join(parts), bounds_pen.bounds


def svg(word_path: str, adaptive: bool, view_w: int) -> str:
    if adaptive:
        fill = (
            f"<style>.word{{fill:{INK_LIGHT}}}"
            f"@media(prefers-color-scheme:dark){{.word{{fill:{INK_DARK}}}}}</style>\n  "
        )
        path = f'<path class="word" d="{word_path}"/>'
    else:
        fill = ""
        path = f'<path fill="{INK_DARK}" d="{word_path}"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w} 96" fill="none">\n'
        f"  {fill}{MARK}\n"
        f"  {path}\n"
        "</svg>\n"
    )


def main() -> None:
    font_path = Path(sys.argv[1])
    assets = Path(__file__).resolve().parents[2] / "docs" / "brand" / "assets"
    word_path, (x_min, _y_min, x_max, _y_max) = outline_text(font_path)
    # The icon is the left-most painted element; "Tidings" is the right-most.
    # Size the viewBox so the right gutter matches the left inset -> centered.
    content_left = min(MARK_LEFT, x_min)
    content_right = max(MARK_RIGHT, x_max)
    view_w = round(content_left + content_right)
    print(
        f"text x-extent {x_min:.1f}..{x_max:.1f}; content {content_left:.1f}..{content_right:.1f}; "
        f"viewBox 0 0 {view_w} 96 (margins L={content_left:.1f} R={view_w - content_right:.1f})"
    )
    (assets / "logo-wordmark.svg").write_text(svg(word_path, adaptive=True, view_w=view_w))
    (assets / "logo-wordmark-dark.svg").write_text(svg(word_path, adaptive=False, view_w=view_w))
    print(f"wrote {assets}/logo-wordmark.svg and logo-wordmark-dark.svg")


if __name__ == "__main__":
    main()
