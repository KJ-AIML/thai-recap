"""Gemini calls with model fallback, retries and token accounting."""
import time, json, os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
_POOL = ThreadPoolExecutor(4)
HARD_TIMEOUT = int(os.environ.get("RECAP_LLM_TIMEOUT", "200"))
from pathlib import Path
from google import genai
from google.genai import types
from .config import gemini_key, ANALYSIS_MODELS, PRICES, WORK
from .util import extract_json

_client = None
def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=gemini_key(), http_options=types.HttpOptions(timeout=240_000, retry_options=types.HttpRetryOptions(attempts=1)))
    return _client

def upload_video(path: Path, prog):
    """Upload via File API (cached by path for 40h, matching Gemini's 48h retention)."""
    cache = path.with_suffix(".gemini_file.json")
    if cache.exists():
        info = json.loads(cache.read_text())
        if time.time() - info["t"] < 40 * 3600:
            try:
                f = client().files.get(name=info["name"])
                if f.state.name == "ACTIVE":
                    return f
            except Exception:
                pass
    prog(12, "อัปโหลดวิดีโอเข้า Gemini File API")
    f = client().files.upload(file=str(path), config={"mime_type": "video/mp4"})
    while f.state.name == "PROCESSING":
        time.sleep(4); f = client().files.get(name=f.name)
    if f.state.name != "ACTIVE":
        raise RuntimeError(f"Gemini file processing failed: {f.state}")
    cache.write_text(json.dumps({"name": f.name, "t": time.time()}))
    return f

def _skip_model(err: str) -> bool:
    e = err.lower()
    return ("limit: 0" in e or "no longer available" in e or "not found" in e or "404" in e
            or "permission" in e or "free_tier" in e and "429" in e)

HEALTH = WORK / "model_health.json"

def _bad_models():
    try:
        d = json.loads(HEALTH.read_text())
        return {m for m, t in d.items() if time.time() - t < 3600}
    except Exception:
        return set()

def _mark_bad(model):
    try:
        d = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
    except Exception:
        d = {}
    d[model] = time.time(); HEALTH.write_text(json.dumps(d))

def generate_json(parts, prog, label, models=None, temperature=0.7, media_resolution=None, thinking=True):
    models = models or ANALYSIS_MODELS
    bad = _bad_models()
    models = [m for m in models if m not in bad] + [m for m in models if m in bad]
    last = None
    for model in models:
        for attempt in range(int(os.environ.get("RECAP_LLM_ATTEMPTS", "2"))):
            try:
                cfg = dict(response_mime_type="application/json", temperature=temperature)
                if media_resolution:
                    cfg["media_resolution"] = media_resolution
                t0 = time.time()
                fut = _POOL.submit(client().models.generate_content, model=model, contents=parts,
                                   config=types.GenerateContentConfig(**cfg))
                try:
                    r = fut.result(timeout=HARD_TIMEOUT)
                except FutTimeout:
                    raise TimeoutError(f"hard timeout {HARD_TIMEOUT}s")
                data = extract_json(r.text)
                u = r.usage_metadata
                pin, pout = PRICES.get(model, (0.5, 3.0))
                tin = u.prompt_token_count or 0
                tout = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
                usd = tin / 1e6 * pin + tout / 1e6 * pout
                prog.add_cost(f"{label} ({model})", usd, f"{tin} in / {tout} out tokens, {time.time()-t0:.0f}s")
                return data, model
            except Exception as ex:
                last = ex; msg = str(ex)
                if _skip_model(msg):
                    print(f"  {model} unavailable: {msg[:160]}", flush=True); _mark_bad(model)
                    break
                if "timed out" in msg.lower() or "timeout" in msg.lower():
                    print(f"  {model} timed out -> next model", flush=True); _mark_bad(model)
                    break
                wait = min(60, 8 * (attempt + 1))
                print(f"  {model} attempt {attempt+1} failed: {msg[:160]} -> retry in {wait}s", flush=True)
                time.sleep(wait)
    raise RuntimeError(f"All Gemini models failed for {label}: {last}")
