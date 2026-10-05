"""Developer tool: draws the program's icon - LEIFEG in Cinzel, gold letters on a purple swirl in a
gold ring - as packaging/icon.png (512 px) and packaging/icon.ico (the Windows executable's, 16-256 px).

    pip install pillow numpy
    python packaging/make_icon.py [--font path/to/Cinzel.ttf]

Cinzel (Natanael Gama, SIL Open Font License 1.1, https://github.com/NDISCOVER/Cinzel) is downloaded from
the Google Fonts repository unless given: only the letters drawn with it end up in the icon. Everything
else is drawn here (seeded noise, so the same icon comes out every time).
"""
from __future__ import annotations

import argparse
import io
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_URL = "https://github.com/google/fonts/raw/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf"
OUT = Path(__file__).resolve().parent
S = 1024                   # drawn at this size, then scaled down
C = S / 2
R_OUT = 502                # the gold ring's outer radius
TEXT = "LEIFEG"
# The ring's inner radius, the word's width, its dark rim and shadow: the large sizes', and the small ones' (up to
# SMALL px: a thinner ring and bigger, plainer letters, as readable as six letters get at that size)
LARGE = {"r_in": 458, "text_width": 760, "edge": 7, "shadow": True}
SMALL_LOOK = {"r_in": 474, "text_width": 900, "edge": 12, "shadow": False}
SMALL = 32
WEIGHT = 900               # Cinzel Black: the heaviest, to stay readable when small
LIGHT = np.array([-0.55, -0.7, 1.0]) / np.linalg.norm([-0.55, -0.7, 1.0])   # from the top left
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

rng = np.random.default_rng(7)   # seeded again for each drawing
yy, xx = np.mgrid[0:S, 0:S].astype(np.float64) + 0.5
dx, dy = xx - C, yy - C
radius, angle = np.hypot(dx, dy), np.arctan2(dy, dx)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def noise(cells: int) -> np.ndarray:
    """Smooth value noise, `cells` random values across the image, 0..1."""
    grid = Image.fromarray(rng.random((cells + 3, cells + 3)).astype(np.float32), "F")
    big = grid.resize((S * (cells + 3) // cells,) * 2, Image.BICUBIC)
    return np.asarray(big, dtype=np.float64)[S // cells: S // cells + S, S // cells: S // cells + S]


def fractal(cells=(4, 8, 16, 32, 64), falloff=0.55) -> np.ndarray:
    total, weight, w = np.zeros((S, S)), 0.0, 1.0
    for c in cells:
        total += w * noise(c)
        weight += w
        w *= falloff
    total /= weight
    return (total - total.min()) / (total.max() - total.min())


def sample(field: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear lookup of field at (x, y), wrapping around."""
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    x0, y0 = x0 % S, y0 % S
    x1, y1 = (x0 + 1) % S, (y0 + 1) % S
    top = field[y0, x0] * (1 - fx) + field[y0, x1] * fx
    bottom = field[y1, x0] * (1 - fx) + field[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def gradient_map(t: np.ndarray, stops: list[tuple[float, str]]) -> np.ndarray:
    """t (0..1) -> RGB through colour stops."""
    pos = [p for p, _ in stops]
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in stops], dtype=np.float64)
    return np.stack([np.interp(t, pos, rgb[:, k]) for k in range(3)], axis=-1)


def shading(height: np.ndarray, strength: float) -> np.ndarray:
    """Lambert light on a height map (a bevel): 0..1, 0.5-ish where flat."""
    gy, gx = np.gradient(height)
    n = np.stack([-gx * strength, -gy * strength, np.ones_like(height)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return np.clip(n @ LIGHT, 0, 1)


def blur(a: np.ndarray, r: float) -> np.ndarray:
    """Gaussian blur (sigma r) in floats: a bevel from 8-bit steps would show bands."""
    x = np.arange(-int(3 * r), int(3 * r) + 1)
    k = np.exp(-x * x / (2 * r * r))
    k /= k.sum()
    a = np.apply_along_axis(np.convolve, 1, a, k, mode="same")
    return np.apply_along_axis(np.convolve, 0, a, k, mode="same")


def grow(mask: np.ndarray, px: int) -> np.ndarray:
    img = Image.fromarray((mask * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(img, dtype=np.float64) / 255


def swirl_disc(r_in: float) -> np.ndarray:
    """The purple vortex inside the ring: smoke streaming round the middle, turning faster toward it."""
    rel = radius / r_in
    twist = angle + 4.6 * (1 - np.clip(rel, 0, 1)) ** 1.5 + 1.0 * (fractal((3, 6, 12)) - 0.5)
    # polar noise: one turn spans the noise's width a whole number of times (no seam), so the smoke
    # stretches along the circles into streaks
    u, v = twist / (2 * np.pi) * S, radius * 1.7
    smoke = sample(fractal((4, 8, 16, 32, 64, 128)), 2 * u, v)
    wisps = 1 - np.abs(2 * sample(fractal((8, 16, 32, 64)), 3 * u + 311, v * 1.25 + 97) - 1)   # thin bright ridges
    puffs = sample(fractal((4, 8, 16, 32)), C + radius * np.cos(twist), C + radius * np.sin(twist))
    t = 0.5 * smoke + 0.22 * wisps ** 2.5 + 0.33 * puffs
    t *= 0.45 + 0.55 * smoothstep(0.0, 0.6, rel)                   # a dark eye
    t *= 1 - 0.6 * smoothstep(0.82, 1.0, rel)                      # shadow under the ring
    t = np.clip((t - 0.2) / 0.6, 0, 1)
    return gradient_map(t, [(0.0, "#05010a"), (0.3, "#1c0836"), (0.55, "#3f1580"), (0.75, "#6a2cc4"),
                            (0.9, "#9b5cf0"), (1.0, "#d9c2ff")])


def gold(shade: np.ndarray, grain: np.ndarray) -> np.ndarray:
    t = np.clip(0.15 + 0.85 * shade + 0.18 * (grain - 0.5), 0, 1)
    return gradient_map(t, [(0.0, "#2a1c0c"), (0.3, "#6b5129"), (0.55, "#a88a52"), (0.75, "#d6c08c"),
                            (0.9, "#efe3c0"), (1.0, "#fffaf0")])


def ring(r_in: float) -> tuple[np.ndarray, np.ndarray]:
    """The worn gold rim, bevelled on both edges: colour and coverage."""
    band = (radius - r_in) / (R_OUT - r_in)
    coverage = smoothstep(-0.03, 0.03, band) * smoothstep(1.03, 0.97, band)
    grain = fractal((16, 32, 64, 128, 256), 0.7)
    wear = fractal((6, 12, 24, 48))
    profile = smoothstep(0.0, 0.3, band) * smoothstep(1.0, 0.7, band)   # flat top, rounded edges
    height = profile * 40 + grain * 5 - smoothstep(0.62, 0.75, wear) * 4    # dents where it's worn
    cracks = smoothstep(0.012, 0.0, np.abs(fractal((8, 16, 32)) - 0.5)) * smoothstep(0.15, 0.4, profile)
    rgb = gold(shading(height, 1.6) * 0.9 + 0.1 * profile, grain)
    rgb *= 1 - (0.35 * cracks + 0.25 * smoothstep(0.55, 0.8, wear))[..., None]   # fine cracks, darker worn patches
    return rgb, coverage


def letters(font_path: Path, text_width: float, edge: int, shadow: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The word's mask, its colour, and the dark rim and shadow around it."""
    font = ImageFont.truetype(str(font_path), 300)
    font.set_variation_by_axes([WEIGHT])
    left, top, right, bottom = font.getbbox(TEXT)
    font = ImageFont.truetype(str(font_path), round(300 * text_width / (right - left)))
    font.set_variation_by_axes([WEIGHT])
    img = Image.new("L", (S, S), 0)
    left, top, right, bottom = font.getbbox(TEXT)
    ImageDraw.Draw(img).text((C - (left + right) / 2, C - (top + bottom) / 2 - 6), TEXT, font=font, fill=255)
    mask = np.asarray(img, dtype=np.float64) / 255
    rows = np.nonzero(mask.max(axis=1) > 0.5)[0]
    up, down = rows.min(), rows.max()
    grain = fractal((32, 64, 128, 256), 0.7)
    height = blur(mask, 7) * mask * 26 + grain * 3 * mask
    shade = shading(height, 1.0)
    shade = np.clip(shade + 0.25 * (1 - (yy - up) / max(1, down - up)) - 0.1, 0, 1)   # lighter at the top
    rgb = gold(shade, grain)
    dark = grow(mask, edge)
    if shadow:
        dark = np.maximum(dark, 0.85 * np.roll(blur(grow(mask, edge + 2), 10), (12, 7), axis=(0, 1)))
    return mask, rgb, dark


def draw(font_path: Path, look: dict) -> Image.Image:
    global rng
    rng = np.random.default_rng(7)
    r_in = look["r_in"]
    disc = smoothstep(r_in + 6, r_in - 2, radius)
    rgb = swirl_disc(r_in) * disc[..., None]
    ring_rgb, ring_cov = ring(r_in)
    mask, text_rgb, dark = letters(font_path, look["text_width"], look["edge"], look["shadow"])
    rgb = rgb * (1 - dark[..., None]) + np.array([12, 6, 2]) * dark[..., None]        # dark rim + shadow
    rgb = rgb * (1 - mask[..., None]) + text_rgb * mask[..., None]
    rgb = rgb * (1 - ring_cov[..., None]) + ring_rgb * ring_cov[..., None]
    alpha = np.maximum(disc, ring_cov) * smoothstep(R_OUT + 1.5, R_OUT - 1.5, radius)
    out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--font", type=Path, help="Cinzel's variable font file (default: downloaded)")
    args = p.parse_args()
    font = args.font
    if not font:
        font = OUT.parent / ".cache" / "fonts" / "Cinzel.ttf"
        if not font.is_file():
            font.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(FONT_URL) as r:
                font.write_bytes(r.read())
    icon, small = draw(font, LARGE), draw(font, SMALL_LOOK)
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png", optimize=True)
    # each size scaled from the full drawing (sharper than from the 512 px PNG)
    sizes = [(small if n <= SMALL else icon).resize((n, n), Image.LANCZOS) for n in ICO_SIZES]
    buf = io.BytesIO()
    # bitmaps rather than PNG data: what every part of Windows reads
    sizes[-1].save(buf, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=sizes[:-1], bitmap_format="bmp")
    (OUT / "icon.ico").write_bytes(buf.getvalue())
    print(f"wrote {OUT / 'icon.png'} and {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
