import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
FONTS = ROOT / "assets" / "fonts"
MUSIC = ROOT / "assets" / "music"
for p in (WORK, OUTPUT):
    p.mkdir(parents=True, exist_ok=True)

def gemini_key():
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_TTS_API_KEY_2"):
        if os.environ.get(k):
            return os.environ[k]
    raise RuntimeError("No Gemini API key in env (GEMINI_API_KEY / GEMINI_TTS_API_KEY_2)")

# Strongest first. Free-tier keys have 0 quota for Pro -> falls through to Flash.
ANALYSIS_MODELS = [m.strip() for m in os.environ.get(
    "RECAP_MODELS", "gemini-3.1-pro-preview,gemini-3.8-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-2.5-pro"
).split(",") if m.strip()]

# Rough list prices (USD per 1M tokens / per 1k chars). Free tier costs $0 but we still
# report what it *would* cost on a paid key. Edit as pricing changes.
PRICES = {
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-3.8-flash": (0.5, 3.0),
    "gemini-3.5-flash": (0.5, 3.0),
    "gemini-3-flash-preview": (0.5, 3.0),
    "tts-gemini": (0.5, 10.0),          # text in, audio out tokens
    "tts-elevenlabs_per_1k_chars": 0.15,
    "tts-google_per_1m_chars": 30.0,    # Chirp3-HD
    "tts-edge": 0.0,
}
USD_THB = 33.0
