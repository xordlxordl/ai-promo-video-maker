"""ElevenLabs audio generation (voiceover / SFX / chunked music score / quota).
API key search order: environment variable ELEVENLABS_API_KEY -> project .env -> traverse parent dirs for .env -> current dir upwards for .env
(Set once at the workspace root, shared across all projects).

python3 scripts/elevenlabs.py quota
python3 scripts/elevenlabs.py voices --zh                       # Account voices + Chinese voices from voice library
python3 scripts/elevenlabs.py vo                                # Generate all voiceovers from timing.json voice table + STT verification
python3 scripts/elevenlabs.py vo --voice <voice_id> --out /tmp/vo-audition   # Test alternate voice without touching production voiceover
python3 scripts/elevenlabs.py vo --model eleven_flash_v2_5 --out /tmp/vo-flash --only hook,cta   # Compare models
python3 scripts/elevenlabs.py vo --takes 4                      # Generate up to 4 takes per line, keeping the most accurate transcription
python3 scripts/elevenlabs.py stt some.mp3                      # Transcribe arbitrary audio (Scribe)
python3 scripts/elevenlabs.py check-mix                         # Transcribe final mix, comparing line-by-line against script (must run after mix)
python3 scripts/elevenlabs.py sfx whoosh "Fast clean airy swoosh" --dur 0.8 --influence 0.6
python3 scripts/elevenlabs.py music score plan.json             # Requires paid tier; plan.json is {"chunks": [...]}

SFX and compositions write to audio-src/el/<name>.mp3, appending prompts to audio-src/el/prompts.tsv (for tracking citations in research notes).
Voiceovers write to audio-src/vo/<line_id>.mp3, with validation results in audio-src/vo/report.json; lines with unchanged text, voice, and model will not regenerate.
Optional voice fields in timing.json:
  "keywords": ["Product", "example"]   Keywords like brand names/URLs that must be heard verbatim; missing in transcript triggers CHECK_WORD
  "sts": true                          After TTS, applies Speech-to-Speech to restore voiceId timbre (used when cloned voice has accurate pronunciation on eleven_v3 but timbre drifts)
Also measures reverb tail per line (decay time from peak -20 dB to -45 dB); tails > 250 ms trigger ECHO (sounds like echo under music).
Free tier: SFX and voiceover work, music endpoint returns 402; supports 1~2 concurrent requests; script automatically retries on 429.
Content generated under Free tier excludes commercial license; remember to notify the user upon delivery.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "audio-src", "el")
VO = os.path.join(ROOT, "audio-src", "vo")
API = "https://api.elevenlabs.io"
MAX_TEMPO = 1.12
MAX_TAIL_MS = 250
STS_MODEL = "eleven_multilingual_sts_v2"


def env_files():
    seen = set()
    for d in (ROOT, os.getcwd()):
        for _ in range(5):
            if d not in seen:
                seen.add(d)
                yield os.path.join(d, ".env")
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent


def key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    for env in env_files():
        if k:
            break
        if os.path.exists(env):
            for line in open(env, encoding="utf-8"):
                if line.strip().startswith("ELEVENLABS_API_KEY="):
                    k = line.split("=", 1)[1].strip().strip("'\"")
    if not k:
        sys.exit("Missing ELEVENLABS_API_KEY: Please set ELEVENLABS_API_KEY=... in .env at workspace root or build directory, or as an environment variable (do not paste into chat)")
    return k


def call(path, body=None, retries=4, files=None):
    if files is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (body or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for name, path_ in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{os.path.basename(path_)}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
            parts.append(open(path_, "rb").read() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        data, ctype = b"".join(parts), f"multipart/form-data; boundary={boundary}"
    else:
        data = json.dumps(body).encode() if body is not None else None
        ctype = "application/json"
    for attempt in range(retries):
        req = urllib.request.Request(API + path, data=data, method="POST" if data else "GET")
        req.add_header("xi-api-key", key())
        if data:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:300]
            if e.code == 429 and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            sys.exit(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            # Connection reset can occur with api.elevenlabs.io; wait and retry, prompt to check proxy on failure
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            sys.exit(f"Network error {e}: check proxy (export HTTPS_PROXY=http://127.0.0.1:<port>; on macOS run scutil --proxy to check port)")


def save(name, audio, prompt, params):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{name}.mp3")
    open(path, "wb").write(audio)
    with open(os.path.join(OUT, "prompts.tsv"), "a", encoding="utf-8") as f:
        f.write(f"{name}\t{prompt}\t{json.dumps(params, ensure_ascii=False)}\n")
    print(path)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def trim(src, dst, tempo=1.0):
    """Cut leading/trailing silence (and optionally speed up) so `at` in timing.json is where the first syllable lands."""
    rm = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02"
    chain = f"{rm},areverse,{rm},areverse"
    if tempo != 1.0:
        chain += f",atempo={tempo:.4f}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", chain, "-ar", "48000", "-b:a", "256k", dst], check=True)


def tail_ms(path):
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    w = 480
    if len(x) < w * 4:
        return 0
    frames = x[: len(x) // w * w].reshape(-1, w)
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    pk = db.max()
    return int((np.where(db > pk - 45)[0][-1] - np.where(db > pk - 20)[0][-1]) * 10)


def to_voice(src_, dst, voice, settings):
    body = {"model_id": STS_MODEL, "voice_settings": json.dumps(settings), "remove_background_noise": "true"}
    open(dst, "wb").write(call(f"/v1/speech-to-speech/{voice}?output_format=mp3_44100_192", body, files={"audio": src_}))


def missing_words(keywords, said, heard):
    return [k for k in keywords if norm(heard).count(norm(k)) < norm(said).count(norm(k))]


def transcribe(path, lang=None):
    body = {"model_id": "scribe_v1"}
    if lang:
        body["language_code"] = lang
    return json.loads(call("/v1/speech-to-text", body, files={"file": path})).get("text", "")


def zh_num(m):
    n, digits, units = int(m.group()), "零一二三四五六七八九", ["", "十", "百", "千"]
    if n == 0 or n >= 10000:
        return m.group()
    out, s = "", str(n)
    for i, ch in enumerate(s):
        d, u = int(ch), units[len(s) - i - 1]
        out += (digits[d] + u) if d else ("零" if out and not out.endswith("零") else "")
    out = out.rstrip("零")
    return out[1:] if out.startswith("一十") else out


def norm(s):
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\d+", zh_num, s.lower()).replace("点", ".")
    return re.sub(r"[\s，。、！？!?,.…：:；;\"'“”‘’（）()\-—·]", "", s)


def check_voice_model(voice, model, sts=False):
    """Professional cloned voices are trained separately per model: exits if not trained for this model, listing usable models.
    Passes if voice.sts is enabled and the STS model is trained: the untrained model reads accurately, and STS restores the original voice timbre."""
    try:
        v = json.loads(call(f"/v1/voices/{voice}"))
    except SystemExit:
        return
    state = (v.get("fine_tuning") or {}).get("state") or {}
    if v.get("category") != "professional" or state.get(model) == "fine_tuned":
        return
    if sts and state.get(STS_MODEL) == "fine_tuned":
        print(f"Voice '{v.get('name')}' not trained for {model}: reading with {model}, then restoring original voice timbre with {STS_MODEL}")
        return
    ready = [m for m, s in state.items() if s == "fine_tuned" and "sts" not in m]
    sys.exit(f"Voice '{v.get('name')}' is not trained for {model} ({state.get(model, 'no record')}). Trained models: {', '.join(ready) or 'none'}.\n"
             f"Two options: 1) Switch voice.model to one of the trained models (eleven_multilingual_v2 requires stability 0.85; when brand names contain English it may slur or produce long tails, so configure keywords);\n"
             f"2) Keep {model} and set voice.sts: true (available when {STS_MODEL} is trained: accurate pronunciation + authentic timbre)")


def voiceover(args):
    tm = json.load(open(os.path.join(ROOT, "src", "timing.json"), encoding="utf-8"))
    cfg = tm.get("voice")
    if not cfg or not cfg.get("lines"):
        sys.exit("timing.json has no voice.lines: write the voiceover lines table first (see references/voiceover.md)")
    voice = args.voice or cfg["voiceId"]
    model = args.model or cfg.get("model", "eleven_v4")
    sts = cfg.get("sts") and {"stability": 0.5, "similarity_boost": 0.9, "style": 0.0, "use_speaker_boost": True}
    check_voice_model(voice, model, bool(sts))
    lang = cfg.get("language", "zh")
    settings = cfg.get("settings", {"stability": 0.5, "similarity_boost": 0.75, "use_speaker_boost": True})
    keywords = cfg.get("keywords", [])
    out = args.out or VO
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    lines = cfg["lines"]
    if args.only:
        wanted = set(args.only.split(","))
    report, cache_path = [], os.path.join(out, "cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    last = os.path.join(out, "report.json")
    prev = {r["id"]: r for r in json.load(open(last, encoding="utf-8")).get("lines", [])} if os.path.exists(last) else {}
    for r in prev.values():
        if r["status"] not in ("OK", "TOO_LONG"):
            cache.pop(r["id"], None)
    for i, ln in enumerate(lines):
        if args.only and ln["id"] not in wanted:
            continue
        say = ln.get("say", ln["text"])
        sig = hashlib.sha1(json.dumps([say, voice, model, settings, lang, sts]).encode()).hexdigest()
        raw = os.path.join(out, "raw", f"{ln['id']}.mp3")
        if cache.get(ln["id"]) != sig or not os.path.exists(raw):
            body = {"text": say, "model_id": model, "language_code": lang, "voice_settings": settings}
            # eleven_v3 does not support previous_text / next_text context stitching parameters
            if not model.startswith("eleven_v3"):
                if i > 0:
                    body["previous_text"] = lines[i - 1].get("say", lines[i - 1]["text"])
                if i + 1 < len(lines):
                    body["next_text"] = lines[i + 1].get("say", lines[i + 1]["text"])
            best = -1.0
            for k in range(args.takes):
                take = raw.replace(".mp3", f".take{k}.mp3")
                open(take, "wb").write(call(f"/v1/text-to-speech/{voice}?output_format=mp3_44100_192", body))
                if sts:
                    # STS can blur short words, so pick based on the post-conversion result
                    os.replace(take, take + ".tts.mp3")
                    to_voice(take + ".tts.mp3", take, voice, sts)
                    os.remove(take + ".tts.mp3")
                if args.takes == 1:
                    os.replace(take, raw)
                    break
                trim(take, take + ".t.mp3")
                got = transcribe(take + ".t.mp3", lang)
                score = difflib.SequenceMatcher(None, norm(say), norm(got)).ratio() - 0.5 * len(missing_words(keywords, say, got))
                os.remove(take + ".t.mp3")
                if score > best:
                    best = score
                    os.replace(take, raw)
                else:
                    os.remove(take)
                if best >= 0.95:
                    break
            cache[ln["id"]] = sig
            json.dump(cache, open(cache_path, "w"), indent=1)
        dst = os.path.join(out, f"{ln['id']}.mp3")
        trim(raw, dst)
        d = duration(dst)
        room = ln["end"] - ln["at"]
        tempo = 1.0
        if d > room:
            tempo = min(MAX_TEMPO, d / room)
            trim(raw, dst, tempo)
            d = duration(dst)
        heard = transcribe(dst, lang)
        score = difflib.SequenceMatcher(None, norm(say), norm(heard)).ratio()
        lost = missing_words(keywords, say, heard)
        tail = tail_ms(raw)
        status = "OK"
        if d > room + 0.05:
            status = "TOO_LONG"
        elif score < 0.85:
            status = "CHECK_TEXT"
        elif lost:
            status = "CHECK_WORD"
        elif tail > MAX_TAIL_MS:
            status = "ECHO"
        report.append({"id": ln["id"], "at": ln["at"], "dur": round(d, 2), "room": round(room, 2), "tempo": round(tempo, 3), "match": round(score, 2), "lost": lost, "tail_ms": tail, "heard": heard, "status": status})
        print(f"{status:10s} {ln['id']:10s} {d:5.2f}s / {room:4.2f}s  tempo {tempo:.2f}  match {score:.2f}  tail {tail:3d}ms{'  Missing words: ' + ','.join(lost) if lost else ''}  [{heard}]")
    prev.update({r["id"]: r for r in report})
    report = [prev[ln["id"]] for ln in lines if ln["id"] in prev]
    json.dump({"voice": voice, "model": model, "sts": bool(sts), "lines": report}, open(last, "w"), ensure_ascii=False, indent=1)
    bad = [r for r in report if r["status"] != "OK"]
    if bad:
        print(
            f"\n{len(bad)} line(s) need attention: TOO_LONG: shorten text or widen time window; CHECK_TEXT: rewrite according to heard audio (write numbers as words, split English);\n"
            "CHECK_WORD: brand keyword mispronounced, switch model (eleven_v3) or add commas before/after keyword; ECHO: long reverb tail, switch model or timbre (see references/voiceover.md)"
        )
        sys.exit(1)


def check_mix(args):
    tm = json.load(open(os.path.join(ROOT, "src", "timing.json"), encoding="utf-8"))
    lines = (tm.get("voice") or {}).get("lines", [])
    src_ = args.file or os.path.join(ROOT, "public", "audio", "mix.wav")
    tmp = "/tmp/_check_mix.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src_, "-b:a", "192k", tmp], check=True)
    heard = transcribe(tmp, (tm.get("voice") or {}).get("language", "zh"))
    h = norm(heard)
    print("Heard:", heard)
    missing = []
    for ln in lines:
        say = norm(ln.get("say", ln["text"]))
        # Sliding window search in transcript for best match: tolerates 1-2 homophone errors, counts as missing only if entire sentence is unheard
        best = max(difflib.SequenceMatcher(None, say, h[i : i + len(say)]).ratio() for i in range(max(1, len(h) - len(say) + 1)))
        if best < 0.8:
            missing.append(f"{ln['id']}({best:.2f})")
    total = difflib.SequenceMatcher(None, norm("".join(l.get("say", l["text"]) for l in lines)), h).ratio()
    print(f"Overall match {total:.3f} (required >= 0.97); Unclear sentences: {missing or 'None'}")
    # Full-track transcription has random noise: slice out unclear sentences and transcribe twice; if both are correct, it's just transcription error, no mix adjustment needed
    lang = (tm.get("voice") or {}).get("language", "zh")
    real = []
    for ln in lines:
        if not any(m.startswith(ln["id"] + "(") for m in missing):
            continue
        cut = f"/tmp/_check_{ln['id']}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(max(0, ln["at"] - 0.3)), "-to", str(ln["end"] + 0.3), "-i", src_, "-b:a", "192k", cut], check=True)
        say = norm(ln.get("say", ln["text"]))
        tries = [transcribe(cut, lang) for _ in range(2)]
        ok = all(difflib.SequenceMatcher(None, say, norm(x)).ratio() >= 0.85 for x in tries)
        print(f"  Segment recheck {ln['id']}: {' / '.join(tries)} -> {'Full-track transcription variance only' if ok else 'Actually unclear'}")
        if not ok:
            real.append(ln["id"])
    script = "".join(l.get("say", l["text"]) for l in lines)
    lost = missing_words((tm.get("voice") or {}).get("keywords", []), script, heard)
    if lost:
        print(f"Misheard keywords: {lost} (brand names and URLs must match every character)")
    if total < 0.97 or real or lost:
        print("Fixes: For sentences truly unclear, regenerate that line (vo --takes 4, delete raw/<id>.mp3) or rephrase;\n"
              "If vocals are masked by simultaneous SFX during segment recheck, reduce that SFX or deepen duckDb for this line")
        sys.exit(1)


def voices(args):
    d = json.loads(call("/v2/voices?page_size=100"))
    for v in d.get("voices", []):
        lab = v.get("labels", {})
        print(f"{v['voice_id']}  {v['name'][:32]:32s} {v.get('category')}  {lab.get('gender')} {lab.get('age')} {lab.get('language') or ''}")
    if args.zh:
        for g in ("male", "female"):
            q = f"/v1/shared-voices?language=zh&gender={g}&page_size=12&sort=usage_character_count_1y"
            for v in json.loads(call(q)).get("voices", []):
                print(f"{v['voice_id']}  {v['name'][:32]:32s} VoiceLibrary  {v.get('gender')} {v.get('age')} {v.get('accent')} {v.get('use_case')}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("quota")
    vs = sub.add_parser("voices")
    vs.add_argument("--zh", action="store_true")
    v = sub.add_parser("vo")
    v.add_argument("--voice", help="Override voiceId in timing.json (for testing voices)")
    v.add_argument("--model", help="Override model in timing.json (for comparing models, use with --out)")
    v.add_argument("--out", help="Output directory, default audio-src/vo")
    v.add_argument("--only", help="Only generate these line IDs, comma-separated")
    v.add_argument("--takes", type=int, default=1, help="Max takes per line, keeping the most accurate transcription (use 3~4 when cloned voice pronunciation is unstable)")
    cm = sub.add_parser("check-mix")
    cm.add_argument("file", nargs="?")
    st = sub.add_parser("stt")
    st.add_argument("file")
    st.add_argument("--lang", default="zh")
    s = sub.add_parser("sfx")
    s.add_argument("name")
    s.add_argument("prompt")
    s.add_argument("--dur", type=float, help="0.5~30 seconds, omitted to let model decide")
    s.add_argument("--influence", type=float, default=0.6, help="0~1, higher adheres closer to prompt")
    s.add_argument("--loop", action="store_true", help="Seamless loop (suitable for backing rhythm)")
    m = sub.add_parser("music")
    m.add_argument("name")
    m.add_argument("plan", help="composition plan JSON：{\"chunks\": [{text, duration_ms, positive_styles, negative_styles}]}")
    a = ap.parse_args()

    if a.cmd == "quota":
        d = json.loads(call("/v1/user/subscription"))
        print(f"Tier {d.get('tier')} | Used {d.get('character_count')} / {d.get('character_limit')}")
    elif a.cmd == "voices":
        voices(a)
    elif a.cmd == "vo":
        voiceover(a)
    elif a.cmd == "check-mix":
        check_mix(a)
    elif a.cmd == "stt":
        print(transcribe(a.file, a.lang))
    elif a.cmd == "sfx":
        body = {"text": a.prompt, "prompt_influence": a.influence, "loop": a.loop}
        if a.dur:
            body["duration_seconds"] = a.dur
        save(a.name, call("/v1/sound-generation?output_format=mp3_44100_192", body), a.prompt, {k: v for k, v in body.items() if k != "text"})
    elif a.cmd == "music":
        plan = json.load(open(a.plan, encoding="utf-8"))
        body = {"composition_plan": plan, "model_id": "music_v2_5"}
        save(a.name, call("/v1/music?output_format=mp3_48000_320", body), os.path.basename(a.plan), {"chunks": len(plan.get("chunks", []))})


if __name__ == "__main__":
    main()
