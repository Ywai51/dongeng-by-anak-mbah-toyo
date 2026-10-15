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

# Suara konsisten per tokoh: nama yang sama -> suara yang sama (hash stabil).
VOICE_POOL = ["anak", "dewasa", "pria"]
# petunjuk jenis suara dari kata peran (best-effort)
FEMALE_HINT = re.compile(r'\b(ibu|bunda|mama|nenek|putri|ratu|bibi|tante|'
                         r'gadis|perempuan|ibu tiri|peri|dewi|nyonya|'
                         r'kakak|adik|saudari|istri|puan)\b', re.I)
CHILD_HINT = re.compile(r'\b(anak|kecil|adik|bocah|bayi|kakak kecil)\b', re.I)


def voice_for(name):
    """Nama tokoh -> key suara (stabil, sama tiap kemunculan)."""
    n = (name or "").strip().lower()
    if not n:
        return None
    if FEMALE_HINT.search(n) and "anak" not in n:
        return "dewasa"
    if CHILD_HINT.search(n):
        return "anak"
    # hash stabil supaya tokoh yang sama selalu bersuara sama
    h = sum(ord(c) for c in n)
    return VOICE_POOL[h % len(VOICE_POOL)]


# --- perbaikan dialog: tambah PENGHUBUNG, jangan baca nama subjek mentah ---
VERBS = ("kata", "katanya", "sahut", "sahutnya", "ujar", "ujarnya", "sapa",
         "sapanya", "tanya", "tanyanya", "jawab", "jawabnya", "ajak", "ajaknya",
         "seru", "serunya", "ucap", "ucapnya", "balas", "balasnya", "panggil",
         "teriak", "bisik", "gumam", "timpal", "sambung", "lanjut", "mohon",
         "menjawab", "bertanya", "menyahut", "menyapa", "mengajak", "berseru")
VERB_RE = re.compile(r'\b(' + "|".join(VERBS) + r')\b', re.I)
# kata yang BUKAN nama kalau berdiri di depan dialog ("X, ...")
NOT_NAME = {
    "kabarnya", "katanya", "konon", "awalnya", "suatu", "pada", "di", "saat",
    "ketika", "ternyata", "akhirnya", "setelah", "kemudian", "lalu", "maka",
    "namun", "tetapi", "tapi", "dan", "ia", "dia", "mereka", "aku", "kamu",
    "kau", "kita", "kami", "saya", "yah", "ya", "oh", "eh", "ah", "hmm",
    "jadi", "benar", "entah", "sebenarnya", "tentu", "nah", "sudahlah", "ayo",
    "mari", "dengar", "lihat", "cepat", "jangan", "tolong", "maaf", "terima",
    "silakan", "aduh", "astaga", "sungguh", "pokoknya", "syukurlah", "permisi",
    "masuklah", "bangunlah", "dengarlah", "lihatlah", "tunggu", "eit", "hai",
    "halo", "selamat", "hei", "wuih", "wah", "duh", "aduhai", "baiklah",
    "menurutmu", "menurutku", "menurut", "sepertinya", "rasanya", "mungkin",
    "maksudku", "maksudmu", "bagiku", "bagimu", "bahkan", "selain", "sebab",
    "karena", "padahal", "sebenarnya", "jangan-jangan", "seingatku", "kurasa",
    "kurasa", "sungguh", "coba", "tidakkah", "bukankah", "apakah", "masa",
    "sebabnya", "itulah", "inilah", "begitulah", "dengarkan", "percayalah",
    "namaku", "namamu", "namanya", "nama", "aku", "kalian", "mereka", "semua",
}
# kata keterangan yang menggantung di akhir atribusi (dibuang)
MANNER = re.compile(
    r'\b(agak|sambil|dengan|pelan|keras|cepat|gusar|ragu|tertawa|santai|tegas|'
    r'marah|sedih|gembira|takut|heran|kaget|lirih|perlahan|kembali|pula|lalu|'
    r'menjelaskan|mewakili|menambahkan|melanjutkan|menimpali|menukas|menjawab|'
    r'menyahut|mengangguk|tersenyum|menangis|sambil tersenyum|sambil menangis|'
    r'dengan lembut|dengan tegas|dengan keras|dengan pelan)\b.*$', re.I)


def _first_sentence(s):
    s = s.strip()
    m = re.match(r'(.+?[.!?])(?:\s|$)', s)
    return (m.group(1) if m else s).strip()


def _extract_attr(text):
    """Ambil (verb, speaker) dari teks atribusi, mis. 'kata ayah Hanhan.'"""
    t = _first_sentence(text.strip())
    if not t:
        return None
    m = VERB_RE.search(t)
    if not m:
        return None
    verb = m.group(1).lower()
    spk = t[m.end():].strip(" ,.-")
    spk = MANNER.sub("", spk).strip(" ,.-")
    spk = re.sub(r'\s+', ' ', spk)
    spk = _clean_speaker(spk)
    if not spk:
        return None
    return verb, spk


def _lead_vocative(dlg):
    """Kata panggilan di depan dialog: 'Hanhan, ayah capek...' -> ('Hanhan', sisa)."""
    m = re.match(r"^([A-Z][\w'’]*(?:\s+[A-Z][\w'’]*){0,2})\s*,\s+(.+)$",
                 dlg.strip(), re.S)
    if not m:
        return None, dlg
    name = m.group(1).strip()
    if name.split()[0].lower() in NOT_NAME or len(name) < 3:
        return None, dlg
    return name, m.group(2).strip()


def _clean_speaker(spk):
    """'Hanhan di depan pintu' -> 'Hanhan'; 'ayah Hanhan' tetap."""
    spk = MANNER.sub("", spk).strip(" ,.-")
    # kalau kata pertama Kapital lalu ada kata huruf-kecil -> potong di situ
    toks = spk.split()
    if toks and toks[0][:1].isupper():
        for i in range(1, len(toks)):
            if toks[i][:1].islower():
                spk = " ".join(toks[:i])
                break
    return re.sub(r'\s+', ' ', spk).strip(" ,.-")


def dialog_line(raw_k):
    """Ubah baris Karakter jadi daftar kalimat siap-TTS.

    Tujuan: JANGAN membaca nama subjek mentah tanpa konteks. Beri PENGHUBUNG
    ('Kata ayah Hanhan, ...' / 'Kata Mentari kepada Bintang Langit, ...')
    supaya pendengar tahu siapa yang bicara, dan buang kata panggilan yang
    menggantung di depan dialog.
    """
    raw_k = (raw_k or "").strip()
    if not raw_k or raw_k in ("-", "–", "(tidak ada dialog)"):
        return []

    # --- format label:  Nama: "dialog"   (boleh dipisah "/") ---
    if re.search(r'[A-Za-z][\w\'’ ]*\s*:\s*[“"]', raw_k):
        out = []
        for seg in re.split(r'\s*/\s*', raw_k):
            seg = seg.strip()
            if not seg:
                continue
            m = re.match(r'^([^:]{1,40}?)\s*:\s*(.+)$', seg, re.S)
            if m and re.search(r'[“"]', m.group(2)):
                spk = _clean_speaker(m.group(1).strip())
                for q in re.findall(r'[“"]([^”"]+)[”"]', m.group(2)):
                    q = q.strip()
                    if q:
                        out.append({"speaker": spk, "text": f"Kata {spk}, {q}"})
            else:
                for q in re.findall(r'[“"]([^”"]+)[”"]', seg):
                    if q.strip():
                        out.append({"speaker": None, "text": q.strip()})
        return out

    # --- format biasa: "dialog" atribusi "dialog" ... ---
    qs = list(re.finditer(r'[“"]([^”"]+)[”"]', raw_k))
    if not qs:
        t = re.sub(r'^KARAKTER\s*:\s*', '', raw_k, flags=re.I).strip()
        return [{"speaker": None, "text": t}] if t and t != "-" else []

    out = []
    for i, m in enumerate(qs):
        dlg = m.group(1).strip()
        if not dlg:
            continue
        after = raw_k[m.end():(qs[i + 1].start() if i + 1 < len(qs) else len(raw_k))].strip()
        before = raw_k[(qs[i - 1].end() if i > 0 else 0):m.start()].strip()
        attr = _extract_attr(after)
        voc, core = _lead_vocative(dlg)
        if attr:
            verb, spk = attr
            conn = f"{verb.capitalize()} {spk}"
            if voc and voc.lower() not in spk.lower() and spk.lower() not in voc.lower():
                conn += f" kepada {voc}"
            out.append({"speaker": spk, "text": f"{conn}, {core}"})
        elif voc:
            # tanpa atribusi tapi ada panggilan -> biarkan apa adanya (aman)
            out.append({"speaker": None, "text": dlg})
        else:
            ml = re.match(r'^([^:]{1,40}?)\s*:\s*$', before)
            if ml and re.search(r'[A-Za-z]', ml.group(1)):
                spk = _clean_speaker(ml.group(1))
                out.append({"speaker": spk, "text": f"Kata {spk}, {dlg}"})
            else:
                out.append({"speaker": None, "text": dlg})
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
        kq = dialog_line(mk.group(1)) if mk else []
        if not subs:
            continue
        last = max(subs)
        for sub in sorted(subs):
            lines = []
            if subs[sub]:
                lines.append({"who": "narrator", "text": subs[sub]})
            if sub == last:   # dialog ditempel di sub terakhir
                for q in kq:
                    who = DIALOG_ROT[di % len(DIALOG_ROT)]
                    if q.get("speaker"):
                        who = voice_for(q["speaker"])
                    lines.append({"who": who, "text": q["text"]})
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
