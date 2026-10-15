#!/bin/bash
# render_split.sh <proyek> [host=light1]
# Bagi 2 render: separuh scene di VPS-ini, separuh di light1, lalu join di VPS-ini.
#   - VPS-ini  : scene 1 .. SPLIT
#   - light1   : scene SPLIT+1 .. N   (clips-only, tanpa join/BGM)
#   - VPS-ini  : tarik klip light1 -> join semua + BGM -> video final
set -euo pipefail
D=$(readlink -f "${1:?pakai: render_split.sh <proyek> [host]}")
HOST="${2:-light1}"
SCRIPTS=/root/json/cerpen
RDIR=/home/admin/cerpen_render

N=$(python3 -c "import json;print(len(json.load(open('$D/story.json'))['scenes']))")
SPLIT=$(( N / 2 ))
echo "== $D : $N scene, split di $SPLIT (VPS 1..$SPLIT, $HOST $((SPLIT+1))..$N)"

# --- 1. VPS-ini render separuh pertama (klip saja) ---
echo "== [VPS-ini] render scene 1..$SPLIT"
python3 $SCRIPTS/build_video_sep.py --dir "$D" --scene-from 1 --scene-to $SPLIT --clips-only

# --- 2. kirim bahan ke light1 ---
echo "== kirim images/tts/story ke $HOST"
ssh -o BatchMode=yes "$HOST" "rm -rf $RDIR/proj && mkdir -p $RDIR/proj/images $RDIR/proj/tts"
scp -q -o BatchMode=yes "$D/story.json" "$HOST:$RDIR/proj/story.json"
rsync -a --info=progress2 "$D/images/" "$HOST:$RDIR/proj/images/"
rsync -a --info=progress2 "$D/tts/"   "$HOST:$RDIR/proj/tts/"

# --- 3. light1 render separuh kedua ---
echo "== [$HOST] render scene $((SPLIT+1))..$N"
ssh -o BatchMode=yes "$HOST" "cd $RDIR && python3 build_video_sep.py --dir $RDIR/proj --scene-from $((SPLIT+1)) --scene-to $N --clips-only"

# --- 4. tarik klip light1 ---
echo "== tarik klip dari $HOST"
mkdir -p "$D/clips"
rsync -a --info=progress2 "$HOST:$RDIR/proj/clips/" "$D/clips/"

# --- 5. join semua + BGM di VPS-ini ---
echo "== [VPS-ini] join + BGM"
python3 $SCRIPTS/build_video_sep.py --dir "$D" --join-only
echo "== SELESAI"
