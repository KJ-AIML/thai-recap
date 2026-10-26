"""Timeline fitting + rendering with ffmpeg (blur-fill reframe, slow/punch zoom, Ken Burns stills, ASS burn-in, BGM ducking)."""
import wave, json, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .util import run, probe_video, probe_duration
from .config import FONTS

GAP = 0.10   # silence between narration lines
TAIL = 0.6   # hold at end

def canvas(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)

def plan(lines, src_dur):
    t = 0.0
    for i, ln in enumerate(lines):
        ln["t0"] = t
        seg = ln["dur"] + (GAP if i < len(lines) - 1 else TAIL)
        ln["seg_dur"] = seg
        t += seg
    return t

def _fg_box(aspect, sw, sh):
    """fg crop (source px) + fg size on canvas."""
    W, H = canvas(aspect)
    src_ar = sw / sh
    if aspect == "9:16" and src_ar < 1.0:
        # portrait source (phone screen recordings, mobile site captures): big 4:5-ish window under the title band
        ar = max(src_ar, 0.80)
        fw = W; fh = int(round(W / ar / 2) * 2); fh = min(fh, H - 560); y = 560
    elif aspect == "9:16":
        ar = max(min(src_ar, 1.6), 4 / 3)      # crop scope/16:9 films to 1.6:1 so the picture is bigger on a phone
        fw = W; fh = int(round(W / ar / 2) * 2)
        y = 580 + (760 - fh) // 2 if fh <= 760 else (H - fh) // 2
    else:
        ar = src_ar
        fw, fh = (W, int(round(W / ar / 2) * 2)) if ar >= W / H else (int(round(H * ar / 2) * 2), H)
        y = (H - fh) // 2
    cw = min(sw, int(sh * ar)); ch = min(sh, int(sw / ar))
    return cw, ch, fw, fh, y

def render_segment(i, ln, master, aspect, sw, sh, vdur, out: Path):
    W, H = canvas(aspect)
    d = ln["seg_dur"]
    s, e = ln["src_start"], min(ln["src_end"], vdur - 0.05)
    L = max(0.4, e - s)
    cw, ch, fw, fh, y = _fg_box(aspect, sw, sh)
    nfr = int(round(d * 30))
    emph = ln.get("emphasis")
    if ln["visual"] == "still":
        ts = s + L * 0.45
        inp = ["-ss", f"{ts:.3f}", "-i", str(master), "-frames:v", "1"]
        pre = f"[0:v]trim=end_frame=1,loop=loop={nfr}:size=1:start=0,setpts=N/30/TB,fps=30"
        mode = i % 4      # vary the Ken Burns move so long videos don't feel looped
        if emph:
            zexpr = f"1.02+0.18*on/{nfr}"; kx = 0
        elif mode == 3:
            zexpr = f"1.15-0.13*on/{nfr}"; kx = 0
        else:
            zexpr = f"1+0.13*on/{nfr}"; kx = (0, -0.8, 0.8)[mode]
        how = f"still+kenburns{mode}"
    else:
        r = L / d
        if r >= 1.0:
            inp = ["-ss", f"{s:.3f}", "-t", f"{d+0.2:.3f}", "-i", str(master)]
            pre = "[0:v]setpts=PTS-STARTPTS,fps=30"; how = "cut"
        elif r >= 0.72:
            inp = ["-ss", f"{s:.3f}", "-t", f"{L:.3f}", "-i", str(master)]
            pre = f"[0:v]setpts=(PTS-STARTPTS)*{1/r:.4f},fps=30,tpad=stop_mode=clone:stop_duration=1"; how = f"slow x{r:.2f}"
        else:
            # play at 0.72x then freeze the last frame; slow zoom keeps it alive
            inp = ["-ss", f"{s:.3f}", "-t", f"{L:.3f}", "-i", str(master)]
            pre = f"[0:v]setpts=(PTS-STARTPTS)*{1/0.72:.4f},fps=30,tpad=stop_mode=clone:stop_duration={d:.2f}"; how = "slow+freeze"
        zexpr = (f"1+0.10*exp(-on/5)+0.05*on/{nfr}" if emph else f"1+0.045*on/{nfr}")
        kx = 0
    # fg: crop to target AR, upscale 2x for smooth zoompan, zoom, back to canvas size
    fg = (f"crop={cw}:{ch}:(iw-{cw})/2:(ih-{ch})/2,scale={fw*2}:{fh*2}:flags=lanczos,"
          f"zoompan=z='{zexpr}':x='(iw-iw/zoom)/2*(1+({kx})*on/{nfr})':y='ih/2-(ih/zoom/2)':d=1:s={fw}x{fh}:fps=30")
    bgw, bgh = W // 4, H // 4
    bg = (f"scale={bgw}:{bgh}:force_original_aspect_ratio=increase,crop={bgw}:{bgh},boxblur=12:3,"
          f"scale={W}:{H},eq=brightness=-0.08:saturation=1.25")
    fc = (f"{pre},trim=end_frame={nfr},setpts=PTS-STARTPTS,format=yuv420p,split[a][b];"
          f"[a]{fg}[fg];[b]{bg}[bg];[bg][fg]overlay=(W-w)/2:{y}:shortest=1,setsar=1,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inp, "-filter_complex", fc, "-map", "[v]", "-frames:v", str(nfr),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", "30", str(out)])
    ln["fit"] = how
    return out

def build_narration(lines, out: Path, total):
    rate = 48000
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        written = 0
        for ln in lines:
            start = int(round(ln["t0"] * rate))
            if start > written:
                w.writeframes(b"\x00\x00" * (start - written)); written = start
            with wave.open(ln["audio"]) as r:
                fr = r.readframes(r.getnframes()); w.writeframes(fr); written += len(fr) // 2
        end = int(round(total * rate))
        if end > written:
            w.writeframes(b"\x00\x00" * (end - written))

def render(lines, master, aspect, ass_text, workdir: Path, out_mp4: Path, prog, bgm=None, bgm_level=0.18, p0=60, p1=92):
    workdir.mkdir(parents=True, exist_ok=True)
    sw, sh, vdur = probe_video(master)
    total = plan(lines, vdur)
    segs = [workdir / f"seg_{aspect.replace(':','x')}_{i:02d}.mp4" for i in range(len(lines))]
    done = [0]
    def job(i):
        render_segment(i, lines[i], master, aspect, sw, sh, vdur, segs[i])
        done[0] += 1
        prog(p0 + (p1 - p0 - 8) * done[0] / len(lines), f"เรนเดอร์ช่วงภาพ {aspect} {done[0]}/{len(lines)}")
    with ThreadPoolExecutor(max(2, (os.cpu_count() or 4) // 3)) as ex:
        list(ex.map(job, range(len(lines))))
    lst = workdir / f"concat_{aspect.replace(':','x')}.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    narr = workdir / "narration.wav"
    build_narration(lines, narr, total)
    ass = workdir / f"subs_{aspect.replace(':','x')}.ass"
    ass.write_text(ass_text, encoding="utf-8")
    prog(p1 - 6, f"ผสมเสียง + ฝังซับไทย ({aspect})")
    inputs = ["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(narr)]
    vf = f"[0:v]ass={ass.resolve()}:fontsdir={FONTS}[v]"
    if bgm and Path(bgm).exists():
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        af = (f"[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asplit[n1][n2];"
              f"[2:a]aresample=48000,aformat=channel_layouts=mono,volume={bgm_level}[m];"
              f"[m][n1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
              f"[n2][duck]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={max(0,total-1.2):.2f}:d=1.2[a]")
    else:
        af = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", vf + ";" + af,
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_mp4)])
    return total
