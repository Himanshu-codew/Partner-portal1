"""Generate the PWA icons for the Partner Portal (development helper).

Usage:
    python scripts/make_icons.py

This is a one-off/dev script, not part of the runtime.  It draws a simple
brand mark (a white "P" on the dark-navy sidebar gradient) and writes:

    static/icons/icon-192.png
    static/icons/icon-512.png
    static/icons/icon-maskable-512.png   (content kept inside the safe zone)

Pillow is an optional dependency.  If it is not installed the committed
hand-written SVG fallbacks (static/icons/*.svg) are used instead — see
docs/pwa.md.
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / 'static' / 'icons'

# Brand colours (match static/css/portal.css sidebar tokens)
NAVY_TOP = (30, 41, 59)      # #1e293b
NAVY_BOTTOM = (15, 23, 42)   # #0f172a
BRAND = (59, 130, 246)       # #3b82f6
WHITE = (255, 255, 255, 255)


def _load_font(px):
    from PIL import ImageFont
    candidates = [
        r'C:\Windows\Fonts\arialbd.ttf',
        r'C:\Windows\Fonts\arial.ttf',
        'arialbd.ttf',
        'Arial Bold.ttf',
        'DejaVuSans-Bold.ttf',
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _vertical_gradient(size, top, bottom):
    from PIL import Image
    img = Image.new('RGB', (1, size), top)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        img.putpixel((0, y), tuple(
            round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)
        ))
    return img.resize((size, size))


def make_icon(size, out_path, maskable=False):
    from PIL import Image, ImageDraw

    img = _vertical_gradient(size, NAVY_TOP, NAVY_BOTTOM).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # Circle behind the mark. Maskable icons keep everything inside the
    # central 80% safe zone so platform masking never crops the mark.
    radius = int(size * (0.30 if maskable else 0.34))
    cx = cy = size // 2
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=BRAND,
    )

    # Bold "P" centred in the circle.
    font = _load_font(int(size * (0.34 if maskable else 0.38)))
    text = 'P'
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
                  text, font=font, fill=WHITE)
    except Exception:  # very old Pillow without textbbox
        tw, th = draw.textsize(text, font=font)
        draw.text((cx - tw / 2, cy - th / 2), text, font=font, fill=WHITE)

    img.convert('RGB').save(out_path, 'PNG')
    print(f'wrote {out_path} ({size}x{size})')


def main():
    try:
        import PIL  # noqa: F401
    except ImportError:
        print('Pillow is not installed — commit the SVG fallbacks instead '
              '(static/icons/*.svg).', file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_icon(192, OUT_DIR / 'icon-192.png')
    make_icon(512, OUT_DIR / 'icon-512.png')
    make_icon(512, OUT_DIR / 'icon-maskable-512.png', maskable=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
