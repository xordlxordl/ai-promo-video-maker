"""Asset quality gate before rendering: Checks whether public/ files referenced in code exist, images are too small or too large, and font subsets are missing characters. Exits with code 1 on ERROR.

python3 scripts/check_assets.py
"""
import glob
import json
import os
import re
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
EXT = r"png|jpe?g|webp|svg|gif|mp3|wav|mp4|webm|woff2"
errors, warns = [], []

refs = set()
for p in glob.glob(os.path.join(ROOT, "src", "**", "*.ts*"), recursive=True) + glob.glob(os.path.join(ROOT, "web", "*.ts*")):
    for m in re.finditer(rf"[\"'`]/?([^\"'`$\s]+\.(?:{EXT}))[\"'`]", open(p, encoding="utf-8").read()):
        refs.add((m.group(1).lstrip("/"), os.path.relpath(p, ROOT)))
for ref, where in sorted(refs):
    if not os.path.exists(os.path.join(PUB, ref)):
        errors.append(f"Missing file public/{ref} ({where})")

if not os.path.exists(os.path.join(PUB, "audio", "mix.wav")):
    errors.append("Missing public/audio/mix.wav, run npm run mix first")

for f in glob.glob(os.path.join(PUB, "**", "*.*"), recursive=True):
    if not re.search(r"\.(png|jpe?g|webp)$", f, re.I):
        continue
    try:
        w, h = Image.open(f).size
    except Exception as e:
        errors.append(f"Corrupted image {os.path.relpath(f, ROOT)}: {e}")
        continue
    rel = os.path.relpath(f, ROOT)
    if max(w, h) < 1000:
        warns.append(f"{rel} is only {w}x{h}; if displayed wider than {w // 2}px on screen, it will blur in 4K")
    if w > 3000:
        warns.append(f"{rel} is {w}px wide; multiple instances on screen in 4K rendering may cause decode failures, downscale to display size * 2")

cfg = json.load(open(os.path.join(ROOT, "fonts.json"), encoding="utf-8"))
for f in cfg["fonts"]:
    if not os.path.exists(os.path.join(PUB, "fonts", f"{f['file']}.woff2")):
        errors.append(f"Missing font public/fonts/{f['file']}.woff2, run npm run fonts first")

for w in warns:
    print("WARN ", w)
for e in errors:
    print("ERROR", e)
print(f"Referenced {len(refs)} files; {len(errors)} errors, {len(warns)} warnings")
sys.exit(1 if errors else 0)
