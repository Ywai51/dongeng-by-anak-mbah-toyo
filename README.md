# Dongeng by Anak Mbah Toyo

Pipeline otomatis **naskah cerita/dongeng → video cerita vertikal 9:16 bersuara** untuk
YouTube, lalu dipecah menjadi **part-part** siap upload dengan **intro + outro**.

Dibuat oleh **Anak Mbah Toyo**.

---

## Alur pipeline

```
naskah .txt (format v2)
   │  parse_dongeng_sep2.py
   ▼
story.json  (scene + prompt gambar + narasi + BGM)
   │
   ├─ gen_images_par.py   → gambar per-scene (multi-akun Agnes via 9router, paralel)
   ├─ gen_tts.py          → suara narasi per-scene (edge-tts, remote host)
   ▼
build_video_sep.py        → klip per-scene + join (xfade) + BGM loop & ducking
   │  (bisa dibagi 2 mesin: --scene-from/--scene-to/--clips-only)
   ▼
video full-res  dongeng_<slug>.mp4
   │  make_parts.py
   ▼
part_01.mp4 … part_NN.mp4  ([intro] + [isi 1.2x] + [outro])
```

## Fitur

- **Subtitle per-kata**: KAPITAL, kuning + glow/outline putih (Poppins ExtraBold).
- **BGM loop + ducking** (volume turun otomatis saat narasi).
- **Ken Burns + xfade** halus antar gambar dalam satu scene.
- **Multi-akun Agnes** paralel (round-robin via header `x-connection-id` 9router).
- **Render dibagi 2 VPS** (separuh scene di tiap mesin, lalu digabung).
- **Part otomatis**: gabung scene sampai mendekati batas durasi (default ≤3 menit),
  tiap part diberi **intro** + **outro** (freeze frame + teks "LANJUT PART X" / "TAMAT"
  + sound effect + TTS).

## Script

| Script | Fungsi |
|---|---|
| `parse_dongeng_sep2.py` | naskah v2 → `story.json` (30–38 scene, 3 gambar/scene) |
| `gen_images_par.py` | generate gambar multi-akun Agnes (paralel, idempoten) |
| `gen_tts.py` | generate suara narasi per-scene (edge-tts) |
| `build_video_sep.py` | render klip per-scene + join + BGM; dukung render sebagian |
| `make_parts.py` | pecah video jadi part + intro/outro + speed 1.2x |
| `render_split.sh` | orkestrasi render dibagi 2 VPS |

## Cara pakai (ringkas)

```bash
D=/path/ke/proyek           # berisi naskah.txt + assets/bgm.mp3

python3 parse_dongeng_sep2.py $D/naskah.txt --out $D --bgm assets/bgm.mp3
python3 gen_images_par.py --dir $D --rpm 9 --conc 2
python3 gen_tts.py        --dir $D --remote <host-tts>
python3 build_video_sep.py --dir $D                       # video full
python3 make_parts.py      --dir $D --speed 1.2 --max-part 180
```

## Aset yang dibutuhkan

- `assets/bgm.mp3` — musik latar (di-loop).
- `intro.mp4` — video pembuka (di-scale ke 1080×1920/30fps).
- sound effect outro (mis. *quick-ting*) + voice TTS narator.

## Struktur folder keluaran

```
work/<slug>/
  naskah.txt  story.json
  images/     foto mentah PNG (scene_NN_XX.png)
  tts/        mp3 + json (timestamp per-kata)
  clips/      klip per-scene (scene_NN.mp4)
  subs/       subtitle .ass
  dongeng_<slug>.mp4       video final full-res
parts/<slug>/
  part_01.mp4 … part_NN.mp4
```

## Catatan

- Kecepatan: video akhir **1.2×** (`--speed`).
- Batas part default **180 s** (termasuk intro + outro) — kalau 1 scene bikin lewat,
  scene itu pindah ke part berikutnya.
- Subtitle selalu **per-kata, kapital, kuning + glow putih**.

## Lisensi

MIT.
