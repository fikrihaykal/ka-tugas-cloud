# Tugas 1 — Online Boutique (normal vs flash sale)

Panduan lengkap terpisah dari README root. README hanya merujuk ke file ini.

**System under test:** Online Boutique (microservices e-commerce).  
**Kondisi normal:** profil workload `constant`.  
**Event flash sale:** profil workload `burst` ke URL yang sama.  
**Deliverable inti:** dua folder hasil eksperimen, masing-masing berisi `workload.csv`, `metadata.json`, `measurement-window.env`, dan setelah collect: `combined.csv`.

```text
~/project/
├── ka-tugas-cloud/                 ← repo lab (cluster, script, results)
└── ka-ecommerce-microservices/     ← sibling wajib (manifest release toko)
```

Kedua repo harus berdampingan. Image toko **publik** (tidak di-build). Jangan deploy aplikasi lab lain di namespace `cloud-dynamics` bersamaan dengan toko.

---

## 1. Apa yang dinilai (ringkas)

| Bagian | Yang harus ada |
|---|---|
| **1 — Environment** | Cluster + monitoring + toko jalan; dua run (`constant`, `burst`); metrik terkumpul pada window yang sama |
| **2 — Satu perilaku** | Satu fenomena dari data (workload ↔ resource ↔ performance), dengan evidence angka |
| **3 — Research problem** | Satu pertanyaan riset yang lahir dari fenomena itu |

Brief canvas: checklist progres lab. Rubrik soal ada di canvas/brief; file ini adalah **cara menjalankan alatnya**.

---

## 2. Peta alat — siapa ngapain

Eksperimen ini bukan “satu website”. Ada beberapa lapisan. Kalau bingung kenapa banyak URL, baca tabel ini dulu.

| Lapisan | Alat | Fungsi | URL / cara akses |
|---|---|---|---|
| Hypervisor lokal untuk K8s | **Docker** + **kind** | Menjalankan node Kubernetes sebagai container Docker | CLI: `kind get clusters` |
| Orkestrasi | **Kubernetes** (`kubectl`) | Menjadwalkan pod, service, ingress | CLI |
| Package chart | **Helm** | Memasang stack monitoring (`kube-prometheus-stack`) | CLI: `helm list -n monitoring` |
| Masuk HTTP ke cluster | **ingress-nginx** | Meneruskan host `*.sslip.io` ke service | Port host **80** / **443** |
| Aplikasi under test | **Online Boutique** | Toko multi-service yang di-load | http://online-boutique.127.0.0.1.sslip.io/ |
| Generate beban | **cloud-dynamics-experiments** | `constant` / `burst` → `workload.csv` | Script Python loadgen |
| Time-series metrics | **Prometheus** | Menyimpan metrik cluster/pod; di-query saat collect | http://prometheus.127.0.0.1.sslip.io/ |
| Dashboard visual | **Grafana** | Grafik dari Prometheus (CPU, memory, dll.) | http://grafana.127.0.0.1.sslip.io/ |
| Browser cluster | **Octant** | Lihat namespace, pod, log, deployment | http://127.0.0.1:22222/ |
| Gabung metrik + workload | **cloud-dynamics-metrics** | Tarik PromQL untuk window ukur → `combined.csv` | Script |

**Bukan website:**

| Nama | Kenapa bukan web |
|---|---|
| **kind** | Program CLI yang membuat cluster. Tidak ada UI kind. |
| **Helm** | Package manager CLI. Tidak ada UI Helm di lab ini. |
| **kubectl** | CLI untuk bicara ke API Kubernetes. |

---

## 3. Tutorial tiap komponen

Semua perintah di bawah diasumsikan dari **root repo** `ka-tugas-cloud`, kecuali disebutkan lain.

### 3.1 Env shell (wajib tiap terminal baru)

```bash
# HOST — dari root ka-tugas-cloud
export PATH="$PWD/kubernetes/bin:$PATH"
export KUBECONFIG="$PWD/kubernetes/setup-cluster/kind/kubeconfig"
export HOST_IP="${HOST_IP:-127.0.0.1}"
```

`export` di dalam `sh 2-set-config.sh` **tidak** masuk ke shell pemanggil. Terminal baru harus set ulang.

Cek:

```bash
kind version
kubectl version --client
helm version
kubectl get nodes
```

Harus ada 4 node Ready: `mylab99-control-plane` + 3 worker.

### 3.2 kind — cluster Kubernetes lokal

**Fungsi:** menjalankan Kubernetes di laptop tanpa VM berat. Tiap “node” = satu container Docker. Cluster lab bernama **`mylab99`**.

**Buat (sekali, Modul 6.1):**

```bash
cd kubernetes/bin && sh download.sh && source set.sh
cd ../setup-cluster/kind
sh 1-create-cluster.sh
sh 2-set-config.sh
export KUBECONFIG="$PWD/kubeconfig"
```

`1-create-cluster.sh` menaikkan `fs.inotify.max_user_*` (butuh `sudo`). Nilai **tidak persist** setelah reboot WSL — lihat §8.

**Cek:**

```bash
kind get clusters
docker ps --filter name=mylab99
```

**Hapus cluster (akhir modul, bukan tiap eksperimen):**

```bash
kind delete cluster --name mylab99
```

### 3.3 kubectl — mengontrol cluster

**Fungsi:** API client Kubernetes. Deploy, list pod, log, delete — semua lewat ini.

Contoh yang sering dipakai di Tugas 1:

```bash
kubectl get nodes
kubectl get pods -n cloud-dynamics
kubectl get pods -n monitoring
kubectl get ingress -A
kubectl -n cloud-dynamics logs deploy/frontend --tail=50
kubectl -n cloud-dynamics get deploy
```

Namespace penting:

| Namespace | Isi |
|---|---|
| `cloud-dynamics` | Online Boutique |
| `monitoring` | Prometheus, Grafana, Alertmanager |
| `ingress-nginx` | Controller Ingress |
| `default` | Kosongkan sebelum research (sisa case lab) |

### 3.4 Helm — memasang chart

**Fungsi:** package manager Kubernetes. Lab memakai Helm untuk memasang **kube-prometheus-stack** (Prometheus Operator + Prometheus + Grafana + node-exporter, dll.).

```bash
# HOST — install monitoring (Modul 6.2; sekali per cluster)
cd kubernetes/setup-cluster/supporting
HOST_IP="${HOST_IP:-127.0.0.1}" sh 5-install-prometheus.sh
```

Yang terjadi di dalam skrip (ringkas):

1. `helm repo add prometheus-community …`
2. `helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n monitoring`
3. Membuat Ingress `prometheus` dan `grafana` ke host `*.${HOST_IP}.sslip.io`

Cek release:

```bash
helm list -n monitoring
kubectl get pods -n monitoring
```

Uninstall (saat matikan Modul 6):

```bash
cd kubernetes/setup-cluster/supporting
kubectl delete ingress prometheus grafana -n monitoring --ignore-not-found
helm uninstall monitoring -n monitoring
kubectl delete namespace monitoring --ignore-not-found
```

### 3.5 ingress-nginx — pintu HTTP ke service

**Fungsi:** menerima request ke host port 80/443, membaca header `Host`, meneruskan ke Service yang benar. Tanpa ingress yang Ready, browser ke `*.sslip.io` akan gagal / connection reset.

Pasang (Modul 6.1):

```bash
cd kubernetes/setup-cluster/supporting
sh 3-install-ingress.sh
sh 4-cek-ingress.sh
```

Cek:

```bash
kubectl -n ingress-nginx get pods
# READY 1/1 Running
curl -sI -H 'Host: prometheus.127.0.0.1.sslip.io' http://127.0.0.1/ | head -5
```

DNS **sslip.io**: nama `foo.127.0.0.1.sslip.io` resolve ke `127.0.0.1`. Cocok untuk lab localhost.

### 3.6 Prometheus — gudang metrik

**Fungsi:** scrape metrik dari cluster (node, kube-state-metrics, pod yang expose metrics) dan simpan sebagai time series. Saat eksperimen selesai, script `collect-experiment.sh` **memanggil HTTP API Prometheus** untuk window waktu yang sama dengan `workload.csv`, lalu menulis `combined.csv`.

**Buka UI:**

http://prometheus.127.0.0.1.sslip.io/

**Cek sehat:**

```bash
curl -fsS "http://prometheus.${HOST_IP:-127.0.0.1}.sslip.io/-/healthy"
# Prometheus Server is Healthy.
```

**Tutorial singkat di UI Prometheus**

1. Buka URL di atas.
2. Tab **Graph** / **Query**.
3. Contoh query (sesuaikan waktu dengan window eksperimen):

```promql
# CPU usage rate container (contoh; nama metric bisa beda per stack)
sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{namespace="cloud-dynamics"}[1m]))
```

4. Atur range waktu ke sekitar `MEASUREMENT_START_EPOCH` … `MEASUREMENT_END_EPOCH` dari file `measurement-window.env` di folder results.
5. Execute. Kalau ada garis, scrape jalan.

Untuk Tugas 1, **tidak wajib** screenshot Prom UI — yang wajib adalah `combined.csv` dari collector. UI berguna untuk cek “apakah ada data?” sebelum/saat analisis.

**Status / Targets:** menu **Status → Targets**. Banyak target `UP`. Kalau banyak `DOWN`, collect bisa kosong/aneh.

### 3.7 Grafana — dashboard di atas Prometheus

**Fungsi:** visualisasi. Datasource default menunjuk ke Prometheus di cluster. Lebih enak dibaca daripada PromUI mentah untuk CPU/memory pod.

**Buka:**

http://grafana.127.0.0.1.sslip.io/

**Login:**

```bash
# user biasanya admin
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-user}' | base64 -d; echo

kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

**Tutorial singkat**

1. Login `admin` + password dari perintah di atas.
2. Menu **Dashboards** → cari dashboard bawaan kube-prometheus-stack, misalnya:
   - *Kubernetes / Compute Resources / Namespace (Pods)*
   - *Kubernetes / Compute Resources / Pod*
3. Filter **namespace** = `cloud-dynamics`.
4. Set time range ke window eksperimen (atau “Last 15 minutes” saat burst masih jalan).
5. Amati CPU/memory frontend vs service lain saat flash sale.

Grafana **tidak** menggantikan `combined.csv`. Ia untuk observasi dan membantu menulis Bagian 2 (fenomena).

### 3.8 Octant — browser resource Kubernetes

**Fungsi:** UI untuk melihat object cluster (pod, deployment, service, ingress, log) tanpa hafal semua perintah kubectl. **Bukan** monitoring time-series (itu Grafana/Prometheus).

**Pasang binary (sekali):**

```bash
cd kubernetes/apps/1_visualizer
sh download.sh
```

**Jalankan:**

```bash
export KUBECONFIG=/path/ke/ka-tugas-cloud/kubernetes/setup-cluster/kind/kubeconfig
# dari root repo:
# export KUBECONFIG="$PWD/kubernetes/setup-cluster/kind/kubeconfig"
cd kubernetes/apps/1_visualizer
sh run.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:22222/
```

Buka: http://127.0.0.1:22222/

`run.sh` bind **`127.0.0.1:22222` (IPv4)** supaya Firefox di Windows/WSL bisa connect. Listener lama `:22222` sering hanya IPv6 — Windows `127.0.0.1` gagal meski `curl` di WSL sukses. Log: `octant.nohup.out`. PID: `octant.pid`.

**Tutorial navigasi untuk Tugas 1**

1. Buka Octant.
2. Di selector **Namespace**, pilih **`cloud-dynamics`** (bukan `default`).
3. **Workloads → Pods**: harus kelihatan `frontend`, `cartservice`, `checkoutservice`, `productcatalogservice`, `recommendationservice`, `adservice`, `currencyservice`, `emailservice`, `paymentservice`, `shippingservice`, `redis-cart`.
4. Klik satu pod → tab **Logs** kalau mau lihat error.
5. **Network → Services / Ingress**: pastikan ada service `online-boutique` dan Ingress host toko.
6. Pod `web1-deployment-*` di `default` = sisa case lab lama, **bukan** toko. Hapus sebelum eksperimen (lihat preflight).

**Stop:**

```bash
kill "$(cat kubernetes/apps/1_visualizer/octant.pid)" 2>/dev/null || true
```

### 3.9 Online Boutique — aplikasi under test

**Fungsi:** toko demo Google/Hipster multi-service. Di lab, manifest diambil dari sibling repo lewat kustomize (`k8s/online-boutique/`), loadgenerator dihapus (beban diganti framework eksperimen kita), service agregat `online-boutique` mengarah ke `frontend:8080`.

URL toko: http://online-boutique.127.0.0.1.sslip.io/

Coba manual di browser: home → product → add to cart → checkout. Itu smoke manusia; script `smoke-test.sh` hanya GET homepage.

### 3.10 Workload generator & collector

| Bundle | Peran |
|---|---|
| `cloud-dynamics-applications` | Deploy / remove / smoke app |
| `cloud-dynamics-experiments` | Loadgen → `results/<id>/workload.csv` + metadata |
| `cloud-dynamics-metrics` | Query Prometheus untuk window yang sama → `combined.csv` |
| `cloud-dynamics-analysis-venv` | Jupyter opsional untuk analisis |

Profil Tugas 1:

| File | Arti |
|---|---|
| `scenarios/constant.env` | `DURATION=30`, `RPS=25` — beban rata (normal) |
| `scenarios/burst.env` | `DURATION=600`, base 10 RPS, burst 150 RPS mulai detik 180 selama 120 dtk — flash sale |

---

## 4. Prasyarat Modul 6 (sekali)

Ikuti README root **Modul 6.1** (kind + ingress) dan **6.2** (Prometheus/Grafana). Ringkas:

```bash
cd kubernetes/bin && sh download.sh && source set.sh
cd ../setup-cluster/kind && sh 1-create-cluster.sh && sh 2-set-config.sh
export KUBECONFIG="$PWD/kubeconfig"
cd ../supporting && sh 3-install-ingress.sh && sh 4-cek-ingress.sh
HOST_IP="${HOST_IP:-127.0.0.1}" sh 5-install-prometheus.sh
```

Octant: §3.8. Case 1–3 lab hapus sebelum research (preflight di bawah).

---

## 5. Preflight Tugas 1 (wajib tiap sesi / setelah reboot)

```bash
# HOST — dari root ka-tugas-cloud
export PATH="$PWD/kubernetes/bin:$PATH"
export KUBECONFIG="$PWD/kubernetes/setup-cluster/kind/kubeconfig"
export HOST_IP="${HOST_IP:-127.0.0.1}"

kind get clusters
docker ps --filter name=mylab99
test -f ../ka-ecommerce-microservices/release/kubernetes-manifests.yaml

# inotify — setiap reboot WSL/host
sudo sysctl -w fs.inotify.max_user_instances=8192
sudo sysctl -w fs.inotify.max_user_watches=1048576

kubectl -n ingress-nginx get pods
curl -fsS "http://prometheus.${HOST_IP}.sslip.io/-/healthy"

# sapu sisa case lab (abaikan NotFound)
kubectl delete \
  -f kubernetes/apps/2_case1/foo.yaml \
  -f kubernetes/apps/2_case1/bar.yaml \
  -f kubernetes/apps/2_case1/coba.yaml \
  -f kubernetes/apps/2_case1/counter.yaml \
  -f kubernetes/apps/2_case1/ingress.yaml \
  -f kubernetes/apps/2_case1/web1.yaml \
  -f kubernetes/apps/2_case1/web2.yaml \
  --ignore-not-found 2>/dev/null || true
kubectl delete namespace cloud-exp --ignore-not-found
# Hanya jika mau deploy ulang toko dari nol:
# kubectl delete namespace cloud-dynamics --ignore-not-found
```

Kalau ingress `CrashLoopBackOff` / kube-proxy `too many open files` / `:80` reset → §8.

---

## 6. Deploy toko + smoke

```bash
cd kubernetes/research/cloud-dynamics-applications
./scripts/build-and-load.sh online-boutique   # no-op build; image publik
./scripts/deploy.sh online-boutique
./scripts/smoke-test.sh online-boutique
```

Browser: http://online-boutique.127.0.0.1.sslip.io/  
Octant: namespace `cloud-dynamics`.

---

## 7. Eksperimen (inti)

Jalankan di **satu** terminal, env sudah di-set (§3.1).

```bash
cd kubernetes/research/cloud-dynamics-experiments
export TARGET_HOST="online-boutique.${HOST_IP}.sslip.io"
export APPLICATION_NAME=online-boutique
export APPLICATION_ARCHITECTURE=online-boutique

./scripts/check-environment.sh
./scripts/run-experiment.sh scenarios/constant.env
# tunggu selesai (~30 dtk + warmup)

./scripts/run-experiment.sh scenarios/burst.env
# ~10 menit; toko bisa lag — itu diharapkan
```

Hasil muncul di:

```text
kubernetes/research/cloud-dynamics-experiments/results/
├── constant-<stamp>-rN/
│   ├── workload.csv
│   ├── metadata.json
│   ├── measurement-window.env
│   ├── scenario.env
│   └── …
└── burst-<stamp>-rN/
    └── …
```

**Collect metrik** (setelah **kedua** run selesai; butuh `measurement-window.env`):

```bash
cd kubernetes/research/cloud-dynamics-metrics
./scripts/check-prometheus.sh
ls ../cloud-dynamics-experiments/results/

./scripts/collect-experiment.sh \
  ../cloud-dynamics-experiments/results/constant-<id> \
  online-boutique

./scripts/collect-experiment.sh \
  ../cloud-dynamics-experiments/results/burst-<id> \
  online-boutique
```

Ganti `constant-<id>` / `burst-<id>` dengan nama folder nyata. Tiap folder harus punya `combined.csv` setelah collect sukses.

**Saat eksperimen jalan, boleh buka bersamaan:**

| Alat | Untuk apa |
|---|---|
| Toko | Rasakan lag saat burst |
| Octant | Pod restart? Ready? |
| Grafana | CPU/memory namespace `cloud-dynamics` |
| Prometheus | Query kasar / Targets UP |

---

## 8. Troubleshooting yang sering kena

### 8.1 Ingress / kube-proxy crash: `too many open files`

Setelah reboot, `fs.inotify.max_user_instances` sering kembali ~128. Naikkan lalu restart pod:

```bash
sudo sysctl -w fs.inotify.max_user_instances=8192
sudo sysctl -w fs.inotify.max_user_watches=1048576
# alternatif tanpa sudo di prompt:
docker exec --privileged mylab99-control-plane \
  sysctl -w fs.inotify.max_user_instances=8192 fs.inotify.max_user_watches=1048576

kubectl -n kube-system delete pod -l k8s-app=kube-proxy
kubectl -n ingress-nginx delete pod -l app.kubernetes.io/component=controller
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=120s
curl -fsS "http://prometheus.127.0.0.1.sslip.io/-/healthy"
```

### 8.2 Octant: Firefox Windows “Unable to connect”

1. Pastikan proses hidup: `ss -ltn | grep 22222` harus `127.0.0.1:22222`.
2. Pakai `sh run.sh` yang sudah bind IPv4 (bukan listener `:22222` IPv6-only).
3. Jangan andalkan IP WSL kecuali localhost benar-benar tidak di-forward.

### 8.3 Collect gagal: missing `measurement-window.env`

Burst belum selesai. Tunggu proses `loadgen.py` / `run-experiment.sh` exit. Baru collect.

### 8.4 Smoke / toko 404 atau reset

Ingress down, atau Ingress host bentrok dengan case lama. Preflight + §8.1.

---

## 9. Analisis (opsional Jupyter)

```bash
cd kubernetes/research/cloud-dynamics-analysis-venv
./scripts/create-venv.sh
./scripts/start-jupyter.sh
# http://127.0.0.1:8888
```

Buka `combined.csv` dari folder `constant-…` dan `burst-…`. Untuk Bagian 2, jawab empat pertanyaan: apa yang terjadi, pada kondisi apa, metrics apa, mengapa penting di cloud — **dari angka**, bukan dugaan kosong.

---

## 10. Cabut toko (End)

Setelah kedua `combined.csv` aman:

```bash
cd kubernetes/research/cloud-dynamics-applications
./scripts/remove.sh online-boutique
kubectl delete namespace cloud-dynamics --ignore-not-found
```

Ini **tidak** menghapus cluster kind / Prometheus. Matikan Modul 6 penuh hanya lewat bagian “Selesai Modul 6” di README root.

---

## 11. Checklist cepat

**Bagian 1**

- [ ] kind + ingress Ready
- [ ] Prometheus healthy, Grafana login OK
- [ ] Octant (opsional tapi disarankan), namespace `cloud-dynamics`
- [ ] Sibling `ka-ecommerce-microservices`
- [ ] Case lab lama disapu
- [ ] Deploy + smoke boutique
- [ ] Run `constant` → results
- [ ] Run `burst` → results
- [ ] Collect → `combined.csv` untuk keduanya

**Bagian 2** — satu fenomena + evidence  
**Bagian 3** — satu research problem  
**End** — `remove.sh` toko

---

## 12. Referensi di repo

| Path | Isi |
|---|---|
| `README.md` (root) | Modul 1–6 praktikum; Modul 6.1–6.3 setup cluster |
| `kubernetes/research/cloud-dynamics-applications/README.md` | Semua app under test |
| `kubernetes/research/cloud-dynamics-experiments/README.md` | Skenario beban |
| `kubernetes/research/cloud-dynamics-metrics/README.md` | Collector PromQL |
| `kubernetes/setup-cluster/supporting/5-install-prometheus.sh` | Helm monitoring |
| `kubernetes/apps/1_visualizer/` | Octant |
