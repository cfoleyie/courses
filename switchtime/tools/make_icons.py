"""Regenerate the PWA icons.

Chrome builds an Android home-screen app from the manifest icons, and that path
is only reliably fed by PNGs at 192 and 512 — an SVG-only icon set is accepted
by the manifest parser but is a common reason an install offer never appears.
The art is drawn here rather than rasterised from icon.svg so the repo needs no
SVG toolchain to reproduce it.

    python tools/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parents[1] / "switchtime" / "static"
GREEN = (47, 111, 94, 255)
WHITE = (255, 255, 255, 255)

#: Fraction of the canvas the clock occupies. Maskable icons are cropped to a
#: circle on some launchers, so their art has to sit inside the safe zone.
SCALE_STANDARD = 0.54
SCALE_MASKABLE = 0.40


def draw_icon(size: int, *, maskable: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if maskable:
        draw.rectangle([0, 0, size, size], fill=GREEN)
    else:
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill=GREEN)

    centre = size / 2
    radius = size * (SCALE_MASKABLE if maskable else SCALE_STANDARD) / 2
    stroke = max(2, round(size * 0.0625 * (0.75 if maskable else 1.0)))

    draw.ellipse(
        [centre - radius, centre - radius, centre + radius, centre + radius],
        outline=WHITE,
        width=stroke,
    )
    # Hands: twelve o'clock, and roughly four o'clock.
    draw.line([centre, centre - radius * 0.62, centre, centre], fill=WHITE, width=stroke)
    draw.line(
        [centre, centre, centre + radius * 0.44, centre + radius * 0.32],
        fill=WHITE,
        width=stroke,
    )
    return img


def main() -> None:
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ]
    for name, size, maskable in targets:
        path = STATIC / name
        draw_icon(size, maskable=maskable).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(STATIC.parents[1])} ({size}x{size})")


if __name__ == "__main__":
    main()
