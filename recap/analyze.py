"""Step 2+3: Gemini watches the video -> scene list; then writes the Thai recap script."""
import json, os
from pathlib import Path
from google.genai import types
from .llm import upload_video, generate_json
from .util import ts_to_sec, probe_duration, run

ANALYSIS_PROMPT = """You are a film editor preparing a recap/summary video. Watch this whole video carefully (it is {dur:.0f} seconds long).
Return ONLY JSON:
{{
 "title": str, "genre": str, "logline": str (1-2 sentences, spoilers allowed),
 "characters": [{{"id": str, "look": str (visual description so a narrator can nickname them), "role": str}}],
 "scenes": [{{
    "start": "MM:SS", "end": "MM:SS",
    "description": str (concrete: what is VISIBLY happening, who, actions, objects; 1-3 sentences),
    "characters": [str], "emotion": str, "dramatic_score": int 1-10,
    "shot": "wide|medium|closeup|insert|title_card|credits",
    "story_beat": "setup|inciting|rising|twist|climax|resolution|credits"
 }}],
 "best_thumbnail_time": "MM:SS" (the single most dramatic, readable frame; a face with strong emotion is best; never a title card),
 "ending": str
}}
Use BOTH the picture and the audio/dialogue (any language, incl. Thai dubs) to understand the plot: who is who (use the
characters' real names when spoken or well known), what they want, clues, reveals, the culprit/trick/motive if any, jokes.
Put plot-critical revealed facts into the scene descriptions. Skip/flag opening & ending theme songs, sponsor cards and
recaps of previous episodes as shot=title_card.
Rules: cover the WHOLE video in order with {scene_rule}, timestamps accurate to the second and non-overlapping.
Mark opening logos, title cards and end credits with shot=title_card/credits and dramatic_score 1."""

SCRIPT_PROMPT = """คุณคือนักเขียนบทพากย์ช่อง "สรุปหนัง/เล่าหนัง" ภาษาไทยบน TikTok และ YouTube Shorts ที่ยอดวิวสูงมาก
งาน: เขียนบทพากย์สรุปเรื่องนี้ให้ยาวประมาณ {target:.0f} วินาที (รวมประมาณ {chars} ตัวอักษรไทย แบ่งเป็น {nlines} บรรทัด บรรทัดละ 25-60 ตัวอักษร)

ข้อมูลฉากจากวิดีโอ (เวลาเป็นวินาทีของคลิปต้นฉบับ ความยาวรวม {dur:.0f} วินาที):
{scenes}

สไตล์ที่ต้องการ:
- บรรทัดแรกต้องเป็น hook ที่ทำให้คนหยุดเลื่อนทันที เช่น "แก๊งวัยรุ่นกลุ่มนี้ไม่รู้เลยว่า..." หรือเปิดด้วยเหตุการณ์ที่ช็อกที่สุด
- เล่าเร็ว กระชับ ใช้ภาษาพูดแบบคนไทยเล่าให้เพื่อนฟัง เป็นธรรมชาติ ไม่ใช่ภาษาเขียน ไม่ใช้ "ครับ/ค่ะ"
- ใช้ปัจจุบันกาล บุรุษที่สาม ใช้ชื่อตัวละครตามที่แฟนไทยเรียกกันจริง (เช่น โคนัน รัน โคโกโร่ / สึนะ รีบอร์น / ริก มอร์ตี้) ถ้าไม่รู้ชื่อให้ตั้งฉายาตามลักษณะที่เห็น
- ถ้าเป็นเรื่องสืบสวน ต้องเล่าให้ครบ: เหตุการณ์ ปม เบาะแสสำคัญ แล้วเฉลยคนร้าย/ทริกตอนท้าย ถ้าเป็นแนวตลก ให้จังหวะมุกชัด
- ใส่อารมณ์และความลุ้น ใช้คำเชื่อมแบบช่องเล่าหนัง เช่น "แต่แล้ว" "ทันใดนั้น" "ใครจะไปคิดว่า"
- เล่าแค่สิ่งที่เห็นในฉากจริง ห้ามแต่งเหตุการณ์ที่ไม่มีในข้อมูลฉาก
- เรียงตามเวลาของเรื่อง (ยกเว้น hook ที่ดึงฉากไคลแมกซ์มาเปิดได้) จบด้วยประโยคปิดที่หักมุม/ฮา/ค้างคา
- เขียนตัวเลขเป็นคำไทย ใช้ไม้ยมก (ๆ) ได้ตามปกติ ห้ามใช้อีโมจิ ห้ามใส่วงเล็บหรือเครื่องหมายคำพูด
- ห้ามใช้ฉาก title card, โลโก้ หรือ end credits

ตอบเป็น JSON เท่านั้น:
{{
 "title_th": "ชื่อปกภาษาไทย สั้น ดึงดูด ไม่เกิน 24 ตัวอักษร",
 "title_th_line2": "บรรทัดรองบนปก ไม่เกิน 20 ตัวอักษร",
 "lines": [{{
   "text": "บทพากย์ 1 บรรทัด",
   "src_start": วินาทีเริ่มของภาพที่ใช้ประกอบ (ตัวเลข),
   "src_end": วินาทีจบ (ตัวเลข, ห่างจาก src_start 2-8 วินาที, อยู่ในฉากเดียวกัน),
   "visual": "video" หรือ "still" (still = ภาพนิ่งซูมช้าๆ ใช้กับช่วงอารมณ์หรือภาพสวย),
   "emphasis": true/false (จังหวะหักมุม/ช็อก),
   "keyword": "คำสำคัญ 1 คำที่ต้องอยู่ใน text เพื่อไฮไลต์ในซับ"
 }}],
 "caption": "แคปชันโพสต์ภาษาไทย 1-2 ประโยค",
 "hashtags": ["#สรุปหนัง", ...]
}}
ภาพของแต่ละบรรทัดต้องตรงกับสิ่งที่บรรทัดนั้นพูดถึง และพยายามไม่ใช้ช่วงภาพซ้ำกัน{visual_hint}"""

VISUAL_HINTS = {
    "video": "\nให้ใช้ visual=\"video\" เกือบทั้งหมด ใช้ still ไม่เกิน 2 บรรทัด",
    "mixed": "\nผสม video และ still ตามความเหมาะสม (still ประมาณ 20-30%)",
    "image": "\nให้ใช้ visual=\"still\" เป็นหลัก (ประมาณ 70%) เลือกเฟรมที่สวยและสื่อความชัด",
}

CHUNK_SEC = int(os.environ.get("RECAP_CHUNK_SEC", "1500"))

EPISODE_NOTE = """
This video is EPISODE {k} of {n} of a compilation (it starts at {off:.0f} s of the full compilation); the episode title is
"{title}". Each episode is a self-contained story. Timestamps you return must be relative to THIS part (00:00 = start of
this part). Main characters seen in earlier episodes (for names only): {prev}
"""

CHUNK_NOTE = """
This video is PART {k} of {n} of a longer film (it starts at {off:.0f} s of the full film). Timestamps you return must be
relative to THIS part (00:00 = start of this part). Story so far (from the earlier parts, for names/context only):
{prev}
"""

def _coverage_ok(d, cd):
    sc = d.get("scenes") or []
    if not sc:
        return False
    end = max(ts_to_sec(x.get("end", 0)) for x in sc)
    descs = [x.get("description", "") for x in sc]
    repeated = len(descs) - len(set(descs))
    return end >= 0.8 * cd and repeated <= max(2, len(descs) // 8)

def _analyze_piece(src, cdir, tag, off, cd, label, prev, prog, pct, depth=0, title=None):
    """Analyse one piece of the proxy (cached). Weak/overloaded fallback models sometimes stop early or loop
    ("screen fades to black" x N); then the piece is re-done as 4 shorter sub-pieces and merged."""
    cj = cdir / f"{tag}.json"
    if cj.exists():
        d = json.loads(cj.read_text()); c = d["_cost"]
        prog.add_cost(c["item"] + " [cached; first-run cost]", c["usd"], c["detail"])
        return d
    cf = cdir / f"{tag}.mp4"
    if not cf.exists():
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{off:.2f}", "-t", f"{cd:.2f}", "-i", str(src),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(cf)])
    f = upload_video(cf, prog)
    prog(pct, f"Gemini ดูวิดีโอช่วง {label} ({off/60:.0f}-{(off+cd)/60:.0f} นาที)")
    nsc = f"{max(8, int(cd / 22))}-{max(14, int(cd / 12))} scenes, each 3-30 s"
    k, n = label.split("/")[0], label.split("/")[-1]
    note = (EPISODE_NOTE.format(k=k, n=n, off=off, prev=prev, title=title) if title
            else CHUNK_NOTE.format(k=k, n=n, off=off, prev=prev))
    prompt = ANALYSIS_PROMPT.format(dur=cd, scene_rule=nsc) + note
    d, model = generate_json([f, prompt], prog, f"scene analysis part {label}", temperature=0.3,
                             media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW)
    if isinstance(d, list):
        d = {"scenes": d} if d and "start" in d[0] else (d[0] if d else {})
    d["model"] = model; d["_cost"] = prog.cost[-1]
    if not _coverage_ok(d, cd) and depth == 0 and cd > 400:
        prog(pct, f"ผลวิเคราะห์ช่วง {label} ไม่ครบ ({model}) → แบ่งย่อย 4 ช่วง")
        subs_, sub_costs = [], [d["_cost"]]
        for j in range(4):
            so = j * cd / 4
            sd = _analyze_piece(src, cdir, f"{tag}_s{j}", off + so, cd / 4, f"{label}.{j+1}", prev, prog, pct, depth + 1)
            for x in sd["scenes"]:
                x["start"] = so + min(ts_to_sec(x.get("start", 0)), cd / 4)
                x["end"] = so + min(ts_to_sec(x.get("end", 0)), cd / 4)
            subs_.append(sd); sub_costs.append(sd["_cost"])
        d = {"scenes": [x for sd in subs_ for x in sd["scenes"]],
             "characters": [c for sd in subs_ for c in sd.get("characters", [])],
             "title": subs_[0].get("title"), "genre": subs_[0].get("genre"),
             "logline": " ".join(sd.get("logline") or "" for sd in subs_), "ending": subs_[-1].get("ending"),
             "best_thumbnail_time": None, "model": ",".join(sorted({sd["model"] for sd in subs_}))}
        d["_cost"] = {"item": f"scene analysis part {label} (split x4)", "usd": round(sum(c["usd"] for c in sub_costs), 5),
                      "detail": "; ".join(c["detail"] for c in sub_costs)}
    if not d.get("scenes"):
        raise RuntimeError(f"scene analysis part {label} returned no scenes")
    cj.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    return d

def _analyze_chunked(master: Path, prog, dur: float):
    """Long sources: split the 360p proxy into ~CHUNK_SEC pieces, analyse each (cached), merge the scene lists."""
    proxy = master.parent / "proxy.mp4"; src = proxy if proxy.exists() else master
    eps = _episodes(master, dur)
    if eps:
        bounds = [(e["start"], min(e["end"], dur) - e["start"], e["title"]) for e in eps]
    else:
        n = max(2, round(dur / CHUNK_SEC)); step = dur / n
        bounds = [(k * step, min(step, dur - k * step), None) for k in range(n)]
    n = len(bounds)
    cdir = master.parent / ("episodes" if eps else "chunks"); cdir.mkdir(exist_ok=True)
    merged = {"scenes": [], "characters": [], "chunks": [], "episodic": bool(eps)}; costs = []; prev = "(this is the first part)"
    for k, (off, cd, title) in enumerate(bounds):
        d = _analyze_piece(src, cdir, f"chunk_{k:02d}", off, cd, f"{k+1}/{n}", prev, prog, 12 + 12 * k / n, title=title)
        for sc in d["scenes"]:
            a = min(ts_to_sec(sc.get("start", 0)), cd); b = min(max(ts_to_sec(sc.get("end", 0)), a + 0.5), cd)
            sc["start_s"] = round(off + a, 2); sc["end_s"] = round(off + b, 2); sc["part"] = k + 1
            merged["scenes"].append(sc)
        names = {c.get("id") for c in merged["characters"]}
        merged["characters"] += [c for c in d.get("characters", []) if c.get("id") not in names]
        bt = d.get("best_thumbnail_time")
        merged["chunks"].append({"part": k + 1, "offset": off, "duration": cd, "episode_title": title, "logline": d.get("logline"), "ending": d.get("ending"),
                                 "best_thumbnail_s": off + ts_to_sec(bt) if bt else None, "model": d.get("model")})
        for key in ("title", "genre"):
            merged.setdefault(key, d.get(key))
        prev = (json.dumps([{"id": c.get("id"), "look": c.get("look")} for c in merged["characters"]][:12], ensure_ascii=False)
                if eps else " | ".join(f"part {c['part']}: {c['logline']}" for c in merged["chunks"])[-1500:])
        costs.append(d["_cost"])
    merged["logline"] = " ".join(c["logline"] or "" for c in merged["chunks"])
    merged["ending"] = merged["chunks"][-1]["ending"]
    best = max((s for s in merged["scenes"] if s.get("shot") not in ("title_card", "credits")),
               key=lambda s: s.get("dramatic_score") or 0, default=None)
    merged["best_thumbnail_time"] = merged["chunks"][len(merged["chunks"]) // 2]["best_thumbnail_s"] or (best or {}).get("start_s")
    merged["model"] = ",".join(sorted({c["model"] for c in merged["chunks"] if c.get("model")}))
    merged["duration"] = dur
    merged["_cost"] = {"item": f"scene analysis {n} parts ({merged['model']})", "usd": round(sum(c["usd"] for c in costs), 5),
                       "detail": "; ".join(c["detail"] for c in costs)}
    return merged

def _episodes(master: Path, dur: float):
    """Chapters saved by source.fetch (compilation episode list). Used as analysis/script parts when every chapter is
    a real episode (>= 120 s) and RECAP_EPISODES != 0."""
    f = master.parent / "chapters.json"
    if os.environ.get("RECAP_EPISODES", "1") == "0" or not f.exists():
        return None
    ch = [c for c in json.loads(f.read_text()) if c["start"] < dur - 5]
    if len(ch) < 2 or any(c["end"] - c["start"] < 120 for c in ch):
        return None
    return ch

def analyze(master: Path, prog, media_resolution=None):
    dur = probe_duration(master)
    if dur > CHUNK_SEC * 1.3 or (dur > 900 and _episodes(master, dur)):
        cache = master.parent / "analysis_chunked.json"
        if cache.exists():
            d = json.loads(cache.read_text())
            prog.add_cost(d["_cost"]["item"] + " [cached; first-run cost]", d["_cost"]["usd"], d["_cost"]["detail"])
            return d
        d = _analyze_chunked(master, prog, dur)
        # replace the per-part cost rows with one merged row (keeps totals right)
        prog.cost[:] = [c for c in prog.cost if not c["item"].startswith("scene analysis part")]
        prog.add_cost(d["_cost"]["item"], d["_cost"]["usd"], d["_cost"]["detail"])
        cache.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        return d
    cache = master.parent / "analysis.json"
    if cache.exists():
        prog(25, "ใช้ผลวิเคราะห์ฉากที่แคชไว้")
        d = json.loads(cache.read_text())
        c = d.get("_cost") or {"item": "scene analysis (gemini-3.5-flash)", "usd": 0.04484, "detail": "53863 in / 5969 out tokens"}
        prog.add_cost(c["item"] + " [cached; first-run cost]", c["usd"], c["detail"])
        return d
    proxy = master.parent / "proxy.mp4"
    dur = probe_duration(master)
    f = upload_video(proxy if proxy.exists() else master, prog)
    prog(15, "Gemini กำลังดูวิดีโอและแบ่งฉาก (1-3 นาที)")
    mr = media_resolution or (types.MediaResolution.MEDIA_RESOLUTION_LOW if dur > 1200 else None)
    data, model = generate_json([f, ANALYSIS_PROMPT.format(dur=dur, scene_rule="20-45 scenes, each 3-25 s")], prog,
                                "scene analysis", temperature=0.3, media_resolution=mr)
    if isinstance(data, list):   # some models return the bare scene list
        data = {"scenes": data} if data and "start" in data[0] else (data[0] if data else {})
    if not data.get("scenes"):
        raise RuntimeError("scene analysis returned no scenes")
    for s in data.get("scenes", []):
        s["start_s"] = min(ts_to_sec(s.get("start", 0)), dur)
        s["end_s"] = min(max(ts_to_sec(s.get("end", 0)), s["start_s"] + 0.5), dur)
    data["model"] = model; data["duration"] = dur; data["_cost"] = prog.cost[-1]
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data

LONG_SCRIPT_PROMPT = """คุณคือนักเขียนบทช่อง "สปอยล์หนัง/เล่าหนัง" ภาษาไทยบน YouTube ที่คนดูจนจบคลิปยาว ๆ
งาน: เขียนบทพากย์สปอยล์หนังเรื่องนี้แบบเต็มเรื่องตั้งแต่ต้นจนจบ ยาวประมาณ {target:.0f} วินาที ({mins:.0f} นาที)
รวมประมาณ {chars} ตัวอักษรไทย แบ่งเป็นประมาณ {nlines} บรรทัด บรรทัดละ 30-75 ตัวอักษร

ข้อมูลฉากจากวิดีโอ (เวลาเป็นวินาทีของวิดีโอต้นฉบับ ความยาวรวม {dur:.0f} วินาที){source_note}:
{scenes}

โครงเรื่องที่ต้องการ (ใส่ชื่อบทในช่อง chapter ของทุกบรรทัด):
1. "hook" 2-4 บรรทัดแรก: ดึงฉากที่ช็อกหรือยิ่งใหญ่ที่สุดมาเปิด แล้วตัดกลับไปเล่าตั้งแต่ต้น เช่น "แต่ก่อนจะไปถึงจุดนั้น เราต้องย้อนกลับไป..."
2. แบ่งเนื้อเรื่องเป็น 4-6 บท ตั้งชื่อบทสั้น ๆ ภาษาไทยแบบช่องเล่าหนัง (ไม่เกิน 22 ตัวอักษร) เช่น "จุดเริ่มต้นของหายนะ" เรียงตามเวลาของเรื่อง
3. บทสุดท้ายคือไคลแมกซ์และตอนจบ เล่าบทสรุปของตัวละครหลักให้ครบ แล้วปิดด้วยประโยคเท่ ๆ หรือฮา ๆ 1-2 บรรทัด

สไตล์:
- ภาษาพูดแบบคนไทยเล่าหนังให้เพื่อนฟัง สนุก มีจังหวะ ใส่มุกเบา ๆ ได้ ไม่ใช้ "ครับ/ค่ะ" ใช้ปัจจุบันกาล บุรุษที่สาม
- ใช้ชื่อจริงของตัวละครในหนัง เขียนทับศัพท์เป็นภาษาไทยแบบที่คนไทยเรียก ถ้าไม่รู้ชื่อให้ตั้งฉายาตามที่เห็น
- เล่าเหตุ-ผลให้คนที่ยังไม่เคยดูเข้าใจ: ใครเป็นใคร ต้องการอะไร ทำไมสถานการณ์ถึงคับขัน เขาแก้เกมยังไง
- เล่าแค่สิ่งที่มีในข้อมูลฉาก ห้ามแต่งเหตุการณ์ใหม่ ถ้าข้อมูลมีช่องว่างระหว่างฉาก ให้เชื่อมแบบกว้าง ๆ โดยไม่ลงรายละเอียดที่ไม่มีในฉาก
- ถ้าฉากเดียวกันถูกบรรยายซ้ำหลายครั้ง (มาจากคลิปคนละตัว) ให้เล่าเหตุการณ์นั้นแค่ครั้งเดียว
- เขียนตัวเลขเป็นคำไทย ใช้ไม้ยมก (ๆ) ได้ ห้ามอีโมจิ ห้ามวงเล็บหรือเครื่องหมายคำพูด
- ห้ามใช้ภาพจาก title card, โลโก้, end card หรือ credits

ภาพประกอบ (สำคัญมากสำหรับคลิปยาว ให้คนดูไม่เบื่อ):
- แต่ละบรรทัดเลือกช่วงภาพ src_start-src_end ยาว 3-7 วินาที ที่ตรงกับสิ่งที่บรรทัดนั้นพูดถึง
- ห้ามใช้ช่วงภาพซ้ำหรือทับกันเด็ดขาด ไล่ใช้ภาพไปตามเรื่อง กระจายให้ทั่วทั้งวิดีโอ
- ผสม video และ still (still ประมาณ 15-25% ใช้กับหน้าตัวละครหรือภาพสวย) ใส่ emphasis=true กับจังหวะช็อก/หักมุมประมาณ 10-15%

ตอบเป็น JSON เท่านั้น:
{{
 "title_th": "ชื่อคลิปภาษาไทย สั้น ดึงดูด ไม่เกิน 26 ตัวอักษร",
 "title_th_line2": "บรรทัดรอง ไม่เกิน 22 ตัวอักษร",
 "chapters": ["ชื่อบท", ...],
 "lines": [{{"chapter": "ชื่อบท", "text": "...", "src_start": ตัวเลข, "src_end": ตัวเลข, "visual": "video" หรือ "still",
            "emphasis": true/false, "keyword": "คำสำคัญ 1 คำที่อยู่ใน text"}}],
 "caption": "แคปชันภาษาไทย 1-2 ประโยค",
 "hashtags": ["#สปอยล์หนัง", ...]
}}"""

BRIEF_BLOCK = """

โจทย์พิเศษจากผู้สั่งงาน (สำคัญกว่ากฎสไตล์ด้านบน ถ้าขัดกันให้ทำตามข้อนี้):
{brief}"""

def write_script(analysis, target_sec, cps, visual_mode, prog, cache_dir: Path, brief: str = ""):
    from .util import sha as _sha
    key = f"script_{int(target_sec)}_{visual_mode}_{cps:.1f}" + (f"_{_sha(brief, 8)}" if brief else "") + ".json"
    cache = cache_dir / key
    if cache.exists():
        prog(32, "ใช้บทพากย์ที่แคชไว้")
        d = json.loads(cache.read_text())
        if d.get("_cost"):
            c = d["_cost"]; prog.add_cost(c["item"] + " [cached; first-run cost]", c["usd"], c["detail"])
        else:
            prog.add_cost("thai script [cached; cost not recorded, est.]", 0.012, "~7k in / ~2.5k out tokens (estimate)")
        return d
    dur = analysis["duration"]
    scenes = [{"t": f"{s['start_s']:.0f}-{s['end_s']:.0f}", "what": s["description"], "emo": s.get("emotion"),
               "drama": s.get("dramatic_score"), "shot": s.get("shot"), "beat": s.get("story_beat")}
              for s in analysis["scenes"]]
    ctx = {"title": analysis.get("title"), "logline": analysis.get("logline"),
           "characters": analysis.get("characters"), "ending": analysis.get("ending"), "scenes": scenes}
    chars = int(target_sec * cps)
    if target_sec >= 240 and analysis.get("chunks") and os.environ.get("RECAP_LONG_ONECALL") != "1":
        data = _write_long_by_parts(analysis, target_sec, cps, prog, brief, cache_dir, key[:-5])
        dedupe_visuals(data["lines"], analysis["scenes"], dur)
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        return data
    if target_sec >= 240:
        nlines = round(target_sec / 4.6)
        note = (" วิดีโอนี้เป็นคลิปทางการหลายตัวต่อกันตามลำดับเรื่อง อาจมีบางช่วงของหนังที่ไม่มีภาพ"
                if analysis.get("compilation") else "")
        prompt = LONG_SCRIPT_PROMPT.format(target=target_sec, mins=target_sec / 60, chars=chars, nlines=nlines, dur=dur,
                                           scenes=json.dumps(ctx, ensure_ascii=False), source_note=note)
    else:
        nlines = max(6, round(target_sec / 3.6))
        prompt = SCRIPT_PROMPT.format(target=target_sec, chars=chars, nlines=nlines, dur=dur,
                                      scenes=json.dumps(ctx, ensure_ascii=False), visual_hint=VISUAL_HINTS.get(visual_mode, ""))
    if brief:
        prompt += BRIEF_BLOCK.format(brief=brief)
    prog(25, "Gemini กำลังเขียนบทพากย์ไทยสไตล์ช่องเล่าหนัง")
    data, model = generate_json([prompt], prog, "thai script", temperature=0.9)
    if isinstance(data, list):
        data = {"lines": data} if data and "text" in data[0] else (data[0] if data else {})
    lines = []
    for ln in data.get("lines", []):
        t = (ln.get("text") or "").strip()
        if not t:
            continue
        s = max(0.0, min(ts_to_sec(ln.get("src_start", 0)), dur - 1))
        e = max(s + 1.0, min(ts_to_sec(ln.get("src_end", s + 4)), dur))
        kw = (ln.get("keyword") or "").strip()
        lines.append({"text": t, "src_start": s, "src_end": e, "chapter": (ln.get("chapter") or "").strip(),
                      "visual": "still" if ln.get("visual") == "still" else "video",
                      "emphasis": bool(ln.get("emphasis")), "keyword": kw if kw and kw in t else ""})
    dedupe_visuals(lines, analysis["scenes"], dur)
    data["lines"] = lines; data["model"] = model; data["_cost"] = prog.cost[-1]
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


PART_PROMPT = """คุณคือนักเขียนบทช่อง "สปอยล์หนัง/เล่าหนัง" ภาษาไทยบน YouTube ที่คนดูจนจบคลิปยาว ๆ
เรากำลังเขียนบทสปอยล์หนังเต็มเรื่องยาวประมาณ {mins:.0f} นาที โดยเขียนทีละช่วงของวิดีโอ ตอนนี้คือช่วงที่ {k} จาก {n}

ภาพรวมทั้งเรื่อง (ทุกช่วง): {overview}
ตัวละคร: {chars}
บทที่เขียนไปแล้ว {done} บรรทัด บรรทัดล่าสุดคือ:
{last}

ฉากของช่วงนี้ (เวลาเป็นวินาทีของวิดีโอทั้งไฟล์):
{scenes}
{extra}
งาน: เขียนบทพากย์ต่อสำหรับช่วงนี้ประมาณ {nlines} บรรทัด (บรรทัดละ 30-75 ตัวอักษร รวมประมาณ {chars_n} ตัวอักษร)
เล่าต่อจากบรรทัดล่าสุดให้ลื่นไหล ไม่ทวนสิ่งที่เล่าไปแล้ว ตั้งชื่อบท (chapter) 1-2 บทสำหรับช่วงนี้ ชื่อสั้นไม่เกิน 22 ตัวอักษร{end_rule}

สไตล์: ภาษาพูดแบบคนไทยเล่าหนังให้เพื่อนฟัง สนุก มีจังหวะ ใส่มุกเบา ๆ ได้ ไม่ใช้ครับ/ค่ะ ใช้ปัจจุบันกาล บุรุษที่สาม
ใช้ชื่อจริงของตัวละครทับศัพท์เป็นไทย เล่าเหตุ-ผลให้คนที่ไม่เคยดูเข้าใจ เล่าแค่สิ่งที่มีในข้อมูลฉากหรือโจทย์พิเศษ ห้ามแต่งเพิ่ม
ถ้าเหตุการณ์ในช่วงนี้ซ้ำกับที่เล่าไปแล้ว (คลิปคนละตัวตัดจากฉากเดียวกัน) ให้ข้าม หรือเล่ารายละเอียดใหม่ที่ยังไม่ได้เล่า และเขียนบรรทัดให้น้อยลงได้
เขียนตัวเลขเป็นคำไทย ใช้ไม้ยมก (ๆ) ได้ ห้ามอีโมจิ ห้ามวงเล็บหรือเครื่องหมายคำพูด
ภาพประกอบ: แต่ละบรรทัดเลือก src_start-src_end ยาว 3-7 วินาที จากฉากของช่วงนี้ ที่ตรงกับสิ่งที่พูด ห้ามใช้ช่วงซ้ำหรือทับกัน
กระจายให้ทั่วช่วง ห้ามใช้ title card/โลโก้/end card/credits ผสม still ประมาณ 20% และ emphasis=true กับจังหวะช็อกประมาณ 10-15%

ตอบเป็น JSON เท่านั้น:
{{{head}"lines": [{{"chapter": "ชื่อบท", "text": "...", "src_start": ตัวเลข, "src_end": ตัวเลข, "visual": "video" หรือ "still",
  "emphasis": true/false, "keyword": "คำสำคัญ 1 คำที่อยู่ใน text"}}]}}"""

HEAD_FIELDS = ('"title_th": "ชื่อคลิปภาษาไทย ไม่เกิน 26 ตัวอักษร", "title_th_line2": "บรรทัดรอง ไม่เกิน 22 ตัวอักษร", '
               '"caption": "แคปชันภาษาไทย 1-2 ประโยค", "hashtags": ["#สปอยล์หนัง", ...], ')

def _write_long_by_parts(analysis, target_sec, cps, prog, brief, cache_dir=None, tag=""):
    """Chaptered long-form script, written part by part (one call per analysis chunk). Smaller outputs per call keep
    weaker/fallback models on track and avoid one huge 150-line JSON answer."""
    chunks = analysis["chunks"]; n = len(chunks); dur = analysis["duration"]
    overview = " | ".join(f"ช่วง {c['part']}: {c['logline']}" for c in chunks)
    chars = json.dumps([{"id": c.get("id"), "role": c.get("role")} for c in analysis.get("characters", [])][:25], ensure_ascii=False)
    usable = [s for s in analysis["scenes"] if s.get("shot") not in ("title_card", "credits")]
    hooks = sorted(usable, key=lambda s: -(s.get("dramatic_score") or 0))[:6]
    out = {"lines": [], "chapters": []}; costs = []; models = set()
    for k in range(n):
        sc = [{"t": f"{s['start_s']:.0f}-{s['end_s']:.0f}", "what": s["description"], "drama": s.get("dramatic_score"),
               "shot": s.get("shot")} for s in analysis["scenes"] if s.get("part") == k + 1]
        share = target_sec * (chunks[k].get("duration") or dur / n) / dur
        nl = max(8, round(share / 4.6))
        extra = ""
        ep = chunks[k].get("episode_title")
        if ep:
            extra += (f"\nช่วงนี้คือตอนที่ {k+1} จาก {n} ของคลิปรวมตอน ชื่อตอนต้นฉบับ: {ep} แต่ละตอนเป็นเรื่องจบในตอน"
                      " ให้ทุกบรรทัดของช่วงนี้ (ยกเว้น hook) ใช้ chapter เดียวกัน เป็นชื่อตอนภาษาไทยสนุก ๆ ที่สื่อถึงตอนนี้"
                      " เปิดตอนด้วยบรรทัดแนะนำว่าตอนนี้เกิดอะไรขึ้น (ถ้าไม่ใช่ตอนแรก ให้เชื่อมแบบ ตอนต่อไป... ) แล้วเล่าให้จบตอน"
                      " ปิดตอนด้วยมุกหรือหมัดเด็ด 1 บรรทัด\n")
        if k == 0:
            extra = ("\nเริ่มด้วย hook 2-3 บรรทัด (chapter = hook) ที่ดึงฉากยิ่งใหญ่ที่สุดของเรื่องมาเปิด ใช้ภาพจากฉากเหล่านี้ได้: "
                     + json.dumps([{"t": f"{h['start_s']:.0f}-{h['end_s']:.0f}", "what": h["description"]} for h in hooks], ensure_ascii=False)
                     + " แล้วตัดกลับมาเล่าตั้งแต่ต้นเรื่อง\n")
        if brief:
            extra += "\nโจทย์พิเศษ (สำคัญ):\n" + brief + "\n"
        end_rule = ("\nนี่คือช่วงสุดท้าย: เล่าไคลแมกซ์และตอนจบให้ครบ สรุปชะตาตัวละครหลัก แล้วปิดด้วยประโยคเท่ ๆ หรือฮา ๆ 1-2 บรรทัด"
                    if k == n - 1 else ("\nนี่ยังไม่ใช่ตอนสุดท้ายของคลิปรวม เล่าตอนนี้ให้จบตอน แต่ห้ามกล่าวลาหรือสรุปปิดทั้งคลิป" if ep
                                        else "\nยังไม่ใช่ตอนจบ ห้ามสรุปปิดเรื่อง"))
        last = "\n".join(l["text"] for l in out["lines"][-6:]) or "(ยังไม่มี นี่คือช่วงแรก)"
        prompt = PART_PROMPT.format(mins=target_sec / 60, k=k + 1, n=n, overview=overview, chars=chars, done=len(out["lines"]),
                                    last=last, scenes=json.dumps(sc, ensure_ascii=False), extra=extra, nlines=nl,
                                    chars_n=int(share * cps), end_rule=end_rule, head=HEAD_FIELDS if k == 0 else "")
        pc = (cache_dir / f"{tag}_part{k+1}of{n}.json") if cache_dir else None
        if pc and pc.exists():
            d = json.loads(pc.read_text()); model = d["_model"]; c = d["_cost"]
            prog.add_cost(c["item"], c["usd"], c["detail"])
        else:
            prog(25 + 7 * k / n, f"Gemini เขียนบทพากย์ช่วง {k+1}/{n}")
            d, model = generate_json([prompt], prog, f"thai script part {k+1}/{n}", temperature=0.85)
            if isinstance(d, list):
                d = {"lines": d}
            if pc:
                pc.write_text(json.dumps({**d, "_model": model, "_cost": prog.cost[-1]}, ensure_ascii=False, indent=1))
        models.add(model); costs.append(prog.cost[-1])
        if k == 0:
            for key in ("title_th", "title_th_line2", "caption", "hashtags"):
                out[key] = d.get(key)
        lo = min((s["start_s"] for s in analysis["scenes"] if s.get("part") == k + 1), default=0)
        hi = max((s["end_s"] for s in analysis["scenes"] if s.get("part") == k + 1), default=dur)
        for ln in d.get("lines", []):
            t = (ln.get("text") or "").strip()
            if not t:
                continue
            s_ = max(0.0, min(ts_to_sec(ln.get("src_start", lo)), dur - 1))
            if not (ln.get("chapter") == "hook" or lo - 1 <= s_ <= hi):
                s_ = lo   # out-of-range pick: dedupe_visuals moves it to free footage of this part
            e_ = max(s_ + 1.0, min(ts_to_sec(ln.get("src_end", s_ + 4)), s_ + 8, dur))
            kw = (ln.get("keyword") or "").strip()
            ch = (ln.get("chapter") or "").strip()
            out["lines"].append({"text": t, "src_start": s_, "src_end": e_, "chapter": ch,
                                 "visual": "still" if ln.get("visual") == "still" else "video",
                                 "emphasis": bool(ln.get("emphasis")), "keyword": kw if kw and kw in t else ""})
            if ch and ch not in out["chapters"]:
                out["chapters"].append(ch)
    out["model"] = ",".join(sorted(models))
    out["_cost"] = {"item": f"thai script {n} parts ({out['model']})", "usd": round(sum(c["usd"] for c in costs), 5),
                    "detail": "; ".join(c["detail"] for c in costs)}
    prog.cost[:] = [c for c in prog.cost if not c["item"].startswith("thai script part")]
    prog.add_cost(out["_cost"]["item"], out["_cost"]["usd"], out["_cost"]["detail"])
    return out

def _ov(a, b, used):
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in used)

def dedupe_visuals(lines, scenes, dur):
    """Long scripts tend to reuse the same shot. Slide a reused window to the nearest unused footage in the same
    or neighbouring scenes (never onto title cards/credits)."""
    ok = [s for s in scenes if s.get("shot") not in ("title_card", "credits")]
    used = []; moved = 0
    for ln in lines:
        s, e = ln["src_start"], ln["src_end"]; L = e - s
        if _ov(s, e, used) > 0.25 * L:
            idx = min(range(len(ok)), key=lambda i: 0 if ok[i]["start_s"] <= s < ok[i]["end_s"] else
                      min(abs(ok[i]["start_s"] - s), abs(ok[i]["end_s"] - s))) if ok else None
            best = None
            if idx is not None:
                for j in sorted(range(max(0, idx - 3), min(len(ok), idx + 4)), key=lambda j: abs(j - idx)):
                    sc = ok[j]; a0 = sc["start_s"]; a1 = max(a0, sc["end_s"] - L)
                    t = a0
                    while t <= a1 + 1e-6:
                        o = _ov(t, t + L, used)
                        if o <= 0.1 * L and (best is None or abs(t - s) < abs(best - s)):
                            best = t
                        t += 0.5
                    if best is not None:
                        break
            if best is not None:
                ln["src_start"], ln["src_end"] = round(best, 2), round(min(dur, best + L), 2); moved += 1
        used.append((ln["src_start"], ln["src_end"]))
    return moved
