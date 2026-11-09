# Dokumentasi

| Path | Isi |
|---|---|
| [images/](images/) | Diagram yang dipakai [README root](../README.md) (Modul 1–6) |
| [tugas-1/panduan.md](tugas-1/panduan.md) | Cara menjalankan Tugas 1: cluster, monitoring, toko, beban, collect |
| [tugas-1/rencana-riset.md](tugas-1/rencana-riset.md) | Tujuan, fenomena yang ditemukan, pertanyaan riset, rencana percobaan |
| [tugas-1/soal.pdf](tugas-1/soal.pdf) | Soal Tugas 1 |
| [tugas-1/infrastruktur.drawio](tugas-1/infrastruktur.drawio) | Diagram infrastruktur (buka dengan draw.io) |
| [tugas-1/analisis/](tugas-1/analisis/) | Laporan analisis (HTML dan PDF) dengan grafik di `figures/` |

Laporan analisis, urut menurut waktu:

1. `01-run-tunggal-burst-flash-sale` — satu run `burst-flash-sale` (26 Okt, satu pod per service).
2. `02-pemulihan-lambat-burst` — sembilan run dengan replica berbeda: pemulihan lambat dan kesiapan kapasitas.
3. `03-laporan-tugas-1` — laporan Tugas 1: scale-out reaktif datang setelah burst (29 run terencana).
4. `04-bottleneck-per-service` — analisis ulang data yang sama dari sisi service: `currencyservice` sebagai bottleneck (CPU di limit, pembagian beban timpang, restart).
