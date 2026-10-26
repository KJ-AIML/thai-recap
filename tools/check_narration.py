"""Transcribe N seconds (from an optional start offset) of a rendered clip with a Gemini model and print it next to the script (sanity check)."""
import sys, os, base64, json, subprocess, requests, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from recap.config import gemini_key
video, n = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 25
ss = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
model = os.environ.get("CHECK_MODEL", "gemini-3.1-flash-lite")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(ss), "-i", video, "-t", str(n), "-vn", "-ac", "1", "-ar", "16000", "/tmp/chk.wav"], check=True)
r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": gemini_key()},
                  timeout=120, json={"contents": [{"parts": [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(open("/tmp/chk.wav", "rb").read()).decode()}},
                                                             {"text": "Transcribe the Thai narration exactly, no commentary."}]}]})
d = r.json()
print("HEARD :", d["candidates"][0]["content"]["parts"][-1]["text"].strip() if "candidates" in d else d.get("error", {}).get("message", "")[:200])
j = video.rsplit("_", 1)[0] + ".json"
if os.path.exists(j):
    lines = json.load(open(j))["lines"]
    print("SCRIPT:", " ".join(l["text"] for l in lines if ss - 0.5 <= l["t0"] < ss + n))
