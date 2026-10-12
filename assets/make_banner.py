"""Generates assets/banner.jpg, the gothic banner shown at the top of $help.

Needs Pillow and the Liberation Serif fonts (apt install fonts-liberation).
Run: python assets/make_banner.py
"""
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
W, H = 1200, 300
random.seed(13)

# base: deep crimson glow fading to black
base = Image.new("RGB", (W, H), (8, 5, 7))
glow = Image.new("L", (W, H), 0)
gd = ImageDraw.Draw(glow)
gd.ellipse((W*0.18, -H*0.6, W*0.82, H*1.35), fill=255)
glow = glow.filter(ImageFilter.GaussianBlur(110))
red = Image.new("RGB", (W, H), (98, 8, 14))
base = Image.composite(red, base, glow.point(lambda v: int(v*0.85)))

# fog
fog = Image.new("L", (W, H), 0); fd = ImageDraw.Draw(fog)
for _ in range(60):
    x, y = random.randint(-100, W), random.randint(int(H*0.5), H+40)
    r = random.randint(60, 180)
    fd.ellipse((x-r, y-r//3, x+r, y+r//3), fill=random.randint(20, 60))
fog = fog.filter(ImageFilter.GaussianBlur(30))
base = Image.composite(Image.new("RGB", (W, H), (60, 52, 58)), base, fog)

# gothic arches silhouette along the bottom
sil = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(sil)
def spire(cx, w, h):
    sd.polygon([(cx-w, H), (cx-w, H-h), (cx, H-h-w*1.6), (cx+w, H-h), (cx+w, H)], fill=255)
for cx, w, h in [(70, 26, 70), (140, 14, 120), (190, 30, 55), (1010, 30, 60), (1065, 15, 130), (1130, 26, 80), (1185, 12, 40)]:
    spire(cx, w, h)
sd.rectangle((0, H-28, W, H), fill=255)
for i in range(0, W, 46):
    sd.rectangle((i, H-40, i+24, H), fill=255)
base = Image.composite(Image.new("RGB", (W, H), (4, 2, 3)), base, sil)

# bats
def bat(d, x, y, s):
    pts = [(-1,0),(-0.6,-0.25),(-0.45,0.05),(-0.25,-0.1),(-0.12,0.08),(0,-0.06),(0.12,0.08),(0.25,-0.1),(0.45,0.05),(0.6,-0.25),(1,0),(0.5,0.2),(0.2,0.3),(0,0.18),(-0.2,0.3),(-0.5,0.2)]
    d.polygon([(x+px*s, y+py*s) for px, py in pts], fill=(6, 3, 4))
bd = ImageDraw.Draw(base)
for x, y, s in [(250, 60, 26), (300, 92, 16), (905, 70, 22), (950, 46, 14), (870, 110, 12), (330, 50, 10)]:
    bat(bd, x, y, s)

# grain
noise = Image.effect_noise((W, H), 22).convert("RGB")
base = ImageChops.add(base, noise.point(lambda v: v//10), scale=1.0, offset=-10)

# vignette
vig = Image.new("L", (W, H), 0); vd = ImageDraw.Draw(vig)
vd.rectangle((0, 0, W, H), fill=255); vd.ellipse((-W*0.1, -H*0.5, W*1.1, H*1.5), fill=0)
vig = vig.filter(ImageFilter.GaussianBlur(80))
base = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), base, vig.point(lambda v: int(v*0.8)))

# title
d = ImageDraw.Draw(base)
title_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", 104)
sub_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", 22)
def spaced(text, font, spacing):
    widths = [d.textlength(c, font=font) for c in text]
    return widths, sum(widths) + spacing*(len(text)-1)
def draw_spaced(text, font, spacing, y, fill, shadow=None):
    widths, total = spaced(text, font, spacing)
    x = (W - total)/2
    for c, w in zip(text, widths):
        if shadow: shadow.text((x, y), c, font=font, fill=255)
        d.text((x, y), c, font=font, fill=fill); x += w + spacing
# glow behind title
sh = Image.new("L", (W, H), 0); shd = ImageDraw.Draw(sh)
widths, total = spaced("DRACULA", title_font, 18)
x = (W-total)/2
for c, w in zip("DRACULA", widths):
    shd.text((x, 72), c, font=title_font, fill=255); x += w + 18
sh = sh.filter(ImageFilter.GaussianBlur(14))
base = Image.composite(Image.new("RGB", (W, H), (150, 10, 20)), base, sh.point(lambda v: int(v*0.75)))
d = ImageDraw.Draw(base)
draw_spaced("DRACULA", title_font, 18, 72, (236, 226, 222))
# ornament lines + subtitle
cy = 206
_, sub_w = spaced("THE NIGHT IS ETERNAL", sub_font, 5)
gap = sub_w/2 + 26
red_line = (138, 3, 3)
for sign in (-1, 1):
    d.line((W/2 + sign*gap, cy, W/2 + sign*(gap+110), cy), fill=red_line, width=2)
    tip = W/2 + sign*(gap - 10)
    d.polygon([(tip - 6, cy), (tip, cy - 6), (tip + 6, cy), (tip, cy + 6)], fill=red_line)
draw_spaced("THE NIGHT IS ETERNAL", sub_font, 5, cy - 13, (196, 160, 160))
import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.jpg")
base.save(out, quality=90, optimize=True)
print("ok")
