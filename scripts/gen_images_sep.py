#!/usr/bin/env python3
"""Pipeline-Cerpen tahap 1 (format BARU): generate 6 gambar per scene via Agnes.

Tiap scene punya "prompts": [6 prompt] -> hasil: images/scene_NN_01.png .. _06.png

Rate limit Agnes 1K = 10 req/menit. Default --rpm 9 (aman).
Idempoten: gambar valid dilewati.

Pakai:
  python3 gen_images_sep.py [--dir <proyek>] [--rpm 9] [--size 1024x1792] [--force]
  python3 gen_images_sep.py --status
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

ENV_FILE = "/root/.hermes/.env"
ROUTER = "http://127.0.0.1:20128/v1"
MODEL = "agnes/agnes-image-2.5-flash"
DEFAULT_RPM = 9
MAX_RETRY = 6


def key():
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line.startswith("HERMES_CUSTOM_0_0_0_0_20128_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


KEY = key()


def valid_png(path):
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n" and os.path.getsize(path) > 10000
    except Exception:
        return False


def gen_once(prompt, size):
    body = json.dumps({"model": MODEL, "prompt": prompt, "n": 1, "size": size}).encode()
    req = urllib.request.Request(
        ROUTER + "/images/generations", data=body,
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        return d["data"][0]["url"], None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:150]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            f.write(c)
    return os.path.getsize(dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getcwd())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rpm", type=float, default=DEFAULT_RPM)
    ap.add_argument("--size", default=None)
    a = ap.parse_args()

    proj = os.path.abspath(a.dir)
    story = json.load(open(os.path.join(proj, "story.json"), encoding="utf-8"))
    size = a.size or story.get("size", "1024x1792")
    scenes = story["scenes"]
    outdir = os.path.join(proj, "images")
    logfile = os.path.join(proj, "gen_images.log")
    gap = max(1.0, 60.0 / max(a.rpm, 0.1))
    os.makedirs(outdir, exist_ok=True)

    def log(m):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
        print(line, flush=True)
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # daftar tugas (scene, idx, prompt)
    jobs = []
    for s in scenes:
        for i, p in enumerate(s["prompts"], 1):
            dest = os.path.join(outdir, f"scene_{s['n']:02d}_{i:02d}.png")
            if a.force or not valid_png(dest):
                jobs.append((s["n"], i, p, dest))

    if a.status:
        tot = sum(len(s["prompts"]) for s in scenes)
        ada = sum(1 for s in scenes for i in range(1, len(s["prompts"]) + 1)
                  if valid_png(os.path.join(outdir, f"scene_{s['n']:02d}_{i:02d}.png")))
        print(f"gambar: {ada}/{tot} ada")
        return 0

    log(f"=== mulai: {len(jobs)} gambar perlu dibuat (size {size}, {a.rpm:g} req/mnt) ===")
    ok = 0
    for j, (n, i, prompt, dest) in enumerate(jobs, 1):
        log(f"[{j}/{len(jobs)}] scene {n} gambar {i} ...")
        done = False
        for attempt in range(1, MAX_RETRY + 1):
            url, err = gen_once(prompt, size)
            if url:
                try:
                    sz = download(url, dest)
                    if valid_png(dest):
                        log(f"  scene {n}_{i:02d} OK ({sz/1e6:.2f} MB)")
                        ok += 1
                        done = True
                        break
                    log(f"  scene {n}_{i:02d} file tidak valid, ulangi")
                except Exception as e:
                    log(f"  scene {n}_{i:02d} download gagal: {type(e).__name__}: {e}")
            else:
                log(f"  scene {n}_{i:02d} gagal (coba {attempt}): {err}")
            time.sleep(15)
        if not done:
            log(f"  scene {n}_{i:02d} GAGAL setelah {MAX_RETRY} percobaan")
        if j < len(jobs):
            time.sleep(gap)
    log(f"=== selesai: {ok}/{len(jobs)} gambar dibuat ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
