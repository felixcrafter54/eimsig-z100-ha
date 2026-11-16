#!/usr/bin/env python3
"""Erzeugt icon.png und logo.png des Add-ons (Pillow). Aufruf: python3 tools/grafiken.py"""
import os
from PIL import Image, ImageDraw, ImageFont

ZIEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eimsig2mqtt")
BLAU, BLAU2, WEISS, GELB = (3, 105, 161), (14, 165, 233), (255, 255, 255), (250, 204, 21)
S = 4  # Supersampling für glatte Kanten


def symbol(groesse):
    n = groesse * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Hintergrund: abgerundetes Quadrat mit leichtem Verlauf
    for y in range(n):
        f = y / n
        c = tuple(int(BLAU2[i] * (1 - f) + BLAU[i] * f) for i in range(3))
        d.line([(0, y), (n, y)], fill=c)
    maske = Image.new("L", (n, n), 0)
    ImageDraw.Draw(maske).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22), fill=255)
    im.putalpha(maske)
    d = ImageDraw.Draw(im)
    # Fenster (gekippt angedeutet: rechter Flügel offen)
    w = int(n * 0.06)
    x0, y0, x1, y1 = int(n * 0.20), int(n * 0.30), int(n * 0.66), int(n * 0.82)
    d.rounded_rectangle([x0, y0, x1, y1], radius=int(n * 0.03), outline=WEISS, width=w)
    xm, ym = (x0 + x1) // 2, (y0 + y1) // 2
    d.line([(xm, y0), (xm, y1)], fill=WEISS, width=w)
    d.line([(x0, ym), (x1, ym)], fill=WEISS, width=w)
    # Funkwellen oben rechts
    cx, cy = int(n * 0.70), int(n * 0.30)
    for k, r in enumerate((0.10, 0.18, 0.26)):
        rr = int(n * r)
        d.arc([cx - rr, cy - rr, cx + rr, cy + rr], start=-75, end=-15, fill=GELB, width=int(n * 0.045))
    d.ellipse([cx - int(n * 0.035), cy - int(n * 0.035), cx + int(n * 0.035), cy + int(n * 0.035)], fill=GELB)
    return im.resize((groesse, groesse), Image.LANCZOS)


def icon():
    symbol(256).save(os.path.join(ZIEL, "icon.png"))


def logo():
    b, h = 500, 200
    im = Image.new("RGBA", (b, h), (0, 0, 0, 0))
    im.alpha_composite(symbol(170), (10, 15))
    d = ImageDraw.Draw(im)
    fett = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
    normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    d.text((200, 42), "EiMSIG", font=fett, fill=(2, 132, 199))
    d.text((202, 110), "Alarmanlage → HA", font=normal, fill=(100, 116, 139))
    im.save(os.path.join(ZIEL, "logo.png"))


if __name__ == "__main__":
    icon()
    logo()
    print("icon.png und logo.png erzeugt")
