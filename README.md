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
5. **ML** (`src/sentinel/train.py`): disengaja menolak melatih model sebelum
   ada >=20 snapshot berlabel. Sebelum itu, indeks berbobot yang mengambil
   keputusan, dan bobotnya ditinjau tiap episode baru. Mengklaim ML sejak
   hari pertama dengan 4 data latih adalah kebohongan statistik.

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

Lisensi: MIT.
