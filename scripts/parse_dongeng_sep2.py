#!/usr/bin/env python3
"""Parser naskah dongeng format BARU v2 (narasi di-split 2) -> story.json.

Beda dari parse_dongeng_sep.py:
  - Tiap nomor narasi dipecah jadi 2 SUB-NARASI: N_1 dan N_2.
  - Tiap sub-narasi punya 3 prompt gambar (mis. narasi 1_1 -> prompt_1_01..03,
    narasi 1_2 -> prompt_1_04..06).
  - Tiap sub-narasi punya teks narasinya SENDIRI (Narasi N_1 : ... / Narasi N_2 : ...).
  - Dialog (Karakter) tetap satu per nomor -> ditempelkan ke sub-narasi TERAKHIR (N_2).

Hasil: jumlah scene = 2 x jumlah nomor (mis. 19 nomor -> 38 scene),
tiap scene punya "prompts": [3 prompt].

Struktur input #ATAS:
    Generation_AI {
      narasi 1_1 {
        prompt_1_01 : "..."
        prompt_1_02 : "..."
        prompt_1_03 : "..."
      }
      narasi 1_2 { prompt_1_04 : "..." ... }
      ...
    }
Struktur input #BAWAH:
    1.
    Narasi 1_1 : ...
    Narasi 1_2 : ...
    Karakter : "..." "..."

Pakai:
  python3 parse_dongeng_sep2.py <file.txt> --out <folder-proyek> [--bgm assets/bgm.mp3]
"""
import argparse
import json
import os
import re

VOICES = {
    "narrator": {"voice": "id-ID-GadisNeural", "rate": "+0%", "pitch": "+0Hz"},
    "anak":     {"voice": "id-ID-GadisNeural", "rate": "+8%", "pitch": "+45Hz"},
    "dewasa":   {"voice": "id-ID-GadisNeural", "rate": "-3%", "pitch": "-20Hz"},
    "pria":     {"voice": "id-ID-ArdiNeural",  "rate": "+0%", "pitch": "+0Hz"},
}
DIALOG_ROT = ["anak", "dewasa", "pria"]


def split_quotes(s):
    out = []
    for m in re.finditer(r'[“"]([^”"]+)[”"]', s):
        t = m.group(1).strip()
        if t:
            out.append(t)
    if not out:
        t = re.sub(r'^KARAKTER\s*:\s*', '', s, flags=re.I).strip()
        if t and t != "-":
            out.append(t)
    return out


def parse(path):
    raw = open(path, encoding="utf-8").read()
    mt = re.search(r'^Judul\s*:\s*(.+)$', raw, re.M)
    judul = mt.group(1).strip() if mt else os.path.splitext(os.path.basename(path))[0]

    # --- #ATAS: prompt per sub-narasi (N, sub) ---
    up = re.split(r'#BAWAH', raw, flags=re.I)[0]
    prompts = {}   # {(n, sub): [3 prompt]}
    for mb in re.finditer(r'narasi\s+(\d+)_(\d+)\s*\{(.*?)\n\s*\}', up, re.S):
        n, sub = int(mb.group(1)), int(mb.group(2))
        body = mb.group(3)
        ps = {}
        for mp in re.finditer(r'prompt_\d+_(\d+)\s*:\s*"(.*?)"\s*$', body, re.M | re.S):
            ps[int(mp.group(1))] = " ".join(mp.group(2).split())
        if ps:
            prompts[(n, sub)] = [ps[k] for k in sorted(ps)]

    # --- #BAWAH: narasi per sub + karakter ---
    parts = re.split(r'#BAWAH', raw, maxsplit=1, flags=re.I)
    down = parts[1] if len(parts) > 1 else ""
    blocks = {}
    for m in re.finditer(r'^\s*(\d+)\.\s*\n(.*?)(?=^\s*\d+\.\s*\n|\Z)',
                         down, re.M | re.S):
        blocks[int(m.group(1))] = m.group(2).strip()

    scenes = []
    di = 0
    for n in sorted(blocks):
        body = blocks[n]
        subs = {}
        for mn in re.finditer(r'^Narasi\s+(\d+)_(\d+)\s*:\s*(.+?)$', body, re.M | re.I):
            subs[int(mn.group(2))] = " ".join(mn.group(3).split())
        mk = re.search(r'^Karakter\s*:\s*(.+)$', body, re.M | re.S | re.I)
        kq = split_quotes(mk.group(1)) if mk else []
        if not subs:
            continue
        last = max(subs)
        for sub in sorted(subs):
            lines = []
            if subs[sub]:
                lines.append({"who": "narrator", "text": subs[sub]})
            if sub == last:   # dialog ditempel di sub terakhir
                for q in kq:
                    lines.append({"who": DIALOG_ROT[di % len(DIALOG_ROT)], "text": q})
                    di += 1
            if not lines:
                continue
            scenes.append({"n": len(scenes) + 1, "dur": 7,
                           "prompts": prompts.get((n, sub), []), "lines": lines})

    # fallback prompt generik
    for i, s in enumerate(scenes):
        if not s["prompts"]:
            s["prompts"] = ["9:16 vertical portrait format. 3D children's storybook "
                            "animation, soft colors. Scene %d of the story." % (i + 1)]
    return judul, scenes


def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or "dongeng"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("txt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--bgm", default="assets/bgm.mp3")
    ap.add_argument("--slug", default=None)
    a = ap.parse_args()

    judul, scenes = parse(a.txt)
    proj = os.path.abspath(a.out)
    os.makedirs(proj, exist_ok=True)
    slug = a.slug or ("dongeng_" + slugify(judul))
    story = {
        "judul": judul, "slug": slug, "size": "1024x1792",
        "out_w": 1080, "out_h": 1920, "xfade": 0.6, "fps": 30,
        "lead_in": 0.5, "pad": 1.0,
        "img_xfade": 0.5,   # transisi antar gambar DI DALAM satu scene
        "bgm": a.bgm, "bgm_opts": {"volume": 0.45, "duck": 0.30},
        "voices": VOICES, "scenes": scenes,
    }
    with open(os.path.join(proj, "story.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=1)
    tot = sum(len(s["prompts"]) for s in scenes)
    print(f"judul  : {judul}")
    print(f"scene  : {len(scenes)}")
    print(f"gambar : {tot} (rata2 {tot/max(len(scenes),1):.1f} per scene)")
    print(f"slug   : {slug}")
    print(f"out    : {os.path.join(proj, 'story.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
