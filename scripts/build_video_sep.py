#!/usr/bin/env python3
"""Pipeline-Cerpen tahap 3 (format BARU): video 9:16 dari 6 gambar/narasi.

Beda dari build_video.py lama:
  - Tiap scene punya BEBERAPA gambar (biasanya 6, dari 6 prompt).
  - Semua gambar scene itu digabung dengan transisi HALUS (xfade) + Ken Burns,
    panjangnya persis = durasi audio narasi scene tsb.
  - Sisanya sama: subtitle per-kata kapital kuning+glow putih, join bertahap,
    BGM loop + ducking.

Pakai:
  python3 build_video_sep.py [--dir <proyek>]
  python3 build_video_sep.py --scene 1          # cuma scene 1 (uji)
  python3 build_video_sep.py --scene-from 1 --scene-to 19 --clips-only   # separuh (split)
  python3 build_video_sep.py --join-only
  python3 build_video_sep.py --join-only --no-bgm
"""
import argparse
import json
import os
import shutil
import subprocess

FONT = "Poppins ExtraBold"
FONT_SIZE = 118
SUB_MARGIN_V = 340

BGM_VOL = 0.45
BGM_DUCK = 0.30
BGM_THRESH_DB = -42.0
BGM_ATTACK_MS = 60
BGM_RELEASE_MS = 900
BGM_FRAME_MS = 20
NAR_LUFS = -14
SR = 48000


def run(cmd, timeout=1800):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def ass_time(t):
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_ass(words, lead):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Glow,{FONT},{FONT_SIZE},&H0000FFFF,&H0000FFFF,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,16,16,2,40,40,{SUB_MARGIN_V},1
Style: Main,{FONT},{FONT_SIZE},&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,3,2,40,40,{SUB_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    out = [header]
    for vi in range(len(words)):
        w = words[vi]
        start = lead + w["start"]
        end = lead + (words[vi + 1]["start"] if vi + 1 < len(words) else w["end"] + 0.35)
        if end <= start:
            end = start + 0.15
        anim = r"{\fad(60,60)\fscx78\fscy78\t(0,130,\fscx100\fscy100)}"
        txt = anim + w["word"].upper()
        out.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Glow,,0,0,0,,{txt}")
        out.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{txt}")
    return "\n".join(out) + "\n"


def kb_expr(idx, frames):
    """Ken Burns bergantian: ganjil zoom-in, genap zoom-out (biar transisi hidup)."""
    n = max(frames - 1, 1)
    if idx % 2 == 1:
        return f"min(1+0.10*on/{n},1.10)"
    return f"max(1.10-0.10*on/{n},1.0)"


def build_scene(s, cfg, dirs):
    n = s["n"]
    # kumpulkan gambar scene ini (scene_NN_01 .. _NN)
    imgs = []
    i = 1
    while True:
        p = os.path.join(dirs["images"], f"scene_{n:02d}_{i:02d}.png")
        if os.path.exists(p):
            imgs.append(p)
            i += 1
        else:
            break
    # fallback: format lama (scene_NN.png)
    if not imgs:
        old = os.path.join(dirs["images"], f"scene_{n:02d}.png")
        if os.path.exists(old):
            imgs = [old]
    mp3 = os.path.join(dirs["tts"], f"scene_{n:02d}.mp3")
    meta = os.path.join(dirs["tts"], f"scene_{n:02d}.json")
    if not (imgs and os.path.exists(mp3) and os.path.exists(meta)):
        print(f"  scene {n}: berkas kurang, lewati")
        return None

    words = json.load(open(meta, encoding="utf-8"))
    lead, pad = cfg["lead_in"], cfg["pad"]
    a_end = words[-1]["end"] if words else 0
    D = lead + a_end + pad

    os.makedirs(dirs["subs"], exist_ok=True)
    ass = os.path.join(dirs["subs"], f"scene_{n:02d}.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(build_ass(words, lead))

    out = os.path.join(dirs["clips"], f"scene_{n:02d}.mp4")
    fps = cfg["fps"]
    W, H = cfg["out_w"], cfg["out_h"]
    xf = cfg["img_xfade"]
    k = len(imgs)
    if k == 1:
        seg = D
    else:
        seg = (D + (k - 1) * xf) / k
    frames = max(int(seg * fps), 2)

    # input: tiap gambar di-loop
    inputs = []
    for p in imgs:
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{seg:.3f}", "-i", p]
    inputs += ["-i", mp3]

    # tiap gambar: scale/crop + Ken Burns
    vparts = []
    for i in range(k):
        z = kb_expr(i + 1, frames)
        vparts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={W}x{H}:fps={fps},setsar=1[v{i}]"
        )
    # xfade berantai antar gambar
    if k == 1:
        vfinal = "v0"
    else:
        prev = "v0"
        for i in range(1, k):
            o = max(0.0, i * (seg - xf))
            lab = f"x{i}"
            vparts.append(
                f"[{prev}][v{i}]xfade=transition=fade:duration={xf}:offset={o:.3f}[{lab}]")
            prev = lab
        vfinal = prev
    # subtitle di gambar akhir
    vparts.append(f"[{vfinal}]subtitles={ass}:fontsdir=/usr/share/fonts/truetype/custom,"
                  f"format=yuv420p[vout]")

    ai = k  # index audio input
    vparts.append(
        f"[{ai}:a]adelay={int(lead*1000)}|{int(lead*1000)},apad,atrim=0:{D:.3f},"
        f"asetpts=N/SR/TB[aout]")

    fc = ";".join(vparts)
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-t", f"{D:.3f}", "-r", str(fps), out])
    rc, so, se = run(cmd, timeout=1800)
    if rc != 0 or not os.path.exists(out):
        print(f"  scene {n}: GAGAL render\n{se[-1200:]}")
        return None
    print(f"  scene {n}: {D:.2f}s ({k} gambar) OK")
    return {"n": n, "file": out, "dur": D}


def probe_dur(path):
    rc, so, se = run(["ffprobe", "-v", "error", "-show_entries",
                      "format=duration", "-of", "default=nw=1:nk=1", path])
    try:
        return float(so.strip())
    except Exception:
        return 0.0


def xfade_merge(items, out, cfg, crf=22):
    n = len(items)
    if n == 1:
        return items[0]["file"]
    xf = cfg["xfade"]
    fps = cfg["fps"]
    inputs = []
    for c in items:
        inputs += ["-i", c["file"]]
    vparts, aparts = [], []
    vprev, aprev = "[0:v]", "[0:a]"
    off = items[0]["dur"]
    for i in range(1, n):
        vout, aout = f"[vx{i}]", f"[ax{i}]"
        o = max(0.0, off - xf)
        vparts.append(f"{vprev}[{i}:v]xfade=transition=fade:duration={xf}:offset={o:.3f}{vout}")
        aparts.append(f"{aprev}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{aout}")
        vprev, aprev = vout, aout
        off = o + items[i]["dur"]
    fc = ";".join(vparts + aparts)
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", fc, "-map", vprev, "-map", aprev,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-c:a", "aac", "-b:a", "160k",
            "-r", str(fps), "-pix_fmt", "yuv420p", out])
    rc, so, se = run(cmd, timeout=3600)
    if rc != 0 or not os.path.exists(out):
        print(f"MERGE GAGAL ({os.path.basename(out)}):\n" + se[-1200:])
        return None
    return out


def join(clips, cfg, dirs):
    if len(clips) == 1:
        return clips[0]["file"]
    CHUNK = 4
    tmpdir = os.path.join(dirs["proj"], "_join_tmp")
    os.makedirs(tmpdir, exist_ok=True)
    items = list(clips)
    level = 0
    while len(items) > 1:
        nxt = []
        for gi in range(0, len(items), CHUNK):
            grp = items[gi:gi + CHUNK]
            if len(grp) == 1:
                nxt.append(grp[0])
                continue
            outp = os.path.join(tmpdir, f"L{level}_{gi // CHUNK}.mp4")
            r = xfade_merge(grp, outp, cfg, crf=18)
            if not r:
                return None
            nxt.append({"n": None, "file": r, "dur": probe_dur(r)})
        items = nxt
        level += 1
    final = os.path.join(dirs["proj"], f"{cfg['slug']}.mp4")
    shutil.copy(items[0]["file"], final)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return final


def _read_f32(path):
    import numpy as np
    return np.fromfile(path, dtype="<f4")


def _write_wav16(path, samples, sr=SR):
    import wave
    import numpy as np
    x = np.clip(samples, -1.0, 1.0)
    pcm = (x * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _duck_envelope(nar, sr=SR, frame_ms=BGM_FRAME_MS, base=BGM_VOL, duck=BGM_DUCK,
                   thresh_db=BGM_THRESH_DB, attack_ms=BGM_ATTACK_MS,
                   release_ms=BGM_RELEASE_MS):
    import numpy as np
    hop = max(1, int(sr * frame_ms / 1000.0))
    nf = len(nar) // hop
    if nf <= 0:
        return np.full(len(nar), base, dtype="f4")
    seg = nar[:nf * hop].reshape(nf, hop).astype("f8")
    rms = np.sqrt((seg * seg).mean(axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-12)
    gate = np.zeros(nf, dtype=bool)
    on = False
    for i in range(nf):
        on = (db[i] > thresh_db - 6.0) if on else (db[i] > thresh_db)
        gate[i] = on
    tgt = np.where(gate, duck, base)
    dt = frame_ms / 1000.0
    ka = 1.0 - np.exp(-dt / max(attack_ms / 1000.0, 1e-4))
    kr = 1.0 - np.exp(-dt / max(release_ms / 1000.0, 1e-4))
    g = np.empty(nf, dtype="f8")
    cur = base
    for i in range(nf):
        k = ka if tgt[i] < cur else kr
        cur += (tgt[i] - cur) * k
        g[i] = cur
    full = np.repeat(g, hop).astype("f4")
    if len(full) < len(nar):
        pad = np.full(len(nar) - len(full), g[-1], dtype="f4")
        full = np.concatenate([full, pad])
    return full[:len(nar)]


def mix_bgm(video, bgm, out, b):
    import numpy as np
    dur = probe_dur(video)
    if dur <= 0:
        return None
    tmpdir = os.path.join(os.path.dirname(os.path.abspath(out)), "_bgm_tmp")
    os.makedirs(tmpdir, exist_ok=True)
    nar_f = os.path.join(tmpdir, "nar.f32")
    bgm_f = os.path.join(tmpdir, "bgm.f32")
    duck_wav = os.path.join(tmpdir, "bgm_ducked.wav")
    rc, so, se = run(["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1",
                      "-ar", str(SR), "-f", "f32le", nar_f])
    if rc != 0:
        print("BGM: ekstrak narasi gagal\n" + se[-500:])
        return None
    rc, so, se = run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", bgm,
                      "-t", f"{dur:.3f}", "-ac", "1", "-ar", str(SR),
                      "-f", "f32le", bgm_f])
    if rc != 0:
        print("BGM: ekstrak bgm gagal\n" + se[-500:])
        return None
    nar = _read_f32(nar_f)
    bm = _read_f32(bgm_f)
    n = min(len(nar), len(bm))
    if n == 0:
        return None
    nar, bm = nar[:n], bm[:n]
    g = _duck_envelope(nar, base=b.get("volume", BGM_VOL),
                       duck=b.get("duck", BGM_DUCK),
                       thresh_db=b.get("threshold_db", BGM_THRESH_DB),
                       attack_ms=b.get("attack", BGM_ATTACK_MS),
                       release_ms=b.get("release", BGM_RELEASE_MS))
    ducked = bm * g
    _write_wav16(duck_wav, ducked)
    fc = (f"[0:a]loudnorm=I={NAR_LUFS}:TP=-1.5:LRA=11[nar];"
          f"[1:a]volume=1.0[b];"
          f"[nar][b]amix=inputs=2:duration=first:normalize=0,"
          f"alimiter=limit=0.95[aout]")
    rc, so, se = run(["ffmpeg", "-y", "-i", video, "-i", duck_wav,
                      "-filter_complex", fc,
                      "-map", "0:v", "-map", "[aout]",
                      "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                      "-t", f"{dur:.3f}", "-movflags", "+faststart", out],
                     timeout=3600)
    shutil.rmtree(tmpdir, ignore_errors=True)
    if rc != 0 or not os.path.exists(out):
        print("MIX BGM GAGAL:\n" + se[-1200:])
        return None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getcwd())
    ap.add_argument("--scene", type=int)
    ap.add_argument("--scene-from", type=int, dest="scene_from")
    ap.add_argument("--scene-to", type=int, dest="scene_to")
    ap.add_argument("--clips-only", action="store_true",
                    help="render scene jadi klip saja, tanpa join/BGM (untuk split)")
    ap.add_argument("--join-only", action="store_true")
    ap.add_argument("--no-bgm", action="store_true")
    a = ap.parse_args()

    proj = os.path.abspath(a.dir)
    story = json.load(open(os.path.join(proj, "story.json"), encoding="utf-8"))
    cfg = {"out_w": story["out_w"], "out_h": story["out_h"], "fps": story["fps"],
           "xfade": story["xfade"], "lead_in": story["lead_in"], "pad": story["pad"],
           "img_xfade": story.get("img_xfade", 0.5), "slug": story["slug"]}
    dirs = {"proj": proj, "images": os.path.join(proj, "images"),
            "tts": os.path.join(proj, "tts"), "clips": os.path.join(proj, "clips"),
            "subs": os.path.join(proj, "subs")}
    os.makedirs(dirs["clips"], exist_ok=True)

    scenes = story["scenes"]
    if a.scene:
        scenes = [s for s in scenes if s["n"] == a.scene]
    if a.scene_from or a.scene_to:
        lo = a.scene_from or 1
        hi = a.scene_to or 10**9
        scenes = [s for s in scenes if lo <= s["n"] <= hi]

    clips = []
    if not a.join_only:
        for s in scenes:
            r = build_scene(s, cfg, dirs)
            if r:
                clips.append(r)

    if a.clips_only:
        print(f"\nCLIPS ONLY: {len(clips)} klip dirender (tanpa join/BGM)")
        return 0 if clips else 1

    if not clips:
        clips = [{"n": s["n"], "file": os.path.join(dirs["clips"], f"scene_{s['n']:02d}.mp4"),
                  "dur": None} for s in scenes
                 if os.path.exists(os.path.join(dirs["clips"], f"scene_{s['n']:02d}.mp4"))]
        for c in clips:
            if c["dur"] is None:
                c["dur"] = probe_dur(c["file"])

    if a.scene or not clips:
        return 0
    out = join(clips, cfg, dirs)
    if not out:
        return 1

    bgm = story.get("bgm")
    if bgm and not a.no_bgm:
        bgm_path = bgm if os.path.isabs(bgm) else os.path.join(proj, bgm)
        if os.path.exists(bgm_path):
            tmp = os.path.join(proj, "_mix_tmp.mp4")
            r = mix_bgm(out, bgm_path, tmp, story.get("bgm_opts", {}))
            if r:
                os.replace(tmp, out)
                print(f"BGM: {os.path.basename(bgm_path)} "
                      f"(loop + ducking, vol {story.get('bgm_opts', {}).get('volume', BGM_VOL)})")
            else:
                print("BGM gagal, video tetap tanpa BGM")
        else:
            print(f"BGM tidak ditemukan: {bgm_path}")

    print(f"\nVIDEO JADI: {out}  ({probe_dur(out):.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
