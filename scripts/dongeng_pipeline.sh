#!/bin/bash
# Pipeline lengkap 1 dongeng (v2): parse -> gambar -> TTS -> render split 2 VPS
#                                    -> join -> parts (intro/outro, 1.2x).
#
# RESUME-AWARE: tiap tahap dilewati kalau hasilnya sudah ada.
#   - story.json ada    -> skip parse
#   - gambar/TTS        -> idempoten (yang sudah ada dilewati)
#   - semua klip ada    -> skip render split
#   - video final ada   -> skip join
#   - parts ada         -> skip make_parts
#
# Pakai: dongeng_pipeline.sh <nomor> <nama-file-tanpa-.txt>
#   contoh: dongeng_pipeline.sh 004 004_naga-yang-menelan-matahari
set -euo pipefail

NO="${1:?nomor, mis 004}"
NAME="${2:?nama file tanpa .txt}"
CER=/root/json/cerpen
HOST="${RENDER_HOST:-light1}"
RDIR=/home/admin/cerpen_render
D="/root/json/dongeng/work/${NO}_sep2_test"
PY=/usr/bin/python3
PARTS_ROOT=/root/json/dongeng/parts
SRC="kendar:/root/dongeng_txt/new_naration/${NAME}.txt"

log(){ echo "[$(date '+%F %T')] $*"; }

mkdir -p "$D/assets"
log "== [$NO] $NAME"

# --- 1. naskah + bgm ---
[ -f "$D/naskah.txt" ] || scp -q -o BatchMode=yes "$SRC" "$D/naskah.txt"
cp -f /root/.hermes/skills/media/pipeline-cerpen/assets/bgm.mp3 "$D/assets/"

# --- 2. parse ---
if [ ! -f "$D/story.json" ]; then
  log "   parse"
  "$PY" "$CER/parse_dongeng_sep2.py" "$D/naskah.txt" --out "$D" --bgm assets/bgm.mp3
fi
N=$("$PY" -c "import json;print(len(json.load(open('$D/story.json'))['scenes']))")
SLUG=$("$PY" -c "import json;print(json.load(open('$D/story.json'))['slug'])")
log "   $N scene, slug=$SLUG"

# --- 3. gambar + TTS (idempoten) ---
log "   gambar (paralel multi-akun) + TTS (remote $HOST)"
"$PY" "$CER/gen_images_par.py" --dir "$D" --rpm 9 --conc 2 > "$D/gen_images.log" 2>&1
"$PY" /root/.hermes/skills/media/pipeline-cerpen/scripts/gen_tts.py \
      --dir "$D" --remote "$HOST" > "$D/gen_tts.log" 2>&1
tail -1 "$D/gen_images.log"; tail -1 "$D/gen_tts.log"

# --- 4. render split 2 VPS (hanya kalau ada klip yang kurang) ---
MISSING=$("$PY" - "$D" <<'PY'
import json,os,sys
D=sys.argv[1]; s=json.load(open(D+"/story.json"))
print(sum(1 for sc in s["scenes"] if not os.path.exists(f"{D}/clips/scene_{sc['n']:02d}.mp4")))
PY
)
if [ "$MISSING" -gt 0 ]; then
  SPLIT=$(( N / 2 ))
  log "   render split: VPS 1..$SPLIT | $HOST $((SPLIT+1))..$N (kurang $MISSING klip)"
  ssh -o BatchMode=yes "$HOST" "rm -rf $RDIR/proj && mkdir -p $RDIR/proj/images $RDIR/proj/tts"
  scp -q -o BatchMode=yes "$D/story.json" "$HOST:$RDIR/proj/story.json"
  rsync -a "$D/images/" "$HOST:$RDIR/proj/images/"
  rsync -a "$D/tts/"   "$HOST:$RDIR/proj/tts/"
  "$PY" "$CER/build_video_sep.py" --dir "$D" --scene-from 1 --scene-to $SPLIT \
        --clips-only --skip-existing > "$D/render_vps.log" 2>&1 &
  VPS_PID=$!
  ssh -o BatchMode=yes "$HOST" "cd $RDIR && $PY build_video_sep.py --dir $RDIR/proj \
        --scene-from $((SPLIT+1)) --scene-to $N --clips-only --skip-existing > render_light1.log 2>&1"
  wait $VPS_PID || { log "   GAGAL render VPS"; exit 1; }
  rsync -a "$HOST:$RDIR/proj/clips/" "$D/clips/"
else
  log "   semua klip sudah ada -> skip render"
fi

# --- 5. join + BGM ---
VID="$D/${SLUG}.mp4"
if [ ! -f "$VID" ]; then
  log "   join + BGM"
  "$PY" "$CER/build_video_sep.py" --dir "$D" --join-only > "$D/render_join.log" 2>&1
else
  log "   video final sudah ada -> skip join"
fi

# --- 6. parts ---
if ls "$PARTS_ROOT/$SLUG"/part_01.mp4 >/dev/null 2>&1; then
  log "   parts sudah ada -> skip"
else
  log "   bikin part (intro/outro, 1.2x)"
  "$PY" "$CER/make_parts.py" --dir "$D" --speed 1.2 --max-part 180 > "$D/make_parts.log" 2>&1
fi

log "== [$NO] SELESAI -> $PARTS_ROOT/$SLUG/"
ls -la "$PARTS_ROOT/$SLUG/"/*.mp4 2>/dev/null | awk '{print "   "$5" "$9}'
