"""Thai TTS per narration line. Providers: gemini (default), edge, elevenlabs, google (Cloud TTS)."""
import os, base64, io, json, time, wave, asyncio, re, requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .util import run, probe_duration, sha
from .config import gemini_key, PRICES

VOICES = {
    "gemini":     {"male": "Charon", "female": "Kore"},
    "edge":       {"male": "th-TH-NiwatNeural", "female": "th-TH-PremwadeeNeural"},
    "elevenlabs": {"male": "JBFqnCBsd6RMkjVDRZzb", "female": "cgSgspJ2msm6clMCkdW9"},  # George / Jessica (eleven_v3)
    "google":     {"male": "th-TH-Chirp3-HD-Charon", "female": "th-TH-Chirp3-HD-Kore"},
}
GEMINI_TTS_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"]
STYLE = ("Read this Thai line as a gripping, fast-paced Thai movie-recap narrator on TikTok: energetic, "
         "suspenseful, natural conversational Thai, no long pauses. Speak only the Thai text: ")

class TTSQuota(Exception):
    pass

def _gemini(text, voice, out_raw: Path, timeout=45, attempts=2):
    """One line via Gemini TTS. Short timeouts: under 503/high-demand we'd rather fall back than wait minutes."""
    last = None
    for model in GEMINI_TTS_MODELS[:1]:
        for attempt in range(attempts):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": gemini_key()}, timeout=timeout, json={
                    "contents": [{"parts": [{"text": STYLE + text}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
            except requests.RequestException as ex:
                last = f"timeout/conn: {ex}"[:200]; continue
            if r.status_code == 200:
                d = r.json()
                try:
                    p = d["candidates"][0]["content"]["parts"][0]["inlineData"]
                except (KeyError, IndexError):
                    last = f"empty audio: {str(d)[:200]}"; continue
                data = base64.b64decode(p["data"])
                if p["mimeType"].startswith("audio/wav") or data[:4] == b"RIFF":
                    out_raw.write_bytes(data)
                else:
                    rate = int(re.search(r"rate=(\d+)", p["mimeType"]).group(1)) if "rate=" in p["mimeType"] else 24000
                    with wave.open(str(out_raw), "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(data)
                u = d.get("usageMetadata", {})
                return {"model": model, "in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0)}
            last = f"{r.status_code} {r.text[:200]}"
            if r.status_code == 429 and ("PerDay" in r.text or "limit: 0" in r.text):
                raise TTSQuota(f"Gemini TTS daily quota exhausted ({model})")
            if r.status_code in (400, 404):
                break
            m = re.search(r'"retryDelay":\s*"(\d+)s"', r.text)
            time.sleep(min(int(m.group(1)) + 1, 20) if m else 3)
    raise TTSQuota(f"Gemini TTS failed: {last}")

def _edge(text, voice, out_raw: Path, speed):
    """Always +0% rate (non-zero rates intermittently return NoAudioReceived); speed is applied later with atempo."""
    import edge_tts
    async def go():
        await edge_tts.Communicate(text, voice).save(str(out_raw))
    for k in range(4):
        try:
            asyncio.run(go())
            if out_raw.exists() and out_raw.stat().st_size > 1000:
                return {"model": "edge", "chars": len(text)}
        except Exception as ex:
            last = ex
        time.sleep(1.5 * (k + 1))
    raise TTSQuota(f"Edge TTS failed: {last if 'last' in dir() else 'no audio'}")

import threading
_EL_LOCK = threading.Lock()

def _eleven(text, voice, out_raw: Path):
    with _EL_LOCK:   # free/starter plans allow very few concurrent requests
        for k in range(3):
            r = _eleven_once(text, voice)
            if r.status_code != 429 or "concurrent" not in r.text:
                break
            time.sleep(2 * (k + 1))
    if r.status_code != 200:
        raise TTSQuota(f"ElevenLabs {r.status_code}: {r.text[:200]}")
    out_raw.write_bytes(r.content)
    return {"model": "eleven_v3", "chars": len(text)}

def _eleven_once(text, voice):
    return requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=120,
                      json={"text": text, "model_id": "eleven_v3", "language_code": "th"})

def _google(text, voice, out_raw: Path, speed):
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                      params={"key": os.environ.get("GOOGLE_TTS_API_KEY", "")}, timeout=60, json={
        "input": {"text": text}, "voice": {"languageCode": "th-TH", "name": voice},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000, "speakingRate": speed}})
    if r.status_code != 200:
        raise TTSQuota(f"Google TTS {r.status_code}: {r.text[:200]}")
    out_raw.write_bytes(base64.b64decode(r.json()["audioContent"]))
    return {"model": voice, "chars": len(text)}

def eleven_remaining():
    try:
        d = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                         headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=20).json()
        return d["character_limit"] - d["character_count"]
    except Exception:
        return 0

def _post(raw: Path, out: Path, tempo: float):
    """-> 48k mono wav, leading/trailing silence trimmed, tempo applied."""
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
    af = trim + (f",atempo={tempo:.3f}" if abs(tempo - 1) > 0.01 else "")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", af, "-ar", "48000", "-ac", "1", str(out)])
    return probe_duration(out)

_google_ok = None
def google_available():
    global _google_ok
    if _google_ok is None:
        try:
            r = requests.get("https://texttospeech.googleapis.com/v1/voices", params={
                "languageCode": "th-TH", "key": os.environ.get("GOOGLE_TTS_API_KEY", "")}, timeout=15)
            _google_ok = r.status_code == 200
        except Exception:
            _google_ok = False
    return _google_ok

def _call(prov, text, voice, raw, speed, fast=True):
    if prov == "gemini": return _gemini(text, voice, raw, timeout=45 if fast else 120)
    if prov == "edge": return _edge(text, voice, raw, speed)
    if prov == "elevenlabs": return _eleven(text, voice, raw)
    return _google(text, voice, raw, speed)

def _raw_path(workdir, prov, voice, text, speed):
    h = sha(f"{prov}|{voice}|{text}|{speed if prov == 'google' else ''}")
    return workdir / f"raw_{h}.{'mp3' if prov in ('edge','elevenlabs') else 'wav'}"

def fallback_chain(primary, lines):
    chain = [primary]
    chars = sum(len(l["text"]) for l in lines)
    if primary != "elevenlabs" and eleven_remaining() >= chars // 3:
        chain.append("elevenlabs")
    if primary != "google" and google_available():
        chain.append("google")
    if primary != "gemini" and "gemini" not in chain:
        chain.append("gemini")
    if "edge" not in chain:
        chain.append("edge")
    return chain

def synthesize(lines, provider, gender, speed, workdir: Path, prog, deadline_s=240, max_mixed=0.25):
    """Per-line TTS, parallel with limits. Each line tries the primary provider (short timeout), then falls back
    line-by-line along the chain (ElevenLabs -> Google Cloud -> Edge). If more than `max_mixed` of the lines needed a
    fallback, the whole script is re-voiced with the single best fallback so the narrator stays consistent.
    Sets line['audio'], line['dur'], line['tts']. Returns (provider_summary, voice_summary)."""
    workdir.mkdir(parents=True, exist_ok=True)
    if provider == "google" and not google_available():
        prog(35, "Google Cloud TTS key ใช้ไม่ได้ → ใช้ Gemini TTS"); provider = "gemini"
    if provider == "elevenlabs" and eleven_remaining() < sum(len(l["text"]) for l in lines):
        prog(35, "ElevenLabs เครดิตไม่พอทั้งบท → ใช้ Gemini TTS"); provider = "gemini"
    if provider == "gemini" and os.environ.get("RECAP_TTS_BATCH") == "1":
        m = synthesize_batch(lines, gender, speed, workdir, prog)
        if m:
            return "gemini", f"{VOICES['gemini'][gender]} ({m})"
        prog(41, "Gemini batch TTS ใช้ไม่ได้ → โหมดทีละบรรทัด + fallback")
    chain = fallback_chain(provider, lines)
    t_start = time.time(); stats = {}; done = [0]
    eleven_budget = [eleven_remaining() if "elevenlabs" in chain else 0]

    def voice_one(i, chain_here):
        ln = lines[i]
        for prov in chain_here:
            voice = VOICES[prov][gender]
            raw = _raw_path(workdir, prov, voice, ln["text"], speed)
            if not (raw.exists() and raw.stat().st_size > 1000):
                if prov == "gemini" and prov != chain_here[-1] and time.time() - t_start > deadline_s:
                    continue  # primary too slow overall -> straight to fallback
                if prov == "elevenlabs":
                    if eleven_budget[0] < len(ln["text"]):
                        continue
                    eleven_budget[0] -= len(ln["text"])
                tmp = raw.with_name(raw.stem + ".part" + raw.suffix)
                try:
                    st = _call(prov, ln["text"], voice, tmp, speed)
                    tmp.rename(raw); stats.setdefault(prov, []).append(st)
                except Exception as ex:
                    print(f"  line {i+1}: {prov} failed ({str(ex)[:100]})", flush=True)
                    continue
            tempo = 1.0 if prov == "google" else speed
            out = workdir / f"line_{i:02d}.wav"
            ln["dur"] = _post(raw, out, tempo); ln["audio"] = str(out); ln["tts"] = prov; ln["voice"] = voice
            done[0] += 1
            prog(35 + 20 * done[0] / len(lines), f"TTS บรรทัด {done[0]}/{len(lines)} ({prov})")
            return prov
        raise RuntimeError(f"line {i+1}: all TTS providers failed")

    # probe the primary on line 1 first: if its daily quota is gone, voice the whole script with one fallback
    pv = VOICES[chain[0]][gender]
    probe = next((i for i, l in enumerate(lines) if not _raw_path(workdir, chain[0], pv, l["text"], speed).exists()), 0)
    try:
        first = voice_one(probe, [chain[0]])
    except Exception as ex:
        first = None
        prog(36, f"{chain[0]} ใช้ไม่ได้ตอนนี้ ({str(ex)[:80]}) → ใช้ provider สำรองทั้งบท")
        total_chars = sum(len(l["text"]) for l in lines)
        for fb in chain[1:]:
            if fb == "elevenlabs" and eleven_remaining() < total_chars:
                continue
            chain = [fb] + [c for c in chain if c not in (fb, chain[0])]
            break
    workers = {"gemini": 4, "elevenlabs": 1, "edge": 2}.get(chain[0], 3)
    with ThreadPoolExecutor(workers) as ex:
        used = list(ex.map(lambda i: voice_one(i, chain), range(len(lines))))
    n_fb = sum(1 for u in used if u != chain[0])
    if n_fb and n_fb / len(lines) > max_mixed and chain[0] == "gemini":
        # patience pass: give the primary voice one more, slower try on just the fallback lines
        prog(50, f"Gemini TTS ช้า: ลองใหม่ {n_fb} บรรทัดแบบรอนานขึ้น")
        def retry(i):
            ln = lines[i]; voice = VOICES["gemini"][gender]
            raw = _raw_path(workdir, "gemini", voice, ln["text"], speed)
            tmp = raw.with_name(raw.stem + ".part" + raw.suffix)
            try:
                st = _gemini(ln["text"], voice, tmp, timeout=120, attempts=2); tmp.rename(raw)
                stats.setdefault("gemini", []).append(st)
                ln["dur"] = _post(raw, Path(ln["audio"]), speed); ln["tts"] = "gemini"; ln["voice"] = voice
                return "gemini"
            except Exception:
                return used[i]
        with ThreadPoolExecutor(4) as ex:
            used = list(ex.map(lambda i: retry(i) if used[i] != "gemini" else "gemini", range(len(lines))))
        n_fb = sum(1 for u in used if u != chain[0])
    if n_fb and n_fb / len(lines) > max_mixed:
        # too many mixed voices -> re-voice everything with the first fallback that works for all lines
        for fb in chain[1:]:
            if fb == "elevenlabs" and eleven_remaining() < sum(len(l["text"]) for l in lines):
                continue
            prog(52, f"{chain[0]} ช้า/ล้ม {n_fb}/{len(lines)} บรรทัด → พากย์ใหม่ทั้งบทด้วย {fb} ให้เสียงเดียวกัน")
            done[0] = 0
            try:
                with ThreadPoolExecutor(4) as ex:
                    used = list(ex.map(lambda i: voice_one(i, [fb]), range(len(lines))))
                break
            except Exception as e:
                prog(52, f"{fb} ล้มเหลว: {str(e)[:100]}")
    # cost accounting
    for prov, sts in stats.items():
        chars = sum(len(l["text"]) for l in lines if l.get("tts") == prov)
        if prov == "gemini":
            tin = sum(s.get("in", 0) for s in sts); tout = sum(s.get("out", 0) for s in sts)
            pi, po = PRICES["tts-gemini"]
            prog.add_cost("TTS gemini", tin / 1e6 * pi + tout / 1e6 * po, f"{tin} in / {tout} audio tokens, {len(sts)} calls")
        elif prov == "elevenlabs":
            c = sum(s.get("chars", 0) for s in sts)
            prog.add_cost("TTS elevenlabs eleven_v3", c / 1000 * PRICES["tts-elevenlabs_per_1k_chars"], f"{c} chars")
        elif prov == "google":
            c = sum(s.get("chars", 0) for s in sts)
            prog.add_cost("TTS google", c / 1e6 * PRICES["tts-google_per_1m_chars"], f"{c} chars")
        else:
            c = sum(s.get("chars", 0) for s in sts)
            prog.add_cost("TTS edge", 0.0, f"{c} chars (free)")
    provs = sorted({l["tts"] for l in lines}); voices = sorted({l["voice"] for l in lines})
    return "+".join(provs), "+".join(voices)


# ---------------------------------------------------------------------------
# Batch mode: the whole script in ONE Gemini TTS request, then split per line by
# aligning detected pauses to the expected (char-proportional) line boundaries.
# Free-tier Gemini TTS allows only ~10 requests/day/model, so 1 request/video matters.
# ---------------------------------------------------------------------------
# Only 3.1: in tests 3.8-flash-lite dropped whole lines and 3.8-flash read the English style prompt aloud.
BATCH_MODELS = ["gemini-3.1-flash-tts-preview"]

def _silences(path, noise="-38dB", d=0.10):
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"silencedetect=n={noise}:d={d}",
                        "-f", "null", "-"], capture_output=True, text=True)
    out, cur = [], None
    for ln in r.stderr.splitlines():
        if "silence_start" in ln:
            cur = float(ln.split("silence_start:")[1])
        elif "silence_end" in ln and cur is not None:
            end = float(ln.split("silence_end:")[1].split("|")[0]); out.append((cur, end)); cur = None
    return out

def _llm_boundaries(audio: Path, lines, prog):
    """Ask a Gemini text model (separate quota from TTS) when each line starts in the long take. ~±0.5 s; we snap to pauses."""
    from .llm import generate_json
    from google.genai import types
    numbered = "\n".join(f"{i+1}. {l['text']}" for i, l in enumerate(lines))
    prompt = ("This audio is a Thai narrator reading the numbered lines below in order. For EACH line give the time in "
              "seconds (float, 2 decimals) where its first word starts. Return JSON {\"starts\": [float,...]} with exactly "
              f"{len(lines)} numbers.\n\n" + numbered)
    try:
        part = types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/wav")
        d, _ = generate_json([part, prompt], prog, "TTS line alignment",
                             models=["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.8-flash"], temperature=0.0)
        st = [float(x) for x in d["starts"]]
        if len(st) == len(lines) and all(b > a for a, b in zip(st, st[1:])):
            return st[1:]
    except Exception as ex:
        print(f"  llm alignment failed: {str(ex)[:120]}", flush=True)
    return None

def _align(gaps, total, weights, expected=None):
    """Pick len(weights)-1 gaps (monotonic) that best match expected boundaries. DP, returns gap indices."""
    n = len(weights) - 1
    if len(gaps) < n:
        return None
    cum, s = [], 0
    for w in weights[:-1]:
        s += w; cum.append(total * s / sum(weights))
    if expected and len(expected) == n:
        cum = expected
    G = len(gaps)
    def cost(k, g):
        mid = (gaps[g][0] + gaps[g][1]) / 2; dur = gaps[g][1] - gaps[g][0]
        return abs(mid - cum[k]) / (0.6 if expected else max(total / len(weights), 0.5)) - min(dur, 0.6) * 1.5
    INF = 1e18
    dp = [[INF] * G for _ in range(n)]; bk = [[-1] * G for _ in range(n)]
    for g in range(G):
        dp[0][g] = cost(0, g)
    for k in range(1, n):
        best, bi = INF, -1
        for g in range(G):
            if g - 1 >= 0 and dp[k - 1][g - 1] < best:
                best, bi = dp[k - 1][g - 1], g - 1
            if bi >= 0:
                dp[k][g] = best + cost(k, g); bk[k][g] = bi
    g = min(range(G), key=lambda x: dp[n - 1][x])
    if dp[n - 1][g] >= INF:
        return None
    path = [g]
    for k in range(n - 1, 0, -1):
        g = bk[k][g]; path.append(g)
    return path[::-1]

def synthesize_batch(lines, gender, speed, workdir: Path, prog, models=None):
    """Returns True on success (sets audio/dur/tts/voice on every line)."""
    voice = VOICES["gemini"][gender]
    text = "\n".join(l["text"] for l in lines)
    for model in (models or BATCH_MODELS):
        raw = workdir / f"batch_{sha(model + voice + text)}.wav"
        st = None
        if not raw.exists():
            prefix = STYLE.replace("this Thai line", "these Thai lines, one after another with a short breath between lines,") \
                if model.startswith("gemini-3.1") else ""
            try:
                prog(38, f"Gemini TTS ({model}) พากย์ทั้งบทในคำขอเดียว")
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": gemini_key()}, timeout=180, json={
                    "contents": [{"parts": [{"text": prefix + text}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}})
            except requests.RequestException as ex:
                print(f"  batch {model}: {ex}", flush=True); continue
            if r.status_code != 200:
                print(f"  batch {model}: {r.status_code} {r.text[:150]}", flush=True); continue
            d = r.json()
            try:
                p = d["candidates"][0]["content"]["parts"][0]["inlineData"]
            except (KeyError, IndexError):
                continue
            data = base64.b64decode(p["data"])
            if data[:4] == b"RIFF":
                raw.write_bytes(data)
            else:
                with wave.open(str(raw), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(data)
            u = d.get("usageMetadata", {}); st = (u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
        # trim outer silence, then find pauses
        trimmed = workdir / f"{raw.stem}_trim.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af",
             "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
             "-ar", "48000", "-ac", "1", str(trimmed)])
        total = probe_duration(trimmed)
        gaps = [g for g in _silences(trimmed) if 0.05 < g[0] < total - 0.05]
        from .subs import vis_len
        expected = _llm_boundaries(trimmed, lines, prog)
        path = _align(gaps, total, [max(1, vis_len(l["text"])) for l in lines], expected)
        if path is None:
            prog(40, f"แยกบรรทัดจากเสียงรวมไม่ได้ ({len(gaps)} ช่วงเงียบ < {len(lines)-1}) → ลองโมเดลถัดไป"); continue
        cuts = [0.0] + [(gaps[g][0] + gaps[g][1]) / 2 for g in path] + [total]
        # sanity: every piece should be roughly proportional to its text (0.35x..2.8x of expectation)
        exp_cps = sum(vis_len(l["text"]) for l in lines) / total
        bad = [i for i, l in enumerate(lines) if not (0.5 < (cuts[i + 1] - cuts[i]) * exp_cps / max(1, vis_len(l["text"])) < 2.0)]
        if len(bad) > max(1, len(lines) // 8):
            prog(40, f"การแยกบรรทัดไม่น่าเชื่อถือ ({len(bad)} บรรทัดผิดสัดส่วน) → ลองโมเดลถัดไป"); continue
        for i, ln in enumerate(lines):
            piece = workdir / f"{raw.stem}_p{i:02d}.wav"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(trimmed), "-ss", f"{cuts[i]:.3f}", "-to", f"{cuts[i+1]:.3f}", str(piece)])
            out = workdir / f"line_{i:02d}.wav"
            ln["dur"] = _post(piece, out, speed); ln["audio"] = str(out); ln["tts"] = "gemini"; ln["voice"] = voice
            ln["raw"] = str(piece)
        if st:
            pi, po = PRICES["tts-gemini"]
            prog.add_cost(f"TTS gemini batch ({model}, {voice})", st[0] / 1e6 * pi + st[1] / 1e6 * po,
                          f"1 request, {st[0]} in / {st[1]} audio tokens, {len(text)} chars")
        else:
            prog.add_cost(f"TTS gemini batch ({model}, cached)", 0.0, "cached")
        prog(55, f"Gemini TTS {model}: แยกได้ {len(lines)} บรรทัด จากเสียงรวม {total:.1f}s")
        return model
    return None
