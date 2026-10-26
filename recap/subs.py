"""Thai subtitles: PyThaiNLP word segmentation -> short punchy chunks -> styled .ass (recap look)."""
import unicodedata
from pythainlp.tokenize import word_tokenize
from .util import sec_to_ass

def vis_len(s: str) -> int:
    """Visible width: Thai combining marks (vowels above/below, tone marks) take no width."""
    return sum(1 for c in s if unicodedata.category(c) not in ("Mn", "Me", "Cf") and c != " ")

def chunk_line(text: str, max_w: int):
    toks = [t for t in word_tokenize(text, engine="newmm", keep_whitespace=True)]
    chunks, cur = [], []
    for t in toks:
        if t.isspace():
            if cur and vis_len("".join(cur)) >= max_w * 0.55:
                chunks.append(cur); cur = []
            elif cur:
                cur.append(" ")
            continue
        if cur and vis_len("".join(cur) + t) > max_w and not (vis_len(t) <= 3 and vis_len("".join(cur) + t) <= max_w + 3):
            chunks.append(cur); cur = []
        cur.append(t)
    if cur:
        chunks.append(cur)
    # merge a tiny trailing chunk into previous one
    if len(chunks) > 1 and vis_len("".join(chunks[-1])) <= 3:
        chunks[-2] += chunks.pop()
    return ["".join(c).strip() for c in chunks if "".join(c).strip()]

def _esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")

def _highlight(chunk: str, kw: str, color="&H0000E5FF&"):
    if kw and kw in chunk:
        i = chunk.index(kw)
        return _esc(chunk[:i]) + "{\\c" + color + "}" + _esc(kw) + "{\\c&HFFFFFF&}" + _esc(chunk[i + len(kw):])
    return _esc(chunk)

def build_ass(lines, aspect, total_dur, title="", title2="", credit="", font="Kanit"):
    if aspect == "9:16":
        W, H, size, max_w, sub_y, title_on = 1080, 1920, 104, 13, 1470, True
    else:
        W, H, size, max_w, sub_y, title_on = 1920, 1080, 76, 26, 960, False
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font} ExtraBold,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,7,3,5,40,40,0,222
Style: Title,{font} Black,{118 if aspect=='9:16' else 84},&H0000E5FF,&H0000E5FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,8,4,5,40,40,0,222
Style: Title2,{font} ExtraBold,{72 if aspect=='9:16' else 54},&H00FFFFFF,&H00FFFFFF,&H000000C8,&H96000000,0,0,0,0,100,100,0,0,3,14,0,5,40,40,0,222
Style: Chapter,{font} ExtraBold,58,&H00FFFFFF,&H00FFFFFF,&H000000C8,&H96000000,0,0,0,0,100,100,0,0,3,16,0,7,40,40,0,222
Style: Credit,{font} Bold,{30 if aspect=='9:16' else 26},&H90FFFFFF,&H90FFFFFF,&H90000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,{40 if aspect=='9:16' else 18},222

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if title and title_on:
        ev.append(f"Dialogue: 2,{sec_to_ass(0)},{sec_to_ass(total_dur)},Title,,0,0,0,,{{\\pos({W//2},{320})}}{_esc(title)}")
        if title2:
            ev.append(f"Dialogue: 2,{sec_to_ass(0)},{sec_to_ass(total_dur)},Title2,,0,0,0,,{{\\pos({W//2},{465})}}{_esc(title2)}")
    elif title:
        ev.append(f"Dialogue: 2,{sec_to_ass(0)},{sec_to_ass(min(3.5,total_dur))},Title,,0,0,0,,{{\\pos({W//2},{150})\\fad(150,300)}}{_esc(title)}")
    if credit:
        ev.append(f"Dialogue: 1,{sec_to_ass(0)},{sec_to_ass(total_dur)},Credit,,0,0,0,,{_esc(credit)}")
    prev_ch = None
    for ln in lines:
        ch = ln.get("chapter") or ""
        if ch and ch != prev_ch and ch.lower() != "hook" and not title_on:
            # chapter card (long-form 16:9): red tag top-left for 3.2 s
            ev.append(f"Dialogue: 2,{sec_to_ass(ln['t0'])},{sec_to_ass(ln['t0'] + 3.2)},Chapter,,0,0,0,,"
                      f"{{\\an7\\pos(60,50)\\fad(200,300)}}{_esc(ch)}")
        prev_ch = ch
        chunks = chunk_line(ln["text"], max_w)
        weights = [max(1, vis_len(c)) for c in chunks]
        t = ln["t0"]; span = ln["dur"]
        for c, w in zip(chunks, weights):
            d = span * w / sum(weights)
            pop = "\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)" if not ln.get("emphasis") else "\\fscx130\\fscy130\\t(0,120,\\fscx100\\fscy100)"
            ev.append(f"Dialogue: 3,{sec_to_ass(t)},{sec_to_ass(t + d)},Sub,,0,0,0,,{{\\pos({W//2},{sub_y}){pop}}}{_highlight(c, ln.get('keyword',''))}")
            t += d
    return head + "\n".join(ev) + "\n"
