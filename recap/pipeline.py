"""End-to-end orchestration."""
import json, time, re, shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path
from .config import WORK, OUTPUT, USD_THB, MUSIC
from .util import Progress, sha, probe_duration
from . import source, analyze, tts, subs, render, thumbnail

@dataclass
class Options:
    src: str                      # URL or local file path
    length: int = 75              # target seconds
    gender: str = "male"          # male | female
    speed: float = 1.15           # narration tempo
    aspect: str = "9:16"          # 9:16 | 16:9 | both
    visual: str = "mixed"         # video | mixed | image
    tts: str = "gemini"           # gemini | edge | elevenlabs | google
    bgm: str = "auto"             # auto | none | path to audio file
    bgm_level: float = 0.16
    credit: str = ""              # attribution line burned in small text (needed for CC-BY sources)
    name: str = ""
    brief: str = ""               # extra creative brief / allowed facts for the script (e.g. a website "movie recap")

CPS = 12.5  # Thai chars per second spoken by Gemini TTS at 1.0x (measured ~12.3)

def run(opt: Options, cb=None):
    prog = Progress(cb); t0 = time.time()
    master = source.fetch(opt.src, prog)
    srcdir = master.parent
    an = analyze.analyze(master, prog)
    prog(24, f"แบ่งได้ {len(an['scenes'])} ฉาก ด้วย {an['model']}")
    script = analyze.write_script(an, opt.length, CPS * opt.speed, opt.visual, prog, srcdir, opt.brief)
    lines = [dict(l) for l in script["lines"]]
    if not lines:
        raise RuntimeError("Script came back empty")
    job = f"{time.strftime('%Y%m%d-%H%M%S')}_{opt.name or re.sub(r'[^A-Za-z0-9]+','-', an.get('title','recap'))[:30].strip('-').lower()}"
    jw = WORK / "jobs" / job; jw.mkdir(parents=True, exist_ok=True)
    prog(34, f"สังเคราะห์เสียงพากย์ {len(lines)} บรรทัด ({opt.tts}, {opt.gender})")
    prov, voice = tts.synthesize(lines, opt.tts, opt.gender, opt.speed, srcdir / "tts", prog)
    total = sum(l["dur"] for l in lines)
    # length control: if narration overshoots, speed up tempo-adjustable lines (gemini/elevenlabs) up to 1.4x
    if total > opt.length * 1.12:
        factor = min(1.4 / opt.speed, total / opt.length)
        prog(56, f"บทยาวไป {total:.0f}s → เร่งเสียงเป็น x{opt.speed*factor:.2f}")
        for ln in lines:
            if ln["tts"] in ("gemini", "elevenlabs", "edge"):
                raw = Path(ln["raw"]) if ln.get("raw") else tts._raw_path(srcdir / "tts", ln["tts"], ln["voice"], ln["text"], opt.speed)
                if raw.exists():
                    ln["dur"] = tts._post(raw, Path(ln["audio"]), opt.speed * factor)
    bgm = None
    if opt.bgm == "auto":
        m = sorted(MUSIC.glob("*.mp3")) + sorted(MUSIC.glob("*.wav")) + sorted(MUSIC.glob("*.m4a"))
        bgm = m[0] if m else None
    elif opt.bgm not in ("none", "", None):
        bgm = Path(opt.bgm)
    aspects = ["9:16", "16:9"] if opt.aspect == "both" else [opt.aspect]
    outs = {}
    for k, a in enumerate(aspects):
        ass_text = subs.build_ass(lines, a, render.plan(lines, an["duration"]), script.get("title_th", ""),
                                  script.get("title_th_line2", ""), opt.credit)
        out = OUTPUT / f"{job}_{a.replace(':','x')}.mp4"
        span = 35 / len(aspects)
        dur = render.render(lines, master, a, ass_text, jw, out, prog, bgm=bgm, bgm_level=opt.bgm_level,
                            p0=58 + k * span, p1=58 + (k + 1) * span)
        outs[a] = str(out)
    prog(94, "ทำภาพปก")
    frame, ft = thumbnail.pick_frame(master, an, jw)
    thumbs = {}
    for a in aspects:
        p = OUTPUT / f"{job}_thumb_{a.replace(':','x')}.jpg"
        thumbnail.make(frame, script.get("title_th", ""), script.get("title_th_line2", ""), p, a)
        thumbs[a] = str(p)
    usd = sum(c["usd"] for c in prog.cost)
    result = {
        "job": job, "videos": outs, "thumbnails": thumbs, "duration": round(dur, 2),
        "tts_provider": prov, "voice": voice, "analysis_model": an["model"], "script_model": script.get("model"),
        "title": script.get("title_th"), "title2": script.get("title_th_line2"),
        "caption": script.get("caption"), "hashtags": script.get("hashtags"),
        "lines": [{k: l.get(k) for k in ("chapter", "text", "src_start", "src_end", "visual", "emphasis", "keyword", "t0", "dur", "fit", "tts")} for l in lines],
        "cost": prog.cost, "cost_usd_paid_tier_est": round(usd, 4), "cost_thb_est": round(usd * USD_THB, 2),
        "thumbnail_time": round(ft, 2), "elapsed_s": round(time.time() - t0, 1), "options": asdict(opt),
    }
    (OUTPUT / f"{job}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    (OUTPUT / f"{job}_script.txt").write_text("\n".join(l["text"] for l in lines) + "\n\n" + (script.get("caption") or "")
                                              + "\n" + " ".join(script.get("hashtags") or []), encoding="utf-8")
    prog(100, f"เสร็จแล้ว {dur:.1f}s, ประมาณ ${usd:.3f} (~฿{usd*USD_THB:.1f}) ถ้าใช้คีย์แบบจ่ายเงิน")
    result["log"] = prog.log
    return result
