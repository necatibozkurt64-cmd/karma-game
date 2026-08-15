#!/usr/bin/env python3
"""Erzeugt quadratische Profilbilder aus den Kartenmotiven.

Das Kartenbild ist ein breiter Streifen, das Profilbild ein Kreis - derselbe
Ausschnitt passt nicht fuer beides. Hier wird deshalb ein Quadrat um den
Gesichtsmittelpunkt geschnitten (dieselben Prozentwerte wie CARD_IMAGE_FOCUS
im Client) und auf 160x160 WebP verkleinert.
"""
from pathlib import Path
from PIL import Image

SRC = Path(__file__).resolve().parent.parent / 'app' / 'public' / 'Bilder'
OUT = SRC / 'avatare'
SIZE = 160

# id -> (Datei, Fokus x%, Fokus y%, Zoom)
# Fokus = Gesichtsmittelpunkt, Zoom = Anteil der kurzen Kante, der ins Quadrat
# geht. Der Zoom muss pro Bild stehen: bei Motiven, auf denen die Figur klein im
# Bild sitzt (Trump, Mr Hankey, Olli), fuellt die volle kurze Kante den Kreis mit
# Hintergrund statt mit Gesicht.
FIGURES = {
    # aktuelle Karten - Fokus meist aus CARD_IMAGE_FOCUS, fuer den Kreis nachgezogen
    'card-1':  ('fotos/01-willy.webp',      0.27, 0.20, 0.62),
    'card-2':  ('fotos/02-fabrice.webp',    0.48, 0.30, 0.86),
    'card-3':  ('fotos/03-tom.webp',        0.36, 0.40, 0.86),
    'card-4':  ('fotos/04-ugur.webp',       0.55, 0.30, 0.86),
    'card-5':  ('fotos/05-barbie.webp',     0.50, 0.74, 0.86),
    'card-6':  ('fotos/06-carlin.webp',     0.65, 0.30, 0.86),
    'card-7':  ('07_Ronaldo.jpeg',          0.55, 0.33, 0.90),
    'card-8':  ('08_Leonardo DiCaprio.jpg', 0.56, 0.17, 0.86),
    'card-9':  ('fotos/09-penny.webp',      0.50, 0.30, 0.86),
    'card-10': ('fotos/10-merkel.webp',     0.50, 0.42, 0.86),
    'card-11': ('11_joker.jpg',             0.47, 0.40, 0.86),
    'card-12': ('12_Hund.jpg',              0.50, 0.30, 0.86),
    'card-13': ('fotos/13-murat-abi.webp',  0.33, 0.40, 0.86),
    'card-14': ('14_Thierry Henry.jpeg',    0.45, 0.42, 0.86),
    'card-15': ('15_Katze.jpg',             0.52, 0.28, 0.86),
    # Legacy - Figuren, die frueher auf den Karten standen. Sie liegen in
    # app/public/Bilder/legacy/ und sind nur noch Quelle fuer diese Avatare.
    'legacy-olli':     ('legacy/01_Olli.png',                  0.39, 0.20, 0.37),
    'legacy-tupac':    ('legacy/02_tupac.jpg',                 0.50, 0.30, 0.86),
    'legacy-arnold':   ('legacy/03_arnold schwarzenegger.jpg', 0.50, 0.25, 0.86),
    'legacy-cartman':  ('legacy/04_Eric Cartman.png',          0.50, 0.30, 0.86),
    'legacy-zidane':   ('legacy/05_zidane.jpg',                0.55, 0.22, 0.80),
    'legacy-brucelee': ('legacy/06_bruce lee.jpg',             0.50, 0.30, 0.86),
    'legacy-hawktuah': ('fotos/06-hawk-tuah.webp',      0.50, 0.30, 0.86),
    'legacy-snowden':  ('legacy/09_snowden.jpg',               0.50, 0.30, 0.86),
    'legacy-trump':    ('legacy/10_trump.jpg',                 0.42, 0.35, 0.40),
    'legacy-hankey':   ('legacy/13_MrHankey.jpg',              0.50, 0.38, 0.62),
}


def crop_square(im, fx, fy, zoom):
    w, h = im.size
    side = int(min(w, h) * zoom)
    cx, cy = w * fx, h * fy
    left = int(max(0, min(cx - side / 2, w - side)))
    top = int(max(0, min(cy - side / 2, h - side)))
    return im.crop((left, top, left + side, top + side))


def main():
    OUT.mkdir(exist_ok=True)
    for key, (rel, fx, fy, zoom) in sorted(FIGURES.items()):
        src = SRC / rel
        if not src.exists():
            print(f'FEHLT: {rel}')
            continue
        im = Image.open(src).convert('RGB')
        sq = crop_square(im, fx, fy, zoom).resize((SIZE, SIZE), Image.LANCZOS)
        dst = OUT / f'{key}.webp'
        sq.save(dst, 'WEBP', quality=88, method=6)
        print(f'{key:18} {rel:34} {im.size} -> {dst.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main()
