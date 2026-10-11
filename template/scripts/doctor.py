"""Environment health check: Run on first use, after switching machines, or when scripts encounter strange errors. Inspection only; installs nothing.

python3 <tool_dir>/template/scripts/doctor.py   Run at workspace root (before project is initialized)
python3 scripts/doctor.py                      Run under <output_dir>/<project>/build/ (also checks node_modules)

MISSING indicates required items without which videos cannot be made; WARN indicates optional items affecting specific features only.
"""
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
MAC, WIN = platform.system() == "Darwin", platform.system() == "Windows"
rows = []


def report(level, name, detail, fix=""):
    rows.append(level)
    pad = 18 - sum(2 if ord(c) > 0x2E80 else 1 for c in name)
    print(f"{level:8s}{name}{' ' * pad}{detail}" + (f"\n{'':26s}-> {fix}" if fix else ""))


def install_hint(mac, win, linux):
    return mac if MAC else win if WIN else linux


def version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return ""


v = version(["node", "-v"])
major = int(re.sub(r"\D", "", v.split(".")[0]) or 0) if v else 0
if major >= 18:
    report("OK", "Node.js", v)
else:
    report("MISSING", "Node.js", v or "Not installed", "Install Node.js 18+: https://nodejs.org")

for tool in ("ffmpeg", "ffprobe"):
    if shutil.which(tool):
        report("OK", tool, version([tool, "-version"])[:60])
    else:
        report("MISSING", tool, "Not installed", install_hint("brew install ffmpeg", "winget install ffmpeg", "sudo apt install ffmpeg"))

if sys.version_info >= (3, 9):
    report("OK", "Python", platform.python_version())
else:
    report("MISSING", "Python", platform.python_version(), "Requires Python 3.9+")

missing = [m for m, mod in [("numpy", "numpy"), ("scipy", "scipy"), ("Pillow", "PIL"), ("fonttools", "fontTools"), ("brotli", "brotli")] if not importlib.util.find_spec(mod)]
if missing:
    report("MISSING", "Python deps", "Missing " + " ".join(missing), f"pip install -r {os.path.relpath(os.path.join(ROOT, 'requirements.txt'))}")
else:
    report("OK", "Python deps", "numpy scipy Pillow fonttools brotli")

if importlib.util.find_spec("playwright"):
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
        if os.path.exists(exe):
            report("OK", "Playwright", "Available for 4K web screenshots (scripts/shot.py)")
        else:
            report("WARN", "Playwright", "Browser binary not installed", "playwright install chromium")
    except Exception as e:  # noqa: BLE001
        report("WARN", "Playwright", f"Launch failed: {e}"[:80], "playwright install chromium")
else:
    report("WARN", "Playwright", "Not installed; cannot use shot.py / snapshot.py for screenshots", "pip install playwright && playwright install chromium")

if os.path.isdir(os.path.join(ROOT, "node_modules")):
    report("OK", "npm deps", "Installed")
elif os.path.basename(ROOT) == "template":
    report("OK", "npm deps", "Run npm install in build/ after initializing project (do not install in template)")
else:
    report("MISSING", "npm deps", "Not installed", "npm install")

try:
    from fonts import resolve

    cfg = json.load(open(os.path.join(ROOT, "fonts.json"), encoding="utf-8"))
    bad = [f["file"] for f in cfg["fonts"] if not resolve(f["source"])]
    if bad:
        report("MISSING", "CJK Fonts", f"Cannot find {', '.join(bad)}", "Place font file into fonts-src/ and edit fonts.json; on Linux: sudo apt install fonts-noto-cjk")
    else:
        report("OK", "CJK Fonts", ", ".join(os.path.basename(resolve(f["source"])[0]) for f in cfg["fonts"]))
except Exception as e:  # noqa: BLE001
    report("WARN", "CJK Fonts", f"Check failed: {e}"[:80])

from elevenlabs import env_files  # noqa: E402

env = os.environ.get("ELEVENLABS_API_KEY") and "Environment variable"
for f in env_files():
    if not env and os.path.exists(f) and "ELEVENLABS_API_KEY=" in open(f, encoding="utf-8").read():
        env = f
if env:
    report("OK", "ElevenLabs", f"Key configured ({env}); check quota with python3 scripts/elevenlabs.py quota")
else:
    report("WARN", "ElevenLabs", "Not configured: cannot generate voiceover or custom score, falls back to stock music + subtitles", "If needed, set ELEVENLABS_API_KEY=... in .env at workspace root or as environment variable")

print()
if "MISSING" in rows:
    print(f"{rows.count('MISSING')} required environment item(s) missing. Please install them and rerun.")
    sys.exit(1)
print("All required environment items are ready." + ("" if MAC else " This tool was primarily developed on macOS; for issues on other OS, see references/pitfalls.md."))
