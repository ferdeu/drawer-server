"""Draws the panel's home-screen icon into termux/panel/ (step 8 copies it to the phone).

The PNGs are already in the repo; run this only to change the icon: python scripts/panel-icons.py
Needs Pillow on your computer: pip install pillow
"""
from pathlib import Path

from PIL import Image, ImageDraw

BLUE, WHITE, GREEN = "#2563eb", "#ffffff", "#16a34a"  # the panel's own colors
OUT = Path(__file__).resolve().parent.parent / "termux" / "panel"


def icon(size, maskable=False):
    s = 4 * size  # draw big, shrink for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill=BLUE)
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BLUE)
    k = 0.8 if maskable else 1.0  # Android crops maskable icons to a circle: keep the house inside it

    def p(x, y):
        return (s / 2 + (x - 0.5) * s * k, s / 2 + (y - 0.5) * s * k)

    d.polygon([p(0.5, 0.2), p(0.82, 0.48), p(0.18, 0.48)], fill=WHITE)  # roof
    d.rectangle([*p(0.27, 0.46), *p(0.73, 0.78)], fill=WHITE)  # walls
    d.rounded_rectangle([*p(0.44, 0.58), *p(0.56, 0.78)], radius=s * 0.02 * k, fill=BLUE)  # door
    for r, color in ((0.075, BLUE), (0.055, GREEN)):  # "everything works" dot, with a ring around it
        d.ellipse([*p(0.73 - r, 0.71 - r), *p(0.73 + r, 0.71 + r)], fill=color)
    return img.resize((size, size), Image.Resampling.LANCZOS)


icon(192).save(OUT / "icon-192.png")
icon(512).save(OUT / "icon-512.png")
icon(512, maskable=True).save(OUT / "icon-maskable.png")
icon(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png")  # iPhones round the corners
print(f"Icons written to {OUT}; run step 8 to put them on the phone")
