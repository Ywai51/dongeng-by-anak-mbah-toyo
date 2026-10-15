#!/usr/bin/env python3
"""Generate gambar dongeng PARALEL via BEBERAPA akun Agnes sekaligus.

Tiap akun Agnes (providerConnections.provider='agnes') dipaksa lewat header
`x-connection-id` -> kuota tiap akun terpisah, jadi throughput = jumlah akun x RPM.

Idempoten: gambar valid dilewati.
Pakai:
  python3 gen_images_par.py --dir <proyek> [--rpm 9] [--conc 2] [--size 1024x1792] [--force]
  python3 gen_images_par.py --dir <proyek> --status
"""
import argparse
import json
import os
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.request

ENV_FILE = "/root/.hermes/.env"
ROUTER = "http://127.0.0.1:20128/v1"
MODEL = "agnes/agnes-image-2.5-flash"
DB = "/root/.9router/db/data.sqlite"
DEFAULT_RPM = 9          # per AKUN
DEFAULT_CONC = 2         # request serentak per akun
MAX_RETRY = 6


def key():
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line.startswith("HERMES_CUSTOM_0_0_0_0_20128_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


KEY = key()


def agnes_accounts():
    """Semua akun Agnes aktif dari DB 9router, urut prioritas."""
    c = sqlite3.connect(DB)
    rows = list(c.execute(
        "SELECT id, name FROM providerConnections "
        "WHERE provider='agnes' AND isActive=1 ORDER BY priority, updatedAt"))
    c.close()
    return rows  # [(id, name), ...]


def valid_png(path):
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n" and os.path.getsize(path) > 10000
    except Exception:
        return False


def gen_once(prompt, size, conn_id):
    body = json.dumps({"model": MODEL, "prompt": prompt, "n": 1, "size": size}).encode()
    hdr = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
           "x-connection-id": conn_id}
    req = urllib.request.Request(ROUTER + "/images/generations", data=body, headers=hdr)
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


class Pacer:
    """Batasi laju per akun: jeda minimal `gap` detik antar request akun itu."""

    def __init__(self, gap):
        self.gap = gap
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next_t)
            self.next_t = t + self.gap
        d = t - now
        if d > 0:
            time.sleep(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getcwd())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rpm", type=float, default=DEFAULT_RPM, help="RPM per akun")
    ap.add_argument("--conc", type=int, default=DEFAULT_CONC, help="serentak per akun")
    ap.add_argument("--accounts", type=int, default=0, help="pakai N akun (0=semua)")
    ap.add_argument("--size", default=None)
    a = ap.parse_args()

    proj = os.path.abspath(a.dir)
    story = json.load(open(os.path.join(proj, "story.json"), encoding="utf-8"))
    size = a.size or story.get("size", "1024x1792")
    scenes = story["scenes"]
    outdir = os.path.join(proj, "images")
    logfile = os.path.join(proj, "gen_images.log")
    os.makedirs(outdir, exist_ok=True)
    lock = threading.Lock()

    def log(m):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
        with lock:
            print(line, flush=True)
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # daftar tugas
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

    accts = agnes_accounts()
    if a.accounts:
        accts = accts[:a.accounts]
    if not accts:
        log("TIDAK ADA akun Agnes aktif di 9router")
        return 1
    names = ", ".join(f"{n}({i[:8]})" for i, n in accts)
    gap = max(1.0, 60.0 / max(a.rpm, 0.1))
    log(f"=== mulai: {len(jobs)} gambar, {len(accts)} akun x rpm {a.rpm:g} x conc {a.conc} "
        f"(jeda {gap:.1f}s/akun) | akun: {names} ===")

    q = queue.Queue()
    for j in jobs:
        q.put(j)
    stat = {"ok": 0, "fail": 0, "skip": 0}
    t0 = time.time()

    def worker(acc_id, acc_name, pacer):
        while True:
            try:
                n, i, prompt, dest = q.get_nowait()
            except queue.Empty:
                return
            if valid_png(dest) and not a.force:
                with lock:
                    stat["skip"] += 1
                q.task_done()
                continue
            done = False
            for attempt in range(1, MAX_RETRY + 1):
                pacer.wait()
                url, err = gen_once(prompt, size, acc_id)
                if url:
                    try:
                        sz = download(url, dest)
                        if valid_png(dest):
                            with lock:
                                stat["ok"] += 1
                            log(f"  scene {n}_{i:02d} OK ({sz/1e6:.2f} MB) [{acc_name}]")
                            done = True
                            break
                        log(f"  scene {n}_{i:02d} file tidak valid, ulangi [{acc_name}]")
                    except Exception as e:
                        log(f"  scene {n}_{i:02d} download gagal: {type(e).__name__}: {e}")
                else:
                    log(f"  scene {n}_{i:02d} gagal (coba {attempt}) [{acc_name}]: {err}")
                time.sleep(min(15, 3 * attempt))
            if not done:
                with lock:
                    stat["fail"] += 1
                log(f"  scene {n}_{i:02d} GAGAL setelah {MAX_RETRY} percobaan")
            q.task_done()

    threads = []
    for acc_id, acc_name in accts:
        pacer = Pacer(gap)
        for _ in range(max(1, a.conc)):
            t = threading.Thread(target=worker, args=(acc_id, acc_name, pacer), daemon=True)
            t.start()
            threads.append(t)
    for t in threads:
        t.join()

    dt = time.time() - t0
    log(f"=== selesai: {stat['ok']} dibuat, {stat['fail']} gagal, {stat['skip']} dilewati "
        f"dalam {dt/60:.1f} menit ({stat['ok']/max(dt,1)*60:.1f} gambar/menit) ===")
    return 0 if stat["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
