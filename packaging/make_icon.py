"""Genera l'icona di Arloc: tessere di mosaico su un quadrato arrotondato.

Uso: uv run python packaging/make_icon.py
Produce packaging/arloc.png (1024), packaging/arloc.ico (multi-size) e arloc/ui/resources/arloc.png (256).
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024
BG = (31, 122, 109)  # colore d'accento dell'app (#1F7A6D)
TONES = [(244, 238, 226), (232, 222, 203), (217, 160, 102), (196, 112, 84), (120, 176, 160), (250, 246, 238)]


def make() -> Image.Image:
    rnd = random.Random(7)  # deterministico
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=220, fill=BG)
    n, margin, gap = 5, 170, 22
    cell = (S - 2 * margin - (n - 1) * gap) / n
    for r in range(n):
        for c in range(n):
            x0 = margin + c * (cell + gap) + rnd.uniform(-6, 6)
            y0 = margin + r * (cell + gap) + rnd.uniform(-6, 6)
            # diagonale "decorata" come in un mosaico, resto chiaro
            tone = TONES[2 + (r + c) % 3] if abs(r - c) <= 0 or r + c == n - 1 else TONES[rnd.choice([0, 1, 5])]
            d.rounded_rectangle((x0, y0, x0 + cell, y0 + cell), radius=18, fill=tone)
    return img


def main():
    img = make()
    (ROOT / "arloc" / "ui" / "resources").mkdir(parents=True, exist_ok=True)
    img.save(ROOT / "packaging" / "arloc.png")
    img.resize((256, 256), Image.LANCZOS).save(ROOT / "arloc" / "ui" / "resources" / "arloc.png")
    img.save(ROOT / "packaging" / "arloc.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icone generate")


if __name__ == "__main__":
    main()
