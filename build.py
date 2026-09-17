"""Embed the rendered assets into the card: src/decent-de1-card.js + render/assets.json -> dist/decent-de1-card.js"""
from pathlib import Path

root = Path(__file__).parent
src = (root / "src" / "decent-de1-card.js").read_text()
assets = (root / "render" / "assets.json").read_text()
assert "__ASSETS__" in src
out = root / "dist" / "decent-de1-card.js"
out.write_text(src.replace("__ASSETS__", assets))
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
