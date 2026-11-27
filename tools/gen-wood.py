"""Chapter plates for the book: procedural wood, dithered to the same 1-bit alpha masks as the old paintings.
Needs numpy and pillow (not a Plank dependency, run it by hand): `python3 tools/gen-wood.py` rewrites site/art/wood-*.png."""
import numpy as np
from PIL import Image

W, H = 1200, 800
Y, X = np.mgrid[0:H, 0:W].astype(float)


def noise(scale, seed):
    r = np.random.default_rng(seed).random((H // scale + 3, W // scale + 3))
    return np.asarray(Image.fromarray((r * 255).astype("uint8")).resize((W + 3 * scale, H + 3 * scale), Image.BICUBIC), float)[:H, :W] / 255


def rings(d, freq):
    return 0.5 + 0.5 * np.sin(d * freq)


def planks(seed=1):
    out, n = np.zeros((H, W)), 5
    for i in range(n):
        y0, y1 = i * H // n, (i + 1) * H // n
        warp = noise(300, seed + i) * 60 + noise(80, seed + 9 + i) * 8
        g = rings(Y + warp + i * 97, 0.3) * 0.8 + noise(3, seed + 20 + i) * 0.2
        kx, ky = np.random.default_rng(seed + i).integers(150, W - 150), (y0 + y1) // 2
        d = np.hypot((X - kx) / 2.2, Y - ky)
        g = np.where(d < 60, rings(d, 0.5) * 0.9 + 0.1 * g, g * (0.75 + 0.25 * np.clip(d / 140, 0, 1)))
        g[y0:y0 + 3] = 1  # the seam between boards
        out[y0:y1] = g[y0:y1] * (0.8 + 0.2 * (i % 2))
    return out


def endgrain(seed=2):
    d = np.hypot(X - W * 0.5 + noise(120, seed) * 60 - 30, (Y - H * 0.52) * 1.05 + noise(120, seed + 1) * 60 - 30)
    g = rings(d, 0.22) * 0.8 + noise(5, seed + 2) * 0.2
    crack = (np.abs(np.arctan2(Y - H * 0.52, X - W * 0.5) - 0.5) < 0.012) & (d < 330)
    g[crack] = 1
    return np.where(d < 340, g, 1 - 0.0 * g + 0.0) * np.where(d < 340, 1, 1) + np.where(d >= 340, 1.0 - np.clip((d - 340) / 40, 0, 1) * 0 - 0, 0) * 0


def cathedral(seed=3):
    c = np.abs(X - W / 2)
    d = Y * 0.9 + (c ** 2) * 0.0016 + noise(150, seed) * 40
    return rings(d, 0.16) * 0.8 + noise(5, seed + 1) * 0.2


def burl(seed=4):
    a = noise(160, seed) * 9 + noise(60, seed + 1) * 3 + noise(20, seed + 2)
    return rings(a, 6.5) * 0.85 + noise(4, seed + 3) * 0.15


def logs(seed=5):
    out = np.ones((H, W)) * 0.95
    for cx, cy, r in [(300, 250, 230), (780, 230, 200), (1050, 440, 150), (500, 640, 220), (930, 680, 130), (100, 640, 150)]:
        d = np.hypot(X - cx + noise(80, seed + cx) * 20, Y - cy + noise(80, seed + cy) * 20)
        g = rings(d, 0.3) * 0.8 + noise(5, seed) * 0.2
        bark = np.clip((d - r + 14) / 14, 0, 1)
        g = g * (1 - bark) + 0.1 * bark
        out = np.where(d < r, g, out)
    return out


def hatch(seed=6):
    """flat-sawn board, long straight grain, a little like a woodcut block"""
    g = rings(Y * 0.9 + noise(200, seed) * 160 + noise(30, seed + 1) * 12, 0.5)
    return g * 0.6 + noise(3, seed + 2) * 0.1 + noise(300, seed + 3) * 0.3


def dither(g, name):
    g = np.clip((g - g.min()) / (g.max() - g.min()), 0, 1)
    ink = Image.fromarray(((1 - g) * 255).astype("uint8")).convert("1")  # Floyd-Steinberg, dark wood = ink
    a = np.asarray(ink).astype("uint8") * 255
    Image.merge("LA", (Image.new("L", (W, H), 255), Image.fromarray(a))).save(f"site/art/wood-{name}.png", optimize=True)


for f in (planks, endgrain, cathedral, burl, logs, hatch):
    dither(f(), f.__name__)
