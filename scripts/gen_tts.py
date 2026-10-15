#!/usr/bin/env python3
"""TTS narasi/dialog -> mp3 + timestamp PER-KATA (word boundary).

Pakai edge-tts (WordBoundary events) supaya subtitle bisa per-kata.
Output: tts/scene_XX.mp3 + tts/scene_XX.json (daftar {word,start,end}).

PENTING: IP VPS-ini (8.215.67.24) DIBLOKIR Microsoft Edge TTS (403). Karena itu
TTS dijalankan di host lain lewat SSH (default alias `light1`) lalu hasilnya
disalin kembali. Aktifkan otomatis: --remote light1 (atau env CERPen_TTS_REMOTE).
Kalau remote gagal, fallback ke lokal.

Pakai: python3 gen_tts.py [--dir <proyek>] [--force] [--remote light1|none]
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def log_to(path, m):
    print(m, flush=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(m + "\n")


# ---------------------------------------------------------------- lokal
async def tts_one(text, voice, rate, pitch, mp3, meta):
    import edge_tts
    # boundary="WordBoundary" -> timestamp PER-KATA (default hanya per-kalimat)
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                dur = chunk["duration"] / 1e7
                words.append({"word": chunk["text"],
                              "start": round(start, 3),
                              "end": round(start + dur, 3)})
    json.dump(words, open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return words


# ---------------------------------------------------------------- remote (SSH)
REMOTE_WORKER = r'''import asyncio, json, sys, os
import edge_tts

def run(job):
    """Tulis ke NAMA FILE SAJA (cwd), bukan path lengkap dari mesin pemanggil."""
    async def one(text, voice, rate, pitch, mp3, meta):
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                    boundary="WordBoundary")
        words = []
        with open(os.path.basename(mp3), "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    s = ch["offset"] / 1e7
                    d = ch["duration"] / 1e7
                    words.append({"word": ch["text"], "start": round(s, 3),
                                  "end": round(s + d, 3)})
        json.dump(words, open(os.path.basename(meta), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return words

    async def main():
        for j in job:
            await one(j["text"], j["voice"], j["rate"], j["pitch"],
                      j["mp3"], j["meta"])
    asyncio.run(main())

if __name__ == "__main__":
    run(json.load(open(sys.argv[1], encoding="utf-8")))
'''


def tts_remote(jobs, host, workdir):
    """Jalankan TTS di host lain lewat SSH, lalu tarik hasilnya.

    jobs: list dict {text, voice, rate, pitch, mp3, meta} dengan mp3/meta =
          PATH LENGKAP lokal (tujuan salinan). Nama file remote diambil dari
          basename-nya.
    """
    os.makedirs(workdir, exist_ok=True)
    rdir = "/tmp/cerpen_tts"
    jf = os.path.join(workdir, "tts_jobs.json")
    wf = os.path.join(workdir, "tts_worker.py")
    # file job untuk remote: pakai NAMA FILE saja
    remote_jobs = [{"text": j["text"], "voice": j["voice"], "rate": j["rate"],
                    "pitch": j["pitch"], "mp3": os.path.basename(j["mp3"]),
                    "meta": os.path.basename(j["meta"])} for j in jobs]
    json.dump(remote_jobs, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
    open(wf, "w", encoding="utf-8").write(REMOTE_WORKER)

    def ssh(cmd, timeout=900):
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                               host, cmd], capture_output=True, text=True, timeout=timeout)

    r = ssh(f"mkdir -p {rdir} && rm -f {rdir}/*.mp3 {rdir}/*.json")
    if r.returncode != 0:
        raise RuntimeError(f"ssh gagal: {r.stderr[:200]}")
    for f, name in ((jf, "tts_jobs.json"), (wf, "tts_worker.py")):
        r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f, f"{host}:{rdir}/{name}"],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"scp gagal: {r.stderr[:200]}")

    r = ssh(f"cd {rdir} && python3 tts_worker.py tts_jobs.json", timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"TTS remote gagal: {(r.stderr or r.stdout)[-300:]}")

    # tarik hasil ke PATH LENGKAP lokal (folder tujuan dibuat dulu)
    for j in jobs:
        for key in ("mp3", "meta"):
            dest = j[key]
            fn = os.path.basename(dest)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes",
                                f"{host}:{rdir}/{fn}", dest],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                raise RuntimeError(f"ambil {fn} gagal: {r.stderr[:200]}")
    return True


async def main(dirp, force, remote):
    proj = os.path.abspath(dirp)
    story = json.load(open(os.path.join(proj, "story.json"), encoding="utf-8"))
    voices = story["voices"]
    out = os.path.join(proj, "tts")
    logfile = os.path.join(proj, "gen_tts.log")
    os.makedirs(out, exist_ok=True)

    todo = []
    for s in story["scenes"]:
        n = s["n"]
        mp3 = os.path.join(out, f"scene_{n:02d}.mp3")
        meta = os.path.join(out, f"scene_{n:02d}.json")
        if not force and os.path.exists(mp3) and os.path.exists(meta) \
                and os.path.getsize(mp3) > 1000:
            log_to(logfile, f"scene {n}: sudah ada, lewati")
            continue
        text = " ".join(l["text"] for l in s["lines"])
        v = voices[s["lines"][0]["who"]]
        todo.append({"n": n, "text": text, "voice": v["voice"], "rate": v["rate"],
                     "pitch": v["pitch"], "mp3": mp3, "meta": meta})

    if not todo:
        log_to(logfile, "selesai: 0 audio dibuat")
        return

    if remote and remote != "none":
        try:
            tts_remote(todo, remote, os.path.join(proj, "_tts_remote"))
            log_to(logfile, f"TTS remote ({remote}) OK untuk {len(todo)} scene")
            for j in todo:
                words = json.load(open(j["meta"], encoding="utf-8"))
                dur = words[-1]["end"] if words else 0
                log_to(logfile, f"scene {j['n']}: {dur:.2f}s, {len(words)} kata (remote)")
            log_to(logfile, f"selesai: {len(todo)} audio dibuat")
            return
        except Exception as e:
            log_to(logfile, f"TTS remote gagal ({e}); coba lokal...")

    # lokal
    for j in todo:
        words = await tts_one(j["text"], j["voice"], j["rate"], j["pitch"],
                              j["mp3"], j["meta"])
        dur = words[-1]["end"] if words else 0
        log_to(logfile, f"scene {j['n']}: {dur:.2f}s, {len(words)} kata -> "
                        f"{os.path.basename(j['mp3'])}")
    log_to(logfile, f"selesai: {len(todo)} audio dibuat")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getcwd())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--remote", default=os.environ.get("CERPEN_TTS_REMOTE", "light1"),
                    help="host SSH untuk TTS (default light1); 'none' = lokal saja")
    a = ap.parse_args()
    asyncio.run(main(a.dir, a.force, a.remote))
