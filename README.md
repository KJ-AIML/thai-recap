# Thai Recap — วางลิงก์ ได้คลิปเล่าเรื่องพากย์ไทย

เครื่องมือรันบนเครื่องตัวเอง (http://127.0.0.1:8000) วางลิงก์วิดีโอหรืออัปโหลดไฟล์ → Gemini ดูคลิปทั้งเรื่องแล้วแบ่งฉาก →
เขียนบทพากย์ไทยสไตล์ช่อง "เล่าหนัง" (เปิดด้วย hook, เล่าเร็ว, ภาษาพูด) → พากย์ไทยทีละบรรทัด → ตัดภาพให้พอดีเสียง
(ตัด / สโลว์ / ฟรีซ / ซูมช้า / Ken Burns) → ซับไทยตัวใหญ่ (Kanit, ตัดคำด้วย PyThaiNLP, ไฮไลต์คำสำคัญสีเหลือง) →
ได้ MP4 แนวตั้ง 9:16 และ/หรือ 16:9 + ภาพปกพร้อมชื่อเรื่องภาษาไทย + แคปชัน/แฮชแท็ก

A local "paste a video URL → get a Thai‑narrated recap short" tool. Clean MIT-compatible pipeline (no AGPL code);
ideas borrowed from NarratoAI / MoneyPrinterTurbo.

## Pipeline
| Step | Tech |
|---|---|
| Download | `yt-dlp` (≤720p, prefers H.264) or direct .mp4 URL / upload → normalized H.264 master + 360p proxy |
| Understand | Gemini File API, JSON scene list with timestamps, dramatic score, story beat, best thumbnail time. Model chain: `gemini-3.1-pro-preview` → `gemini-3.8-flash` → `gemini-3.5-flash` → `gemini-3-flash-preview` → `gemini-2.5-pro` (unavailable/timeout models are skipped for 1 h) |
| Script | Same chain, text-only call on the scene list → Thai lines with `src_start/src_end`, `visual` (video/still), `emphasis`, `keyword`, cover title, caption, hashtags |
| Voice | Gemini TTS `gemini-3.1-flash-tts-preview` (default; male *Charon*, female *Kore*, style-prompted as recap narrator) · Edge TTS (free fallback, Niwat/Premwadee) · ElevenLabs `eleven_v3` · Google Cloud Chirp3-HD. Per-line synthesis (cached), silence trimmed, tempo via `atempo`, auto speed-up if script overshoots the target length |
| Edit | ffmpeg per segment: blur-fill reframe, 2× upscale + `zoompan` slow zoom / punch-zoom on emphasis, slow-mo or freeze to fit narration, Ken Burns on stills |
| Audio | narration loudnorm −14 LUFS, optional BGM ducked with `sidechaincompress` |
| Subs | PyThaiNLP `newmm` chunks (≤15 visible chars on 9:16), `.ass` with Kanit ExtraBold, pop-in, yellow keyword, title band on 9:16, credit line |
| Thumbnail | Gemini's dramatic frame (sanity-scored vs top dramatic scenes) + Pillow/raqm Thai title |
| Cost | token/char accounting per call → `output/<job>.json` (`cost_usd_paid_tier_est`) |

## Setup / ติดตั้ง
```bash
cd /workspace/thai-recap
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs ffmpeg (with libass) + yt-dlp
export GEMINI_API_KEY=...            # or GEMINI_TTS_API_KEY_2
export ELEVENLABS_API_KEY=...        # optional
export GOOGLE_TTS_API_KEY=...        # optional (Cloud Text-to-Speech API enabled)
./tools/make_bgm.sh                  # optional: generate an original music bed into assets/music/
```

## Run / ใช้งาน
Web UI:
```bash
.venv/bin/uvicorn recap.web:app --host 127.0.0.1 --port 8000
# เปิด http://127.0.0.1:8000
```
CLI:
```bash
.venv/bin/python -m recap.cli "https://www.youtube.com/watch?v=_cMxraX_5RE" \
  --length 75 --aspect both --gender male --speed 1.15 --visual mixed --tts gemini \
  --credit "ภาพ: Sprite Fright © Blender Foundation (CC BY 4.0)"
```
Options: `--length` seconds · `--gender male|female` · `--speed 0.8–1.5` · `--aspect 9:16|16:9|both` ·
`--visual video|mixed|image` · `--tts gemini|edge|elevenlabs|google` · `--bgm auto|none|file` · `--bgm-level 0.16`

Outputs go to `output/`: `<job>_9x16.mp4`, `<job>_16x9.mp4`, `<job>_thumb_*.jpg`, `<job>_script.txt`, `<job>.json`.
Everything is cached in `work/` (download, analysis, script, TTS) so re-renders are fast and cost nothing extra.

## ข้อควรระวัง / Caveats
- ใช้กับคลิปที่มีสิทธิ์เท่านั้น (คลิปของตัวเอง, Creative Commons, public domain). การ์ตูน/หนังมีลิขสิทธิ์จะโดน Content ID และไม่ได้เงิน
- CC‑BY sources need attribution → use `--credit`.
- Free-tier Gemini keys have 0 quota for Pro models → the tool falls back to Flash automatically. Enable billing for Pro.
- Edge TTS is an unofficial endpoint — fine for testing, use Gemini/ElevenLabs/Azure for anything commercial.

## TTS notes (tested 26 Oct 2026)
| Provider | Result | Notes |
|---|---|---|
| Gemini `gemini-3.1-flash-tts-preview` (Charon/Kore) | **Best**: exact transcript, fluent, fewest pauses, takes a style prompt | **Free tier = 10 requests/day/model** → per-line mode only covers ~10 lines/day. Enable billing, or try `RECAP_TTS_BATCH=1` (whole script in 1 request, split on pauses; experimental) |
| Gemini `gemini-3.8-flash-tts` | Rejected | read the English style prompt aloud / very slow with long pauses |
| Gemini `gemini-3.8-flash-lite-tts` | Rejected | dropped whole lines in a 3-line test, misread tone marks |
| ElevenLabs `eleven_v3` (`language_code=th`) | Good, natural | `eleven_multilingual_v2` rejects Thai. Free plan has ~1k chars left = not enough for one 75 s script (~1.2k chars) |
| Edge TTS Niwat / Premwadee | Good, exact transcript, free | unofficial endpoint; Premwadee/Achara intermittently return *NoAudioReceived*, so rate is fixed at +0% and speed is applied with `atempo` |
| Google Cloud Chirp3-HD | not tested | `GOOGLE_TTS_API_KEY` currently rejected as invalid |

Fallback logic: the primary provider is probed on the first uncached line; if its daily quota is gone the whole script goes to
one fallback (ElevenLabs if enough credits → Google → Edge) so the narrator stays one voice. Per-line fallback is used only
when ≤25 % of lines fail (`max_mixed`).
