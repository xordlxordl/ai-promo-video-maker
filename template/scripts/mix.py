"""本项目的 cue sheet：按 src/timing.json 把 audio-src/ 的素材混成 public/audio/mix.wav。每个项目按分镜重写。

python3 scripts/mix.py            生成混音
python3 scripts/mix.py --env      生成后打印响度曲线
python3 scripts/mix.py --no-vo    不放旁白、音乐不压低，写到 out/mix-music.wav（换进成片就是「纯音乐版」）
"""
import os
import sys

from audiolib import ROOT, SR, Mix, build_in, duck_curve, load, room_tone, seg, splice, src, sub_boom, timing, voice_lines

TM = timing()
DUR = TM["duration"]
BEAT = TM["beat"]
SC = {k: v[0] for k, v in TM["scenes"].items()}
mix = Mix(DUR)

# ---------- 旁白：timing.json 的 voice.lines 由 `elevenlabs.py vo` 生成到 audio-src/vo/；说话时音乐压低 duckDb ----------
VC = TM.get("voice") or {}
NO_VO = "--no-vo" in sys.argv
VO = voice_lines(TM, VC.get("rmsDb", -13)) if VC.get("lines") and not NO_VO else []
duck = duck_curve([(ln["at"], ln["at"] + len(c) / SR, ln.get("duckDb", VC.get("duckDb", -9))) for ln, c in VO], DUR + 4) if VO else None
for ln, clip in VO:
    mix.place(clip, ln["at"], gain=VC.get("gain", 1.0), fade_out=0.03, tag="voice")

# ---------- 音乐 ----------
if os.path.exists(src("music.mp3")):
    music = load("music.mp3")
    off = TM["musicOffset"]
    if TM.get("music"):
        # 作曲自带开场情绪段：从第 0 秒起按拼接表用（需要静场时再加 muffle(body, a, b)）
        body = splice(music, TM["music"], off, DUR)
        mix.place(body, 0.0, fade_in=0.15, fade_out=1.2, duck=duck, tag="music")
    else:
        music_in = max(0.0, TM["drop"] - 4 * BEAT)
        body = seg(music, off + music_in, off + DUR)
        body = build_in(body, TM["drop"] - music_in)
        mix.place(body, music_in, fade_in=0.3, fade_out=1.5, duck=duck, tag="music")
else:
    print("audio-src/music.mp3 不存在，只输出音效层")

# ---------- 音效 ----------
mix.place(room_tone(max(1.0, TM["drop"])), 0.0, fade_in=1.0, fade_out=1.0)
mix.place(sub_boom(), TM["drop"], gain=0.9)
for name, start in SC.items():
    if start > 0:
        mix.place(sub_boom(0.6, 90, 45, 8), start, gain=0.3)

mix.vo_margin()
if NO_VO:
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
mix.master(os.path.join(ROOT, "out", "mix-music.wav") if NO_VO else None)

if "--env" in sys.argv:
    from audiolib import envelope

    envelope()
