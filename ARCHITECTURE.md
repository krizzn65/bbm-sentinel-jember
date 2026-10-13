# Arsitektur

```
                 GLOBAL                    NASIONAL
  Brent, USD/IDR, volume berita,    volume berita antrean SPBU,
  GDELT (opsional)                  kuota & pernyataan resmi
        \                                /
         \                              /
          REGIONAL (bobot tertinggi)        LOKAL
  gelombang Selat Bali & laut selatan,   berita Jember, pindai 11 SPBU
  hujan koridor Gumitir, berita          kota/kampus, laporan lapangan
  Ketapang/Gumitir/tetangga                       |
        \______________  _________________________|
                        v
              SQLite feature store
        (semua observasi mentah + baseline)
                        v
           fitur -> ramp ambang / z-score
                        v
              indeks risiko 0-100
              HIJAU / KUNING / ORANYE / MERAH
                   /               \
        indeks >= 60 atau      mode normal:
        antrean terkonfirmasi  diam, dataset bertambah
                   v
              MODE KRISIS
        buletin harian: per jenis BBM,
        peringkat SPBU kota/kampus
                   v
        alert ke pengguna (WhatsApp)

Lapisan prediksi bertanggal (forecast.py):
  tren teredam + faktor kepercayaan rentang observasi + kalender libur
  + ANALOG HISTORIS (history.py): pola pemicu hari ini dicocokkan ke
  episode terdokumentasi (data/historical_episodes.json); episode
  terdekat menentukan perkiraan tanggal puncak & durasi.

Lapisan bukti visual (imaging.py):
  foto CCTV publik / media / laporan warga -> salinan ber-watermark
  (SPBU, tanggal+jam WIB, keadaan antrean, sumber) + sidecar SHA-256
  -> evidence_images + alerts/evidence_latest.json -> dilampirkan
  pada alert yang mengutipnya.
```

## Keputusan desain

- **Angka dulu, teks kemudian.** Berita diubah menjadi hitungan per jendela
  waktu, frasa terekstrak (panjang antrean, waktu tunggu, kata stok) dan
  skor. Teks judul hanya disimpan sebagai contoh bukti, bukan sebagai sinyal.
- **Regional diberi bobot terbesar (0,35).** Sejarah Jember menunjukkan
  penentu akhirnya selalu distribusi fisik dari Tanjungwangi lewat dua titik
  sumbat: Gumitir dan Ketapang. Sinyal global tanpa gangguan regional
  terbukti tidak cukup (episode Maret 2026 reda dalam 4 hari tanpa WFH).
- **Setiap run adalah satu baris dataset.** Fitur saat ini + label hasil
  (krisis terkonfirmasi dalam 5 hari) adalah bahan training Fase 2.
- **Fail-soft di semua kolektor.** Satu sumber mati tidak boleh membunuh
  putaran; error dicatat sebagai observasi, bukan exception fatal.
- **Cakupan SPBU dibatasi dengan sengaja.** 11 SPBU di 3 kecamatan kota.
  Menambah SPBU pelosok menaikkan noise dan biaya pindai tanpa menambah
  manfaat bagi pengguna yang beraktivitas di kota/kampus.
