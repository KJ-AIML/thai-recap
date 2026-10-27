"""Download (yt-dlp, <=720p) or accept a local file, then normalize to an editing-friendly H.264 master."""
import shutil
from pathlib import Path
from .util import run, sha, file_sha, probe_video
from .config import WORK

def save_chapters(url: str, d: Path):
    """YouTube chapters (e.g. episode list of a compilation) -> chapters.json; used to chunk long-form analysis."""
    import json
    try:
        info = json.loads(run(["yt-dlp", "--no-playlist", "-J", url], timeout=120))
        ch = [{"start": float(c["start_time"]), "end": float(c["end_time"]), "title": c.get("title") or ""}
              for c in (info.get("chapters") or [])]
    except Exception:
        ch = []
    (d / "chapters.json").write_text(json.dumps(ch, ensure_ascii=False, indent=1))

def fetch(url_or_path: str, prog) -> Path:
    p = Path(url_or_path)
    if p.exists():
        key = file_sha(p)
        d = WORK / "sources" / key; d.mkdir(parents=True, exist_ok=True)
        raw = d / ("raw" + p.suffix.lower())
        if not raw.exists():
            shutil.copy(p, raw)
    else:
        key = sha(url_or_path)
        d = WORK / "sources" / key; d.mkdir(parents=True, exist_ok=True)
        raws = list(d.glob("raw.*"))
        if raws:
            raw = raws[0]
        else:
            prog(3, "ดาวน์โหลดวิดีโอ (yt-dlp, ≤720p)")
            if url_or_path.lower().split("?")[0].endswith((".mp4", ".mov", ".mkv", ".webm")) and "youtube" not in url_or_path:
                run(["curl", "-sfL", "--max-time", "1800", "-o", str(d / "raw.mp4"), url_or_path])
            else:
                run(["yt-dlp", "--no-playlist", "-f",
                     "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]/b",
                     "--merge-output-format", "mp4", "-o", str(d / "raw.%(ext)s"), url_or_path], timeout=1800)
            raw = next(d.glob("raw.*"))
        if not (d / "chapters.json").exists() and "://" in url_or_path:
            save_chapters(url_or_path, d)
    master = d / "master.mp4"
    if not master.exists():
        prog(6, "แปลงไฟล์ต้นฉบับเป็น H.264 720p 30fps")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf",
             "scale='min(1280,iw)':-2,fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-g", "30", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000", str(master)])
    proxy = d / "proxy.mp4"
    if not proxy.exists():
        prog(9, "ทำไฟล์ proxy สำหรับส่งให้ Gemini")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-vf", "scale=-2:360",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "64k", "-ac", "1", str(proxy)])
    return master
