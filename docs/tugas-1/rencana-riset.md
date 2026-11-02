# Rencana riset — pemulihan lambat dan kesiapan kapasitas saat burst

Dokumen kerja untuk Tugas 1 (Online Boutique). Menggabungkan tujuan, fenomena yang sudah ditemukan, dan rencana percobaan yang terukur. Cara menjalankan alat ada di [panduan.md](panduan.md). Penjelasan fenomena beserta grafik ada di [analisis/02-pemulihan-lambat-burst.pdf](analisis/02-pemulihan-lambat-burst.pdf).

---

## 1. Tujuan

**Tujuan tugas** (dari [panduan.md](panduan.md) bagian 1):

| Bagian | Yang harus ada |
|---|---|
| 1 — Environment | Cluster, monitoring, dan toko jalan. Dua run (`constant`, `burst-flash-sale`) dengan metrik pada window yang sama. |
| 2 — Satu perilaku | Satu fenomena dari data (workload ↔ resource ↔ performance) dengan evidence angka. |
| 3 — Research problem | Satu pertanyaan riset yang lahir dari fenomena itu. |

**Tujuan riset** (usulan untuk Bagian 3 dan tugas lanjutan): memahami dan memperpendek jarak antara “pod sudah ada” dan “pod sudah melayani dengan sehat” saat burst flash sale. Perbaikan yang dicari ada di sisi infrastruktur (sinyal autoscaling, pre-scale, warm-up, ingress), bukan sekadar menambah jumlah pod.

**Kriteria keberhasilan**, ditetapkan sebelum run supaya hasil tidak diinterpretasi ulang sesudahnya:

- SLO: p95 < 300 ms dan request gagal < 1%.
- Lead time: detik dari burst mulai sampai p95 sehat bertahan.
- Ukuran lain: total request gagal, p95 puncak, dan waktu pulih setelah puncak berakhir.

---

## 2. Fenomena yang ditemukan

Sumber: sembilan run `burst-flash-sale` (R1–R9, 26 dan 29 Oktober) dengan replica berbeda-beda. Profil: 10 RPS selama 120 detik, 400 RPS selama 60 detik, turun linier ke 10 RPS sampai detik 540. R9 memakai 100 → 600 RPS, jadi tidak dibandingkan langsung. Run ini dilakukan tanpa rencana dan hanya dipakai untuk menemukan fenomena, bukan sebagai hasil akhir.

| Run | Pod | Gagal saat burst | p95 median saat burst (ms) | Beban saat p95 pulih (RPS) | Umur frontend (menit) |
|---|---|---|---|---|---|
| R1 · 26/10 | 11 | 99% | 24 ¹ | 76 | 47 |
| R2 · 12:38 | 15 | 100% | 5025 | 116 | 18 |
| R3 · 13:27 | 23 | 98% | 5032 | 177 | 67 |
| R4 · 13:56 | 36 | 44% | 5029 | 180 | 6 |
| R5 · 14:20 | 67 | 0% | 489 | 207 | 17 |
| R6 · 14:36 | 98 | 0% | 1005 | 77 | 21 |
| R7 · 14:48 | 67 | 0% | 357 | 187 | 45 |
| R8 · 14:59 | 36 | 0% | 593 | 163 | 57 |
| R9 · 23:12 | 36 | 28% | 5028 | 264 | 549 |

¹ p95 rendah karena 99% request gagal cepat, bukan tanda sehat. p95 ≈ 5000 ms berarti request mencapai timeout generator.

### Temuan 1 — pod menghapus kegagalan, bukan latency

Dari 11 sampai 67 pod, request gagal saat burst turun dari hampir seluruhnya ke nol. Pada empat run tanpa gagal, p95 median saat burst masih 357–1005 ms, sekitar 10–30 kali kondisi normal (30–37 ms). Menambah pod dari 67 ke 98 tidak memperbaiki apa pun (489 → 1005 ms). CPU ingress-nginx hanya 0,3–0,4 core dan CPU total toko puncaknya 5,4 core dari 12 core host, jadi tidak ada bukti host atau ingress jenuh.

### Temuan 2 — latency tertinggal di belakang beban

p95 baru di bawah 300 ms saat beban sudah turun ke 76–264 RPS, yaitu 178–299 detik setelah puncak berakhir. Ini pola antrean yang belum terkuras. Datanya hanya punya satu arah (beban turun), jadi istilah histeresis belum boleh dipakai sebelum ada uji naik-turun bertahap (Fase 1).

### Temuan 3 — konfigurasi sama, hasil berbeda (hipotesis)

R4 dan R8 memakai replica identik (frontend 8, currency 10, productcatalog 5, cart 4, ad 3, total 36 pod). Hasilnya gagal 44% vs 0%. Yang berbeda adalah riwayatnya: R4 datang tepat setelah scale up dari 23 pod (pod frontend berumur sekitar 6 menit), R8 datang setelah scale down dari 67 pod (sekitar 57 menit). Dugaan: pod yang sudah Ready belum tentu hangat. Bukti baru satu pasang run, jadi statusnya hipotesis. Umur pod tidak berurutan dengan p95 pada run lain, sehingga faktor lain masih mungkin berperan.

---

## 3. Pertanyaan riset

> Pada burst 3–4 kali beban normal, berapa lama kapasitas tambahan baru benar-benar melayani dengan p95 sehat (lead time dari burst mulai), komponen mana yang paling besar menyumbangnya, dan strategi infrastruktur apa yang paling banyak memotongnya sambil menjaga request tetap berhasil?

Komponen lead time yang diukur terpisah: deteksi sinyal, keputusan scale, penjadwalan pod, penarikan image, startup, dan warm-up sampai p95 sehat.

Strategi yang dibandingkan: HPA berbasis CPU, HPA berbasis RPS atau in-flight request (KEDA), pre-scale terjadwal, pre-scale plus warm-up, dan opsional load shedding di ingress.

---

## 4. Rencana percobaan

### 4.1 Prinsip

1. Hasil dan SLO didefinisikan sebelum run (bagian 1).
2. Satu faktor diubah per kali, sisanya dikunci.
3. Replikasi minimal 3 per sel, supaya ada ukuran variasi. R4 vs R8 menunjukkan perlunya.
4. Prosedur reset yang sama sebelum setiap run:
   - scale ke setting target dan tunggu semua pod Ready;
   - pemanasan 5 menit pada 25 RPS;
   - cooldown sampai p95 stabil;
   - urutan run diacak, supaya kondisi pod dingin atau hangat tidak terbawa dari run sebelumnya.
5. Replica tiap run ditulis ke `metadata.json` (sekarang `unspecified`).

### 4.2 Setting pod

Memakai konfigurasi yang sudah pernah dijalankan, supaya terbukti bisa di-deploy.

| Setting | Total pod | Isi |
|---|---|---|
| S1 (baseline) | 15 | frontend 5, service lain 1 |
| S2 | 36 | frontend 8, currency 10, productcatalog 5, cart 4, ad 3, sisanya 1 |
| S3 | 67 | frontend 16, currency 20, productcatalog 10, cart 8, ad 6, redis 2, sisanya 1 |

### 4.3 Fase

| Fase | Isi | Run | Keluaran |
|---|---|---|---|
| 0. Persiapan | Perbaiki agregasi collector (jumlah antar pod, bukan rata-rata). Tulis replica ke metadata. Catat status code ingress. Tulis skrip yang me-reset dan menjalankan satu run. | 0 | Prosedur yang bisa diulang |
| 1. Kapasitas | Step load naik lalu turun (10, 25, 50, 100, 150, 200 RPS, 60–90 detik per tahap) pada S1, S2, S3, masing-masing 2 kali. | 6 | Titik lutut C per setting, apakah kapasitas naik linear terhadap pod, dan histeresis naik vs turun |
| 2. Burst statik | Tanpa autoscaler. Setting {S1, S2, S3} × burst {3×, 4×} dari L0, masing-masing 3 kali. L0 adalah RPS tertinggi di mana S1 masih memenuhi SLO (dari Fase 1). Tambah pembanding dingin vs hangat di S2 pada 4×, 3 kali per kondisi. | 18 + 6 | Pengaruh pod dan burst, bukti ada atau tidaknya efek pod dingin |
| 3. Autoscale | Pada burst 4×: HPA CPU, HPA RPS atau in-flight, pre-scale terjadwal, pre-scale plus warm-up, masing-masing 3 kali. | 12 | Lead time per strategi |

Total sekitar 42 run. Satu run efektif sekitar 20 menit (600 detik uji ditambah reset dan pemanasan), jadi sekitar 14 jam.

**Versi ringkas untuk Tugas 1:** Fase 0, 1, dan 2 tanpa sel 3× (6 + 9 + 6 = 21 run, sekitar 7 jam). Cukup untuk Bagian 2 dan 3 dengan angka yang terukur.

### 4.4 Keputusan yang masih terbuka

- Waktu yang tersedia. Kalau terbatas, Fase 1 saja sudah memberi kapasitas per setting, linearitasnya, dan ada tidaknya histeresis.
- Batas pengumpulan Tugas 1, dan apakah Fase 3 boleh masuk. [panduan.md](panduan.md) bagian 3.4 melarang mengubah replica dan memasang autoscaler pada baseline Tugas 1, jadi Fase 2 (mengubah replica) dan Fase 3 (autoscaler) perlu konfirmasi bahwa aturan itu hanya berlaku untuk dua run baseline.

---

## 5. Batasan data yang sudah ada

- Satu run per konfigurasi, tanpa replikasi.
- p95 diukur di sisi generator beban dan dibatasi timeout sekitar 5 detik. Request yang gagal cepat ikut menurunkan p95.
- Replica diubah manual antar run, run berurutan sehingga membawa riwayat, dan generator beban berjalan di mesin yang sama dengan cluster kind.
- Kolom CPU, memory, dan network di `combined.csv` adalah rata-rata per pod, bukan total (agregasi di `collector/collect.py` merata-ratakan seri). CPU total dihitung ulang dari file per-pod di `metrics/`.
- Metrik `CPU_THROTTLED` tidak mengembalikan data, jadi throttling tidak bisa dinilai.
- Replica per service dibaca dari Prometheus (`kube_deployment_spec_replicas`) pada window tiap run.
