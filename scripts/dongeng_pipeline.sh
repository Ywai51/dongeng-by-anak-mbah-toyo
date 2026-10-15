#!/bin/bash
# Pipeline lengkap 1 dongeng: parse -> gambar (paralel) -> TTS (remote) -> render split 2 VPS
#                          -> join -> parts (intro/outro, 1.2x).
#
# Pakai: dongeng_pipeline.sh <nomor> <nama-file-tanpa-.txt>
#   contoh: dongeng_pipeline.sh 004 004_naga-yang-menelan-matahari
#
# Sumber naskah: kendar:/root/dongeng_txt/new_naration/<nama>.txt
set -euo pipefail

NO="${1:?nomor, mis 004}"
NAME="${2:?nama file tanpa .txt}"
CER=/root/json/cerpen
HOST="${RENDER_HOST:-light1}"
RDIR=/home/admin/cerpen_render
D="/root/json/dongeng/work/${NO}_sep2_test"
SRC="kendar:/root/dongeng_txt/new_naration/${NAME}.txt"

log(){ echo "[$(date +%H:%M:%S)] $*"; }

mkdir -p "$D/assets"
log "== [$NO] tarik naskah dari kendar"
scp -q -o BatchMode=yes "$SRC" "$D/naskah.txt"
cp -f /root/.hermes/skills/media/pipeline-cerpen/assets/bgm.mp3 "$D/assets/"

log "== [$NO] parse"
python3 "$CER/parse_dongeng_sep2.py" "$D/naskah.txt" --out "$D" --bgm assets/bgm.mp3

log "== [$NO] gambar (multi-akun paralel) + TTS (remote $HOST) BERSAMAAN"
python3 "$CER/gen_images_par.py" --dir "$D" --rpm 9 --conc 2 > "$D/gen_images.log" 2>&1 &
IMG_PID=$!
python3 /root/.hermes/skills/media/pipeline-cerpen/scripts/gen_tts.py \
        --dir "$D" --remote "$HOST" > "$D/gen_tts.log" 2>&1 &
TTS_PID=$!
wait $IMG_PID || { log "GAGAL gambar"; exit 1; }
wait $TTS_PID || { log "GAGAL tts"; exit 1; }
log "   gambar+tts selesai"

# ---- render dibagi 2 VPS ----
N=$(python3 -c "import json;print(len(json.load(open('$D/story.json'))['scenes']))")
SPLIT=$(( N / 2 ))
log "== [$NO] render split: VPS 1..$SPLIT | $HOST $((SPLIT+1))..$N"

log "   kirim bahan ke $HOST"
ssh -o BatchMode=yes "$HOST" "rm -rf $RDIR/proj && mkdir -p $RDIR/proj/images $RDIR/proj/tts"
scp -q -o BatchMode=yes "$D/story.json" "$HOST:$RDIR/proj/story.json"
rsync -a "$D/images/" "$HOST:$RDIR/proj/images/"
rsync -a "$D/tts/"   "$HOST:$RDIR/proj/tts/"

log "   render BERSAMAAN (VPS + $HOST)"
python3 "$CER/build_video_sep.py" --dir "$D" --scene-from 1 --scene-to $SPLIT --clips-only \
        > "$D/render_vps.log" 2>&1 &
VPS_PID=$!
ssh -o BatchMode=yes "$HOST" "cd $RDIR && python3 build_video_sep.py --dir $RDIR/proj \
        --scene-from $((SPLIT+1)) --scene-to $N --clips-only > render_light1.log 2>&1"
wait $VPS_PID || { log "GAGAL render VPS"; exit 1; }

log "   tarik klip dari $HOST"
rsync -a "$HOST:$RDIR/proj/clips/" "$D/clips/"

log "== [$NO] join + BGM"
python3 "$CER/build_video_sep.py" --dir "$D" --join-only > "$D/render_join.log" 2>&1

log "== [$NO] bikin part (intro/outro, 1.2x)"
python3 "$CER/make_parts.py" --dir "$D" --speed 1.2 --max-part 180 > "$D/make_parts.log" 2>&1

log "== [$NO] SELESAI. Part di: /root/json/dongeng/parts/<slug>/"
tail -3 "$D/make_parts.log"
