"""Step 2+3: Gemini watches the video -> scene list; then writes the Thai recap script."""
import json
from pathlib import Path
from google.genai import types
from .llm import upload_video, generate_json
from .util import ts_to_sec, probe_duration

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
Rules: cover the WHOLE video in order with 20-45 scenes, each 3-25 s, timestamps accurate to the second and non-overlapping.
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

def analyze(master: Path, prog, media_resolution=None):
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
    data, model = generate_json([f, ANALYSIS_PROMPT.format(dur=dur)], prog, "scene analysis", temperature=0.3, media_resolution=mr)
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
        lines.append({"text": t, "src_start": s, "src_end": e,
                      "visual": "still" if ln.get("visual") == "still" else "video",
                      "emphasis": bool(ln.get("emphasis")), "keyword": kw if kw and kw in t else ""})
    data["lines"] = lines; data["model"] = model; data["_cost"] = prog.cost[-1]
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data
