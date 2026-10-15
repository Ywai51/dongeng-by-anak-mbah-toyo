#!/bin/bash
# Wrapper cron: Pipeline-Dongeng harian (2 cerita/hari).
# Jadwal: 02:00 waktu server (CST/UTC+8) = 01:00 WIB.
# flock mencegah tumpang-tindih kalau batch kemarin belum selesai.
set -u
LOG=/root/json/dongeng/daily_runner.log
LOCK=/root/json/dongeng/.daily.lock
PY=/usr/bin/python3

# cron PATH minimal -> pin interpreter + PATH yang sudah terverifikasi
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if ! "$PY" -c "import numpy, sqlite3" 2>/dev/null; then
  echo "[$(date '+%F %T')] FATAL: $PY tidak punya numpy/sqlite3" >> "$LOG"
  exit 1
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] masih jalan (batch sebelumnya belum selesai), skip" >> "$LOG"
  exit 0
fi

{
  echo "[$(date '+%F %T')] ===== batch harian mulai ====="
  nice -n 10 "$PY" /root/json/dongeng/daily_runner.py --count 2
  echo "[$(date '+%F %T')] ===== batch harian selesai (rc=$?) ====="
} >> "$LOG" 2>&1
