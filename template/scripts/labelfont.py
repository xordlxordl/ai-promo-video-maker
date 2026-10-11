"""Chinese font for labeling contact sheets and sampled frames: Searches common macOS / Windows / Linux paths in order, falling back to Pillow's default font if not found (non-ASCII characters will display as boxes)."""
import glob

from PIL import ImageFont

CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/**/NotoSans-Regular.ttc",
    "/usr/share/fonts/**/wqy-microhei.ttc",
]


def label_font(size):
    for pattern in CANDIDATES:
        for path in glob.glob(pattern, recursive=True):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()
