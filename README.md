# BBM Sentinel Jember

Sistem peringatan dini kelangkaan BBM untuk **Jember kota + kawasan kampus**
(Kecamatan Kaliwates, Sumbersari, Patrang). Bukan pemantau seluruh kabupaten.

Idenya sederhana: krisis BBM di Jember hampir tidak pernah datang tiba-tiba.
Dari 4 episode terdokumentasi (Juli 2025, Maret 2026, September 2026,
Oktober 2026, lihat `data/episodes.json`), selalu ada sinyal 1-5 hari
sebelumnya di lapis luar: jadwal tanker/geopolitik, kemacetan Ketapang,
gelombang Selat Bali, perbaikan Gumitir, lalu antrean di kabupaten tetangga.
Sistem ini membaca sinyal itu sebagai **angka**, menghitung indeks risiko,
dan memberi alert sebelum antrean terjadi. Saat krisis sudah berjalan,
sistem masuk mode krisis dan mengeluarkan buletin harian: status per jenis
BBM dan peringkat SPBU kota/kampus yang paling terdampak.

## Empat lapis sinyal

| Lapis | Sumber data | Bentuk angka |
|---|---|---|
| Global | Stooq / FRED (Brent), Frankfurter (USD/IDR), Google News RSS, GDELT (opsional) | perubahan harga 1d/7d (%), perubahan kurs 30d (%), volume berita 24j/72j |
| Nasional | Google News RSS (antrean SPBU nasional, kuota subsidi, pernyataan Pertamina/BPH Migas) | hitungan per jendela waktu + frasa stok kosong |
| Regional | Open-Meteo Marine + Forecast, Google News RSS (Banyuwangi, Bondowoso, Lumajang, Situbondo, Ketapang, Gumitir) | tinggi gelombang maks 72j (m), curah hujan Gumitir 72j (mm), volume berita |
| Lokal | Google News RSS Jember, pemindaian per SPBU, laporan lapangan dari pengguna | hitungan berita, panjang antrean terekstrak (m), waktu tunggu (jam), skor per SPBU 0-100 + keyakinan |

## Cara kerja

1. **Kolektor** (`src/sentinel/collectors/`) menarik data dan menyimpan
   *setiap* observasi mentah ke SQLite (`data/sentinel.db`). Riwayat inilah
   datasetnya: tanpa riwayat, tidak ada baseline dan tidak ada ML.
2. **Fitur + skor** (`src/sentinel/scoring.py`): setiap sinyal diubah ke
   0-100 lewat ramp ambang yang eksplisit di `config.json`, atau z-score
   terhadap baseline bergulir bila riwayat sudah cukup. Indeks risiko adalah
   rata-rata berbobot per lapis: regional 0,35, lokal 0,25, global 0,20,
   nasional 0,20. Angka-angka ini hanya hidup di lapis mesin; keluaran ke
   pengguna selalu bahasa awam (lihat poin mode krisis).
3. **Level**: HIJAU <40, KUNING 40-59, ORANYE 60-79, MERAH >=80.
4. **Mode krisis** (`src/sentinel/crisis.py`): aktif saat indeks >=60 atau
   antrean lokal terkonfirmasi. Menghasilkan `alerts/bulletin_latest.md`
   berbahasa awam: status sederhana, bensin yang susah dicari, SPBU yang
   sebaiknya dihindari / antre tapi jalan / masih lancar, dan satu saran.
   Tanpa indeks, skor, atau persentase. Isinya berasal dari status per
   jenis BBM dan peringkat SPBU dari
   `data/spbu_kota_jember.json` (11 SPBU kota/kampus).
5. **Prediksi bertanggal** (`src/sentinel/forecast.py`): proyeksi 7 hari
   dari tren indeks (basis median agar satu run anomali tidak menggerakkan
   ramalan), momentum lapis lokal+regional, faktor kalender (hari libur
   Indonesia di `data/holidays_id.json`, akhir pekan, kejadian terjadwal
   di `config.json:known_events`), dan lapisan analog historis. Slope
   diskalakan faktor kepercayaan berbasis rentang waktu observasi: data
   beberapa menit tidak boleh diekstrapolasi menjadi ramalan seminggu.
   Setiap prediksi disimpan dan diverifikasi terhadap realita hariannya
   (MAE berjalan dilaporkan, bukan diklaim).
6. **Belajar dari sejarah** (`src/sentinel/history.py` +
   `data/historical_episodes.json` + `data/historical_windows.json`):
   keempat episode terdokumentasi dikodekan menjadi vektor pemicu,
   durasi, dan jeda menuju puncak per pola (distribusi fisik 7-9 hari,
   puncak hari ke-2 s.d. ke-4; panik murni puncak ~1 hari, selesai 4
   hari). Pola pemicu hari ini - dihitung dari pemicu bernama yang
   ditambang kolektor berita (Gumitir, Ketapang, gelombang, tanker/
   geopolitik, panik/penimbunan, tetangga) - dibandingkan dengan semua
   episode selesai; episode terdekat meminjamkan jeda puncaknya untuk
   menanggalkan perkiraan puncak episode berjalan. Episode yang sedang
   berjalan tidak pernah dipakai melatih/menilai dirinya sendiri.
   Jendela arsip kuantitatif (kurs, hujan Gumitir, gelombang Ketapang +
   selatan; 14 hari sebelum s.d. 3 hari sesudah tiap episode) di-backfill
   dengan `python3 scripts/backfill_history.py`.
7. **ML** (`src/sentinel/train.py`): regresi logistik murni-Python
   dilatih per ruang fitur begitu ada >=20 contoh berlabel dan kedua
   kelas terisi - contoh episode (ruang pemicu) dan snapshot live (ruang
   lapis, dilabeli dari episode terdokumentasi). Sebelum itu, indeks
   berbobot + lapisan analog yang mengambil keputusan, dan status
   model dilaporkan apa adanya di `alerts/model_report.json`.
8. **Bukti visual ber-watermark** (`src/sentinel/imaging.py`): setiap
   foto antrean (snapshot CCTV publik, foto berita/media sosial, foto
   laporan warga) dibuatkan salinan berstempel tanpa mengubah piksel
   asli: strip judul + panel berisi nama/kode/alamat SPBU, tanggal dan
   jam WIB pengambilan (atau waktu diterima sistem, diberi label jujur
   sebagai itu), keadaan antrean dalam kata awam + panjang antrean bila
   memang tercatat, dan sumber gambar. Jejak audit: sidecar JSON +
   SHA-256 + tabel `evidence_images` + `alerts/evidence_latest.json`.
   Dicatat lewat `python3 scripts/watermark_evidence.py`.
9. **Computer vision penghitung kendaraan** (`src/sentinel/vision.py`):
   model YOLOv8 (COCO) diekspor ke ONNX dan dijalankan lokal dengan
   onnxruntime - tanpa GPU, tanpa layanan awan. Setiap foto antrean
   dianalisis per potongan (tiling) agar kendaraan jauh tetap terbaca,
   lalu kendaraan DIKLASIFIKASIKAN per jenis: motor, mobil, truk, bus,
   sepeda, plus orang. Hasil hitung masuk ke panel watermark ("Terdeteksi
   di foto: ..."), ke buletin, dan ke tabel bukti. Panjang antrean
   diperkirakan dari kendaraan yang terlihat (jarak antre baku per
   jenis) dan selalu dilabeli perkiraan - hitungan bersifat batas bawah
   karena foto hanya menangkap sebagian antrean. Model diambil/dibuat
   sekali dengan `python3 scripts/fetch_vision_model.py` (folder
   `models/` tidak masuk git). Dipakai lewat
   `scripts/watermark_evidence.py --vision`. Uji nyata 2026-10-13 pada
   foto antrean SPBU Tamiang (Wikimedia Commons): 28 orang, 1 motor,
   1 truk terdeteksi benar; foto dari dalam mobil yang kendaraannya
   tertutup dasbor terbaca sebagian - sesuai sifat batas bawah.

10. **Pemanen foto antrean otomatis** (`src/sentinel/collectors/images.py`):
   pengganti jalur CCTV yang tertutup. Saat mode krisis aktif (atau
   risiko >= ambang), pipeline memanen foto dari berita daring tentang
   antrean SPBU Jember (Bing News RSS -> gambar artikel/og:image), dengan
   gerbang geografis ketat: judul wajib menyebut "Jember" (uji langsung
   pertama menangkap foto Sukawati-Bali dan Kubu Raya-Kalimantan yang
   lolos kata kunci umum - keduanya ditolak dan dibersihkan). Foto yang
   lolos dihitung kendaraannya oleh lapisan computer vision, dianotasi,
   di-watermark sebagai bukti, dan masuk tabel bukti + buletin. Foto
   unggahan publik media sosial dapat diteruskan ke `alerts/inbox/`
   (nama berkas memuat kode SPBU untuk atribusi) dan diproses dengan
   jalur yang sama. Berjalan otomatis di dalam putaran pipeline;
   manual: `python3 scripts/harvest_images.py --force`. Uji langsung
   2026-10-14 dini hari: 3 foto Jember asli terpanen dan terhitung
   (salah satunya terbaca kode 54.681.25 pada papan harga di foto =
   SPBU Ahmad Yani, terverifikasi visual).

11. **Belajar berkelanjutan (ML)** (`src/sentinel/train.py`): setiap
   putaran pipeline kini menjalankan satu siklus belajar otomatis -
   jendela episode krisis dibuka otomatis saat krisis aktif dan ditutup
   setelah 72 jam tanpa krisis; snapshot diberi label setelah berumur
   5+ hari dari jendela episode terdokumentasi; model regresi logistik
   dilatih ulang begitu sebuah ruang fitur mencapai >=20 contoh
   berlabel dua kelas. Status jujur model selalu di
   `alerts/model_report.json` dan ringkasannya masuk
   `alerts/latest_run.json`. Waktu terbit foto bukti diambil dari
   `datePublished` halaman berita itu sendiri (RSS sebagian media
   mengisi tengah malam); bila jam memang tidak tercantum, panel
   watermark menyatakannya, tidak mengarang 00:00.

## Ketahanan jadwal (penting)

Penjadwalan TIDAK memakai systemd. VM tempat sistem ini berjalan diganti
secara berkala oleh platform dan berkas unit di /etc tidak bertahan -
terbukti 2026-10-13 23:57 WIB timer systemd hilang di tengah krisis dan
pipeline berhenti 1,5 jam tanpa ada yang tahu. Kini:

- Putaran per jam dijalankan cron Muse `bbm-sentinel-run` (milik goal,
  dipulihkan otomatis oleh runtime setelah penggantian VM); alert 3-jam
  oleh `bbm-sentinel-alert`, yang juga memeriksa kesegaran data dan
  menjalankan satu putaran pemulihan sendiri bila data basi >4 jam.
- Semua keadaan (kode, basis data, .venv, model vision) tinggal di
  direktori home yang persisten. `scripts/run_once.sh` berkunci flock +
  penjaga kesegaran 45 menit; `scripts/ensure_runtime.sh` membangun
  ulang .venv/onnxruntime bila hilang dan mencatat kesehatan ke
  `alerts/runtime_health.json`.
- Berkas unit di `systemd/` hanya referensi bila sistem ini suatu hari
  dipindah ke server sungguhan.

## Menjalankan

```sh
pip install -r requirements.txt
./scripts/run_once.sh            # satu putaran penuh
./scripts/run_once.sh --gdelt    # + lapisan GDELT (lambat, kena throttle)
python3 -m pytest tests/         # dari root repo, PYTHONPATH=src
PYTHONPATH=src python3 -m sentinel.train   # status kesiapan ML
```

Laporan lapangan (sinyal berbobot tertinggi) dicatat lewat:

```sh
python3 scripts/report_ground.py 54.681.18 Pertalite kosong "antrean 300 m" Krisna
```

## Jadwal otomatis

`systemd/bbm-sentinel.timer` menjalankan pipeline tiap jam di server.
Lapisan alert (Muse) memeriksa hasilnya berkala dan hanya bersuara ke
WhatsApp pengguna saat level naik atau buletin krisis terbit. Tidak ada
laporan kosong harian di luar mode krisis.

## Kejujuran data

- Pertamina **tidak** mempublikasikan stok per SPBU lewat API publik. Skor
  SPBU adalah *estimasi* dari laporan berita/media + laporan lapangan, dan
  selalu disertai angka keyakinan. Keyakinan rendah ditampilkan apa adanya.
- GDELT membatasi keras (429 adalah hal biasa). Kolektornya fail-soft dan
  bukan penopang pipeline.
- Angka ambang di `config.json` adalah titik awal dari 4 episode historis,
  bukan hasil optimasi. Kalibrasi adalah pekerjaan Fase 2.
- Backfill arsip Brent untuk jendela historis belum terisi: FRED berulang
  kali timeout dan Stooq tidak stabil dari server ini (kurs/hujan/
  gelombang lengkap). Menjalankan ulang `scripts/backfill_history.py`
  akan melengkapinya tanpa mengubah data lain.
- CCTV: hasil riset 2026-10-13 - TIDAK ADA feed publik yang mengarah ke
  SPBU mana pun di Jember. Jember memiliki 216 CCTV Polres/Pemkab (sejak
  2017, termasuk perempatan Mangli) tetapi hanya dipantau dari Command
  Center internal Polres; tidak ada portal publik (cctv.jemberkab.go.id
  tidak terkonfirmasi ada). CCTV SPBU Pertamina tidak memiliki akses
  publik di mana pun di Indonesia. CCTV Banyuwangi yang ter-stream ulang
  pihak ketiga (Patung Kuda, Simpang Lima) bukan area Ketapang/Gumitir
  dan nilainya kecil. Karena itu gambar antrean yang sah masuk sistem
  hanyalah foto media/sosial saat krisis dan foto laporan warga/pengguna
  - semuanya lewat watermark di atas.

Lisensi: MIT.

## Membedakan kendaraan antre vs sekadar lewat (v0.3.1)

Atas koreksi pengguna (foto Ahmad Yani: motor di jalan raya ikut
terhitung antre), `vision.classify_queue` kini menganalisis FORMASI
antrean sebelum menghitung: centroid kendaraan dikelompokkan secara
kerapatan (inti antrean = klaster terbesar), sumbu utama antrean
dipasang pada klaster itu (koridor), lalu kendaraan di luar koridor
yang tidak tersambung rantai formasi dinyatakan SEKADAR LEWAT dan
tidak dihitung. Pengaman khusus: kotak kecil (jauh di latar) yang
jauh dari inti antrean tidak pernah tersambung masuk — itulah ciri
kendaraan lewat di ruas jalan seberang. Bila kendaraan terlalu
sedikit untuk membaca formasi (<4), semua dihitung dan metodenya
dinyatakan terbuka (`formasi_kurang`). Hasilnya mengalir ke cap air
("Terdeteksi antre di foto: ..." dan baris "Sekadar lewat, tidak
dihitung: ..."), buletin, dan kolom `vehicle_counts` berbentuk
`{"queue": ..., "passing": ...}`. Pada foto Ahmad Yani: 8 motor
terhitung awal menyusut menjadi 4 motor antre + 4 motor lewat
(3 di antaranya persis yang ditunjuk pengguna).

Referensi tata letak satelit: `scripts/build_spbu_layout.py`
menyimpan mosaik citra satelit (Esri World Imagery z19, ~230 m)
untuk ke-11 SPBU di `data/satellite/` dan indeksnya di
`data/spbu_layout.json` (koordinat geocode + tingkat kecocokan +
catatan tata letak hasil telaah visual; SPBU Baratan terverifikasi
visual, Ahmad Yani dan Mastrip belum — titik geocode-nya jatuh di
permukiman dan perlu koreksi manual). Berkas ini adalah acuan
geometri stasiun untuk menilai foto, BUKAN pemantauan langsung:
satelit tetap tidak dapat memantau antrean secara waktu-nyata
(alasan lengkap di bagian satelit), dan pencocokan pose otomatis
foto berita ke citra satelit tidak andal — keputusan antre/lewat
dibuat dari formasi pada fotonya sendiri.

## Pola antrean SPBU (dasar pengetahuan v0.3.2)

Atas koreksi lanjutan pengguna (kendaraan besar di latar depan foto —
tetangga antrean si pengambil foto — sempat dinyatakan "lewat"),
`classify_queue` ditulis ulang di atas pola visual antrean BBM yang
ditelaah dari foto/video berita dan media sosial (Jember, Bali,
Palangka Raya, Balikpapan, Takengon):

1. Antrean adalah sebuah BARISAN: pengendara menunggu rapat
   bumper-ke-bumper, jadi keanggotaan diputuskan dari JARAK TEPI
   antar-kotak relatif terhadap ukuran kotak (tahan perspektif),
   bukan jarak titik tengah.
2. Antrean MELUBER: antrean panjang tumpah dari halaman SPBU ke
   badan jalan, bisa ratusan meter, sampai mengganggu lalu lintas.
   Berada di jalan TIDAK menggugurkan kendaraan; yang menggugurkan
   hanyalah keterputusan dari barisan.
3. Kamera biasanya berada DI DALAM antrean (pengendara yang menunggu
   merekam dari barisannya): kendaraan sangat besar yang terpotong
   tepi bawah bingkai adalah tetangga antrean pengambil foto dan
   dihitung antre, meski terdeteksi sebagian.
4. Pengendara yang duduk di atas kendaraannya tepat di ujung
   barisan memperpanjang barisan satu langkah.
Yang tersisa adalah lalu lintas lewat: kendaraan menyendiri atau
kelompok kecil terpisah, umumnya kecil di bingkai pada ruas jalan
seberang. Pada foto Ahmad Yani hasil akhirnya: 5 motor + 1 mobil +
1 truk antre (termasuk motor latar depan yang dikoreksi pengguna),
3 motor kecil di kejauhan dinyatakan lewat.

## v0.4 (2026-10-14): ground truth, social listening, calibration

- **Citizen ground truth (`ground_reports`)**: reports from the user /
  friends ("Ahmad Yani pertalite kosong") are recorded via
  `scripts/report_ground.py` (positional or `--text` free-form parsing;
  unparseable reports are rejected, never guessed). In station scoring
  a fresh report is the strongest signal with explicit decay: full
  authority 3h, floor x0.85 to 12h, x0.6 to 24h, ignored after; a
  fresh "normal" report caps the station score at 25; fuel-specific
  overrides apply for 6h; agreeing reports raise confidence. The
  bulletin marks report-backed stations "(laporan warga)".
- **Active learning (`learning.py`)**: every human correction of a
  vision count is stored in `vision_corrections` and appended to
  `data/vision_labels.jsonl`. Only human-verified counts become
  labels - the model never trains on its own output. The user's two
  corrections of 2026-10-14 (passing motorcycles; the photographer's
  own queue neighbour) are the first entries.
- **Social listening**: an agent sweep (cron `bbm-sentinel-social`,
  every 3h) counts PUBLIC posts about Jember SPBU queues
  (Instagram/Threads/Facebook; X/TikTok via web search) into
  `alerts/social_signals.json` - counts, timestamps, station names
  only, never commenter identities. `collectors/social.py` ingests it
  while fresh (<=6h) as the local-layer feature `social_lokal_posts`
  (saturates at 5 posts). First sweep, 2026-10-14 02:00 WIB: 16 queue
  posts in 24h, naming Ahmad Yani, Mangli, Mastrip.
- **Fine-tune readiness**: `scripts/build_vision_dataset.py` exports
  YOLO box labels ONLY where detector counts match human-verified
  counts exactly; `scripts/train_vision.py` refuses to train below
  150 boxed images and says how far away that is (currently 1).
  A trained `models/yolov8s_spbu.onnx` is preferred automatically.
- **Backtest (`backtest.py`)**: leave-one-out over the 3 closed
  episodes - analog picks (similarity 0.49/0.17/0.49) gave MAE
  duration 2.33 days and peak offset 1.67 days, vs median-baseline
  2.67/1.67. Dated forecasts therefore carry roughly +/-2 days of
  honest uncertainty at this sample size; `alerts/backtest_report.json`.
- **Satellite layout review completed**: coordinates for Ahmad Yani
  and Mastrip re-geocoded to named-PERTAMINA matches; all 11 tiles
  visually reviewed. Only Baratan's canopy is confirmed in imagery;
  Teuku Umar and Basuki Rahmat have candidate structures; the rest
  are honestly marked unidentifiable in current imagery (dense urban
  tiles, small canopies), and Kenanga's geocode is flagged the least
  reliable of the eleven (district mismatch - field check needed).
  No verification is fabricated; see `data/spbu_layout.json`.
