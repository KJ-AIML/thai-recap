import json, subprocess, hashlib, time, re
from pathlib import Path

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(map(str, cmd))[:400]}\n{r.stderr[-2000:]}")
    return r.stdout

def probe_duration(path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())

def probe_video(path):
    out = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate", "-show_entries", "format=duration", "-of", "json", str(path)]))
    s = out["streams"][0]
    return int(s["width"]), int(s["height"]), float(out["format"]["duration"])

def sha(s: str, n=12):
    return hashlib.sha1(s.encode()).hexdigest()[:n]

def file_sha(path, n=12):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]

def ts_to_sec(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    parts = v.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return 0.0

def sec_to_ass(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:])

class Progress:
    """Collects progress + cost; callback(pct, msg) for the UI."""
    def __init__(self, cb=None):
        self.cb = cb; self.log = []; self.cost = []
    def __call__(self, pct, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {pct:3.0f}% {msg}"
        self.log.append(line); print(line, flush=True)
        if self.cb:
            self.cb(pct, msg)
    def add_cost(self, item, usd, detail):
        self.cost.append({"item": item, "usd": round(usd, 5), "detail": detail})
