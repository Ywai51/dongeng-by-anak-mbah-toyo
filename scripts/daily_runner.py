#!/usr/bin/env python3
"""Runner harian Pipeline-Dongeng: proses N naskah v2 berikutnya dari kendar.

Dipanggil cron 02:00 CST (01:00 WIB). Idempoten: naskah yang sudah tercatat
'done' dilewati. Notifikasi Telegram saat mulai + tiap cerita selesai.

Pakai:
  python3 daily_runner.py [--count 2] [--dry]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/root/json")
import tg_send  # noqa: E402

SRC_DIR = "/root/dongeng_txt/new_naration"       # di kendar
CER = "/root/json/cerpen"
PIPE = f"{CER}/dongeng_pipeline.sh"
STATE = "/root/json/dongeng/daily_state.json"
LOG = "/root/json/dongeng/daily_runner.log"
CHAT = "1113863551"
WORK = "/root/json/dongeng/work"
PARTS = "/root/json/dongeng/parts"


def log(msg):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(text):
    try:
        return tg_send.send(text, chat=CHAT)
    except Exception as e:
        log(f"notify gagal: {e}")
        return None


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"done": [], "failed": {}}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def list_sources():
    """Daftar nama file (tanpa .txt) di kendar, urut by nomor."""
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                        "kendar", f"ls {SRC_DIR}/*.txt 2>/dev/null"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ssh kendar gagal: {r.stderr[:200]}")
    names = []
    for line in r.stdout.splitlines():
        b = os.path.basename(line.strip())
        if b.endswith(".txt"):
            names.append(b[:-4])

    def key(n):
        m = re.match(r"(\d+)", n)
        return (int(m.group(1)) if m else 9999, n)

    return sorted(names, key=key)


def run_one(name):
    m = re.match(r"(\d+)", name)
    no = m.group(1) if m else name
    log(f"--- proses {name} (no={no})")
    r = subprocess.run(["bash", PIPE, no, name],
                       capture_output=True, text=True)
    tail = (r.stdout or "")[-1500:]
    if r.returncode != 0:
        log(f"GAGAL {name} rc={r.returncode}\n{tail}\n{(r.stderr or '')[-500:]}")
        return False, tail
    log(f"SELESAI {name}\n{tail}")
    return True, tail


def parts_summary(slug):
    d = os.path.join(PARTS, slug)
    if not os.path.isdir(d):
        return None
    ps = sorted(f for f in os.listdir(d) if f.endswith(".mp4") and "_tg" not in f)
    if not ps:
        return None
    total = 0
    for p in ps:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "default=nw=1:nk=1",
                            os.path.join(d, p)], capture_output=True, text=True)
        try:
            total += float(r.stdout.strip())
        except Exception:
            pass
    return len(ps), total, d


def slug_of(no):
    p = os.path.join(WORK, f"{no}_sep2_test", "story.json")
    try:
        return json.load(open(p, encoding="utf-8"))["slug"]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    st = load_state()
    done = set(st.get("done", []))
    try:
        srcs = list_sources()
    except Exception as e:
        log(f"FATAL: {e}")
        notify(f"Pipeline Dongeng harian GAGAL\nTidak bisa ambil daftar naskah dari kendar.\n{e}")
        return 1

    todo = [n for n in srcs if n not in done]
    log(f"total naskah: {len(srcs)} | sudah: {len(done)} | sisa: {len(todo)}")
    if not todo:
        log("antrian habis")
        notify(f"Pipeline Dongeng: antrian HABIS\nSemua {len(srcs)} naskah sudah diproses.")
        return 0

    batch = todo[:a.count]
    log(f"batch hari ini: {batch}")
    if a.dry:
        print("DRY:", batch)
        return 0

    notify(f"Pipeline Dongeng MULAI\n{len(batch)} cerita: {', '.join(batch)}\n"
           f"Sisa antrian: {len(todo)}")

    ok_n, fail_n = 0, 0
    for name in batch:
        ok, _ = run_one(name)
        no = re.match(r"(\d+)", name).group(1)
        if ok:
            done.add(name)
            st["done"] = sorted(done)
            save_state(st)
            ok_n += 1
            slug = slug_of(no)
            info = parts_summary(slug) if slug else None
            if info:
                n, tot, d = info
                notify(f"Selesai: {name}\n{n} part, total {tot/60:.1f} menit\n"
                       f"Folder: {d}")
            else:
                notify(f"Selesai: {name}\n(part tidak ditemukan, cek log)")
        else:
            fail_n += 1
            st.setdefault("failed", {})[name] = time.strftime("%F %T")
            save_state(st)
            notify(f"GAGAL: {name}\nLihat {LOG}")

    sisa = len(todo) - ok_n
    log(f"== selesai batch: {ok_n} ok, {fail_n} gagal, sisa {sisa}")
    notify(f"Pipeline Dongeng batch SELESAI\n{ok_n} berhasil, {fail_n} gagal\n"
           f"Sisa antrian: {sisa}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
