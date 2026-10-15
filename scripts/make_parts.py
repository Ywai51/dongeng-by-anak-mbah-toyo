#!/usr/bin/env python3
"""Bikin part-part YouTube dari proyek dongeng.

Tiap part = [intro] + [isi part di-speed 1.2x] + [outro].
Part dibentuk dengan menggabungkan scene sampai MENDekati --max-part detik
(batas keras); kalau 1 scene bikin lewat, scene itu pindah ke part berikutnya.

Outro = freeze frame terakhir + teks besar ("LANJUT PART X" / "TAMAT")
        + sound quick-ting + TTS voice narator.

Pakai:
  python3 make_parts.py --dir <proyek> [--speed 1.2] [--max-part 180] [--out <folder>]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_video_sep as bv  # noqa: E402

INTRO = "/root/dongeng_txt/intro/intro.mp4"
OUTRO_SOUND = "/root/dongeng_txt/outro/quick-ting.mp3"
FONT = "/usr/share/fonts/truetype/custom/Poppins-ExtraBold.ttf"
VOICE = "id-ID-GadisNeural"
W, H, FPS, SR = 1080, 1920, 30, 48000


def probe(path):
    return bv.probe_dur(path)


def tts_remote(text, out):
    """Bikin mp3 TTS di light1 (IP VPS-ini diblokir Edge)."""
    rdir = "/tmp/part_tts"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    local_txt = out + ".txt"
    with open(local_txt, "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                    "light1", f"mkdir -p {rdir}"], check=True)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", local_txt,
                    f"light1:{rdir}/t.txt"], check=True)
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "light1",
                        f"edge-tts --voice {VOICE} --file {rdir}/t.txt "
                        f"--write-media {rdir}/o.mp3"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tts remote gagal: {r.stderr[:300]}")
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes",
                    f"light1:{rdir}/o.mp3", out], check=True)
    return out


def norm_intro(out):
    rc, so, se = bv.run([
        "ffmpeg", "-y", "-i", INTRO,
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H},setsar=1,format=yuv420p,fps={FPS}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", out])
    return rc == 0 and os.path.exists(out)


def build_outro(png, text, tts_mp3, out):
    ting_d = probe(OUTRO_SOUND) or 1.0
    tts_d = probe(tts_mp3) or 2.0
    T = ting_d + tts_d + 1.2
    fc = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"setsar=1,format=yuv420p,"
        f"drawtext=fontfile={FONT}:text='{text}':fontsize=120:fontcolor=yellow:"
        f"borderw=7:bordercolor=white:x=(w-text_w)/2:y=h*0.38[v];"
        f"[1:a]aresample={SR},aformat=channel_layouts=stereo[a0];"
        f"[2:a]aresample={SR},aformat=channel_layouts=stereo[a1];"
        f"[a0][a1]concat=n=2:v=0:a=1,apad[a]")
    rc, so, se = bv.run([
        "ffmpeg", "-y", "-loop", "1", "-i", png, "-i", OUTRO_SOUND, "-i", tts_mp3,
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{T:.3f}",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", out], timeout=1800)
    if rc != 0 or not os.path.exists(out):
        print("  outro GAGAL:\n" + se[-1000:])
        return None
    return out


def concat(paths, out):
    ins = []
    for p in paths:
        ins += ["-i", p]
    n = len(paths)
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    rc, so, se = bv.run(["ffmpeg", "-y"] + ins + [
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", out], timeout=3600)
    if rc != 0 or not os.path.exists(out):
        print("  concat GAGAL:\n" + se[-1000:])
        return None
    return out


def merge_clips(clips, cfg, tmp, tag):
    """Tree-merge klip pakai xfade (sama seperti join build_video_sep)."""
    CHUNK = 4
    items = list(clips)
    level = 0
    while len(items) > 1:
        nxt = []
        for gi in range(0, len(items), CHUNK):
            grp = items[gi:gi + CHUNK]
            if len(grp) == 1:
                nxt.append(grp[0])
                continue
            outp = os.path.join(tmp, f"{tag}_L{level}_{gi // CHUNK}.mp4")
            r = bv.xfade_merge(grp, outp, cfg, crf=18)
            if not r:
                return None
            nxt.append({"n": None, "file": r, "dur": bv.probe_dur(r)})
        items = nxt
        level += 1
    return items[0]["file"]


def build_part(clips, idx, total, cfg, tmp, outdir, bgm_path, bgm_opts, speed, intro_n):
    tag = f"part{idx:02d}"
    # 1. gabung klip scene part ini (xfade)
    merged = merge_clips(clips, cfg, tmp, tag)
    if not merged:
        return None
    # 2. BGM (loop + ducking) untuk part ini
    if bgm_path and os.path.exists(bgm_path):
        bgm_out = os.path.join(tmp, f"{tag}_bgm.mp4")
        r = bv.mix_bgm(merged, bgm_path, bgm_out, bgm_opts)
        if r:
            merged = r
        else:
            print("  (BGM gagal, lanjut tanpa BGM)")
    # 3. speed 1.2x
    sp = os.path.join(tmp, f"{tag}_sp.mp4")
    fc = (f"[0:v]setpts=PTS/{speed},fps={FPS},format=yuv420p[v];"
          f"[0:a]atempo={speed},aresample={SR},aformat=channel_layouts=stereo[a]")
    rc, so, se = bv.run(["ffmpeg", "-y", "-i", merged, "-filter_complex", fc,
                         "-map", "[v]", "-map", "[a]",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                         "-c:a", "aac", "-b:a", "160k", sp], timeout=3600)
    if rc != 0 or not os.path.exists(sp):
        print("  speed GAGAL:\n" + se[-1000:])
        return None
    # 4. outro: freeze frame terakhir + teks + ting + TTS
    last = os.path.join(tmp, f"{tag}_last.png")
    bv.run(["ffmpeg", "-y", "-sseof", "-0.6", "-i", sp, "-frames:v", "1",
            "-update", "1", last])
    if not os.path.exists(last):
        print("  freeze frame GAGAL")
        return None
    txt = "TAMAT" if idx == total else f"LANJUT PART {idx + 1}"
    tts = os.path.join(tmp, f"{tag}_tts.mp3")
    tts_remote(txt, tts)
    outro = build_outro(last, txt, tts, os.path.join(tmp, f"{tag}_outro.mp4"))
    if not outro:
        return None
    # 5. gabung intro + isi + outro
    final = os.path.join(outdir, f"part_{idx:02d}.mp4")
    r = concat([intro_n, sp, outro], final)
    if not r:
        return None
    print(f"  part {idx}: {probe(final):.1f}s -> {os.path.basename(final)}")
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getcwd())
    ap.add_argument("--speed", type=float, default=1.2)
    ap.add_argument("--max-part", type=float, default=180.0,
                    help="batas keras durasi part (detik, setelah speed)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    proj = os.path.abspath(a.dir)
    story = json.load(open(os.path.join(proj, "story.json"), encoding="utf-8"))
    cfg = {"out_w": story["out_w"], "out_h": story["out_h"], "fps": story["fps"],
           "xfade": story["xfade"], "lead_in": story["lead_in"], "pad": story["pad"],
           "img_xfade": story.get("img_xfade", 0.5), "slug": story["slug"]}
    slug = story["slug"]
    clipsdir = os.path.join(proj, "clips")
    outdir = a.out or f"/root/json/dongeng/parts/{slug}"
    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(proj, "_parts_tmp")
    os.makedirs(tmp, exist_ok=True)

    # kumpulkan klip berurutan
    clips = []
    for s in story["scenes"]:
        p = os.path.join(clipsdir, f"scene_{s['n']:02d}.mp4")
        if os.path.exists(p):
            clips.append({"n": s["n"], "file": p, "dur": probe(p)})
    if not clips:
        print("tidak ada klip; render dulu (build_video_sep --clips-only)")
        return 1

    # kelompokkan jadi part (~max_part setelah speed, TERMASUK intro+outro)
    intro_dur = probe(INTRO) or 10.0
    ting_dur = probe(OUTRO_SOUND) or 1.0
    outro_est = ting_dur + 2.0 + 1.2          # ting + TTS ~2s + jeda
    overhead = intro_dur + outro_est          # intro + outro (detik, final)
    budget_final = max(a.max_part - overhead, 30.0)
    max_raw = budget_final * a.speed
    print(f"overhead intro+outro ~{overhead:.1f}s -> budget isi {budget_final:.0f}s "
          f"(max part {a.max_part:.0f}s)")
    parts = []
    cur, curd = [], 0.0
    for c in clips:
        if cur and curd + c["dur"] > max_raw:
            parts.append(cur)
            cur, curd = [], 0.0
        cur.append(c)
        curd += c["dur"]
    if cur:
        parts.append(cur)

    total = len(parts)
    print(f"{slug}: {len(clips)} klip -> {total} part "
          f"(max {a.max_part:.0f}s @ {a.speed}x)")
    for i, p in enumerate(parts, 1):
        raw = sum(c["dur"] for c in p)
        print(f"  part {i}: {len(p)} scene, {raw:.0f}s -> {raw / a.speed:.0f}s")

    intro_n = os.path.join(tmp, "intro_n.mp4")
    if not norm_intro(intro_n):
        print("intro gagal dinormalisasi")
        return 1

    bgm = story.get("bgm")
    bgm_path = None
    if bgm:
        bgm_path = bgm if os.path.isabs(bgm) else os.path.join(proj, bgm)
    bgm_opts = story.get("bgm_opts", {})

    ok = 0
    for i, p in enumerate(parts, 1):
        r = build_part(p, i, total, cfg, tmp, outdir, bgm_path, bgm_opts,
                       a.speed, intro_n)
        if r:
            ok += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nSELESAI: {ok}/{total} part di {outdir}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
