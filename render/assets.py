"""Crop the Cycles renders in render/final/ into card assets (render/assets.json).

base: machine with an empty tank. levels: only the pixels that differ from the
base, so overlays never double-darken the soft shadow or show seams.
"""
from PIL import Image, ImageChops, ImageFilter, ImageDraw
import json, io, base64, os

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "final"))
L = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
ims = {l: Image.open(f"level_{l:03d}.png").convert("RGBA") for l in L}
W, H = ims[0].size
an = json.load(open("anchors.png.json"))

# crop around the opaque machine with room for the shadow to fade
bx0, by0, bx1, by1 = ims[0].split()[3].point(lambda v: 255 if v > 200 else 0).getbbox()
mx, mt, mb = int(0.13 * (bx1 - bx0)), int(0.07 * (by1 - by0)), int(0.12 * (by1 - by0))
x0, y0, x1, y1 = max(0, bx0 - mx), max(0, by0 - mt), min(W, bx1 + mx), min(H, by1 + mb)
TW = 900
scale = TW / (x1 - x0)
TH = round((y1 - y0) * scale)


def prep(im):
    return im.crop((x0, y0, x1, y1)).resize((TW, TH), Image.LANCZOS)


fade = Image.new("L", (TW, TH), 0)
pad = int(0.06 * TW)
ImageDraw.Draw(fade).rectangle((pad, pad, TW - pad, TH - pad), fill=255)
fade = fade.filter(ImageFilter.GaussianBlur(pad / 2))


def faded(im):
    r, g, b, a = im.split()
    return Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, fade)))


def enc(im, q=85):
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=q, method=6, exact=True)
    return base64.b64encode(buf.getvalue()).decode()


def to_card(pt):
    return [round(((pt[0] * W - x0) * scale) / TW, 5), round(((pt[1] * H - y0) * scale) / TH, 5)]


def diff_layer(img, ref, box, opaque_only):
    c, r0 = img.crop(box), ref.crop(box)
    mask = ImageChops.difference(c, r0).convert("L").point(lambda v: 255 if v > 6 else 0)
    mask = mask.filter(ImageFilter.MaxFilter(5 if opaque_only else 3)).filter(ImageFilter.GaussianBlur(1.5 if opaque_only else 1))
    if opaque_only:
        opaque = r0.split()[3].point(lambda v: 255 if v >= 250 else 0).filter(ImageFilter.MinFilter(3))
        mask = ImageChops.multiply(mask, opaque)
    r, g, b, _ = c.split()
    return enc(Image.merge("RGBA", (r, g, b, mask)))


base = faded(prep(ims[0]))
out = {"w": TW, "h": TH, "base": enc(base), "levels": {}}

# water: the tank's projected bounding box
tp = [((p[0] * W - x0) * scale, (p[1] * H - y0) * scale) for p in an["tank_box"]]
m = 14
wbox = (int(max(0, min(p[0] for p in tp) - m)), int(max(0, min(p[1] for p in tp) - m)),
        int(min(TW, max(p[0] for p in tp) + m)), int(min(TH, max(p[1] for p in tp) + m)))
out["water_box"] = [wbox[0] / TW, wbox[1] / TH, (wbox[2] - wbox[0]) / TW, (wbox[3] - wbox[1]) / TH]
for l in L:
    out["levels"][l] = diff_layer(faded(prep(ims[l])), base, wbox, True)

out["screen"] = {k: to_card(v) for k, v in an["screen"].items()}
out["tank"] = to_card(an["tank_front_left"])
json.dump(out, open("../assets.json", "w"))
print("size", TW, TH, "total kb", len(json.dumps(out)) // 1024,
      "water kb", sum(len(v) for v in out["levels"].values()) * 3 // 4 // 1024)
