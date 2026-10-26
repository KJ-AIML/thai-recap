import argparse, json
from .pipeline import Options, run

def main():
    ap = argparse.ArgumentParser(description="Thai recap clip generator / สร้างคลิปเล่าเรื่องพากย์ไทย")
    ap.add_argument("src", help="video URL or local file")
    ap.add_argument("--length", type=int, default=75)
    ap.add_argument("--gender", choices=["male", "female"], default="male")
    ap.add_argument("--speed", type=float, default=1.15)
    ap.add_argument("--aspect", choices=["9:16", "16:9", "both"], default="9:16")
    ap.add_argument("--visual", choices=["video", "mixed", "image"], default="mixed")
    ap.add_argument("--tts", choices=["gemini", "edge", "elevenlabs", "google"], default="gemini")
    ap.add_argument("--bgm", default="auto", help="auto | none | path")
    ap.add_argument("--bgm-level", type=float, default=0.16)
    ap.add_argument("--credit", default="")
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    r = run(Options(src=a.src, length=a.length, gender=a.gender, speed=a.speed, aspect=a.aspect, visual=a.visual,
                    tts=a.tts, bgm=a.bgm, bgm_level=a.bgm_level, credit=a.credit, name=a.name))
    r.pop("log", None)
    print(json.dumps({k: r[k] for k in ("videos", "thumbnails", "duration", "tts_provider", "voice", "analysis_model",
                                        "cost_usd_paid_tier_est", "cost_thb_est", "elapsed_s")}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
