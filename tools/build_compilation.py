"""Build one chronological 'story master' from several official clips, removing footage that repeats.

Different official uploads (Movieclips, studio channels, 4K re-uploads) often contain the same shots. We
fingerprint every clip at 2 fps (16x9 grayscale difference hash), walk the clips in story order, and drop any
run of >= MIN_DUP seconds that already appeared in an earlier clip. The kept pieces are normalised to
854x480 / 30 fps / 48 kHz stereo and concatenated. A JSON map (master time -> clip id/time) is written next to it.

usage: python tools/build_compilation.py clips_dir out.mp4  (clips named NN_<youtubeid>.mp4, NN = story order)
"""
import sys, json, subprocess, re
from pathlib import Path
import numpy as np

FPS = 2; MIN_DUP = 4.0; MIN_KEEP = 3.0; HAM = 10   # bits of 128 allowed to differ
TRIM_HEAD = {"Movieclips": 0.0}

def active_crop(p):
    """Letterbox-free picture area, then a centred 16:9 window, so 2.39 / 2.18 / 16:9 uploads of the same shot match."""
    import collections
    D = dur(p); c = collections.Counter()
    for t in (D * 0.25, D * 0.5, D * 0.75):
        o = subprocess.run(["ffmpeg", "-ss", f"{t:.1f}", "-i", str(p), "-t", "8", "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        c.update(re.findall(r"crop=(\d+:\d+:\d+:\d+)", o))
    w, h, x, y = map(int, c.most_common(1)[0][0].split(":"))
    nw = min(w, int(h * 16 / 9)); nh = min(h, int(w * 9 / 16))
    return f"crop={nw}:{nh}:{x + (w - nw) // 2}:{y + (h - nh) // 2}"

def frames(p):
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(p), "-vf",
           f"fps={FPS},{active_crop(p)},scale=17:8:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 8, 17).astype(np.int16)
    bits = (a[:, :, 1:] > a[:, :, :-1]).reshape(len(a), -1)
    mean = a.reshape(len(a), -1).mean(1); std = a.reshape(len(a), -1).std(1)
    return bits, mean, std

def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)

def main(cdir, out):
    cdir, out = Path(cdir), Path(out)
    clips = sorted(cdir.glob("*.mp4"))
    seen = np.zeros((0, 128), bool)
    pieces, report = [], []
    for c in clips:
        bits, mean, std = frames(c)
        n = len(bits)
        dup = np.zeros(n, bool)
        flat = std < 6      # black / flat frames: never count as duplicates, never as unique content
        if len(seen):
            for i in range(0, n, 256):
                d = (bits[i:i+256, None, :] != seen[None, :, :]).sum(2).min(1)
                dup[i:i+256] = d <= HAM
        dup &= ~flat
        # smooth: dup runs shorter than MIN_DUP are kept (avoid chopping on chance matches)
        keep = np.ones(n, bool); i = 0
        while i < n:
            if dup[i]:
                j = i
                while j < n and (dup[j] or flat[j]): j += 1
                if (j - i) / FPS >= MIN_DUP: keep[i:j] = False
                i = j
            else: i += 1
        segs = []; i = 0
        while i < n:
            if keep[i]:
                j = i
                while j < n and keep[j]: j += 1
                if (j - i) / FPS >= MIN_KEEP: segs.append((i / FPS, j / FPS))
                i = j
            else: i += 1
        D = dur(c)
        if segs: segs[-1] = (segs[-1][0], min(D, segs[-1][1] + 0.5))
        kept = sum(e - s for s, e in segs)
        report.append({"clip": c.name, "dur": round(D, 1), "kept": round(kept, 1), "segments": [(round(s,1), round(e,1)) for s, e in segs]})
        print(f"{c.name}: {D:.0f}s -> keep {kept:.0f}s in {len(segs)} piece(s)", flush=True)
        for s, e in segs: pieces.append((c, s, e))
        seen = np.concatenate([seen, bits[~flat]])
    tmp = out.parent / (out.stem + "_parts"); tmp.mkdir(exist_ok=True)
    lst, tmap, t = [], [], 0.0
    for k, (c, s, e) in enumerate(pieces):
        p = tmp / f"p{k:03d}.mp4"
        if not p.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s:.2f}", "-t", f"{e-s:.2f}", "-i", str(c),
                            "-vf", "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", "30",
                            "-af", "aresample=48000", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(p)], check=True)
        d = dur(p); lst.append(f"file '{p.resolve()}'\n")
        tmap.append({"t0": round(t, 2), "t1": round(t + d, 2), "clip": c.name, "src_s": round(s, 2)}); t += d
    (tmp / "list.txt").write_text("".join(lst))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    out.with_suffix(".map.json").write_text(json.dumps({"pieces": tmap, "clips": report}, indent=1))
    print(f"master {out} {t:.0f}s from {len(pieces)} pieces")

if __name__ == "__main__":
    main(*sys.argv[1:3])
