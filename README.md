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
