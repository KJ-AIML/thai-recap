"""Local web UI: http://127.0.0.1:8000"""
import threading, uuid, shutil, traceback, time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import OUTPUT, WORK, ROOT
from .pipeline import Options, run

app = FastAPI(title="Thai Recap")
app.mount("/output", StaticFiles(directory=str(OUTPUT)), name="output")
JOBS = {}
LOCK = threading.Lock()   # one render at a time (CPU + API rate limits)

def _worker(jid, opt):
    j = JOBS[jid]
    def cb(pct, msg):
        j["pct"] = pct; j["msg"] = msg; j["log"].append(f"{time.strftime('%H:%M:%S')} {pct:.0f}% {msg}")
    with LOCK:
        j["state"] = "running"
        try:
            r = run(opt, cb)
            r.pop("log", None)
            j.update(state="done", pct=100, result=r)
        except Exception as ex:
            traceback.print_exc()
            j.update(state="error", msg=str(ex)[:600])

@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "recap" / "static" / "index.html").read_text(encoding="utf-8")

@app.post("/api/jobs")
async def create(url: str = Form(""), file: UploadFile | None = File(None), length: int = Form(75),
                 gender: str = Form("male"), speed: float = Form(1.15), aspect: str = Form("9:16"),
                 visual: str = Form("mixed"), tts: str = Form("gemini"), bgm: str = Form("auto"), credit: str = Form("")):
    src = url.strip()
    if file is not None and file.filename:
        up = WORK / "uploads"; up.mkdir(parents=True, exist_ok=True)
        dst = up / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
        with open(dst, "wb") as f:
            shutil.copyfileobj(file.file, f)
        src = str(dst)
    if not src:
        raise HTTPException(400, "ใส่ลิงก์หรืออัปโหลดไฟล์ก่อน")
    opt = Options(src=src, length=max(20, min(600, length)), gender=gender, speed=max(0.8, min(1.5, speed)),
                  aspect=aspect, visual=visual, tts=tts, bgm=bgm, credit=credit.strip())
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"id": jid, "state": "queued", "pct": 0, "msg": "รอคิว", "log": [], "src": src}
    threading.Thread(target=_worker, args=(jid, opt), daemon=True).start()
    return {"id": jid}

@app.get("/api/jobs/{jid}")
def status(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404)
    out = dict(j); out["log"] = j["log"][-14:]
    if j.get("result"):
        r = j["result"]
        out["urls"] = {"videos": {a: "/output/" + Path(p).name for a, p in r["videos"].items()},
                       "thumbnails": {a: "/output/" + Path(p).name for a, p in r["thumbnails"].items()}}
    return JSONResponse(out)
