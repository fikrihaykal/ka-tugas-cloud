# Tugas 1 — Online Boutique (normal vs flash sale)

Panduan lengkap terpisah dari README root. README hanya merujuk ke file ini.

**System under test:** Online Boutique (microservices e-commerce).  
**Kondisi normal:** profil workload `constant`.  
**Event flash sale:** profil workload `burst-flash-sale` ke URL yang sama.  
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
| **1 — Environment** | Cluster + monitoring + toko jalan; dua run (`constant`, `burst-flash-sale`); metrik terkumpul pada window yang sama |
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
| Generate beban | **cloud-dynamics-experiments** | `constant` / `burst-flash-sale` → `workload.csv` | Script Python loadgen |
| Time-series metrics | **Prometheus** | Menyimpan metrik cluster/pod dan latency ingress; grafik langsung + sumber `combined.csv` | http://prometheus.127.0.0.1.sslip.io/ |
| Dashboard visual | **Grafana** | Grafik langsung: p95 latency toko, request rate, CPU, memory | http://grafana.127.0.0.1.sslip.io/ |
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

**Fungsi:** scrape metrik dari cluster (node, kube-state-metrics, pod, dan ingress-nginx) dan simpan sebagai time series. Ingress controller sudah `--enable-metrics=true`. Skrip pasang Prometheus membuat `ServiceMonitor` `ingress-nginx` supaya durasi request toko masuk ke Prometheus. Saat eksperimen selesai, script `collect-experiment.sh` memanggil HTTP API Prometheus untuk window yang sama dengan `workload.csv`, lalu menulis `combined.csv`.

Grafik di UI ini dipakai **saat beban sedang jalan**, supaya p95 kelihatan tanpa menunggu CSV. Replica toko tidak diubah: tetap satu pod per service seperti di manifest.

**Buka UI:**

http://prometheus.127.0.0.1.sslip.io/

**Cek sehat:**

```bash
curl -fsS "http://prometheus.${HOST_IP:-127.0.0.1}.sslip.io/-/healthy"
# Prometheus Server is Healthy.
```

**Cek target ingress sebelum eksperimen**

```bash
kubectl -n monitoring get servicemonitor ingress-nginx
kubectl -n ingress-nginx get svc ingress-nginx-controller-metrics
```

Di UI: **Status → Targets**. Cari job yang memuat `ingress-nginx`. Harus `UP`. Kalau `ServiceMonitor` tidak ada, pasang sekali (sama dengan yang ditulis `5-install-prometheus.sh`):

```bash
kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ingress-nginx
  namespace: monitoring
  labels:
    release: monitoring
spec:
  namespaceSelector:
    matchNames:
    - ingress-nginx
  selector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
      app.kubernetes.io/component: controller
  endpoints:
  - port: metrics
    path: /metrics
    interval: 5s
EOF
```

Tunggu sekitar 15 detik, lalu cek Targets lagi.

**Query yang ditonton saat beban jalan**

Tab **Graph**. Range **Last 15 minutes**. Satuan p95 di bawah ini **milidetik**, supaya sama dengan kolom `p95_latency_ms` di CSV.

```promql
# p95 latency toko, milidetik
histogram_quantile(
  0.95,
  sum by (le) (
    rate(nginx_ingress_controller_request_duration_seconds_bucket{
      ingress="online-boutique"
    }[1m])
  )
) * 1000
```

```promql
# request per detik yang lewat ingress toko
sum(rate(nginx_ingress_controller_requests{ingress="online-boutique"}[1m]))
```

```promql
# CPU namespace toko, core. Pembanding garis p95: catat apakah ikut naik
sum(rate(container_cpu_usage_seconds_total{namespace="cloud-dynamics",container!="",container!="POD"}[1m]))
```

```promql
# memory working set toko, MB
sum(container_memory_working_set_bytes{namespace="cloud-dynamics",container!="",container!="POD"}) / 1024 / 1024
```

```promql
# pod Ready di namespace toko. Baseline sebelum beban: 11. Catat kalau berkurang
sum(kube_pod_status_ready{namespace="cloud-dynamics",condition="true"})
```

```promql
# restart container toko. Baseline sebelum beban: 0. Catat kalau naik
sum(kube_pod_container_status_restarts_total{namespace="cloud-dynamics"})
```

```promql
# network receive toko, byte/detik
sum(rate(container_network_receive_bytes_total{namespace="cloud-dynamics"}[1m]))
```

```promql
# request non-2xx per detik di ingress toko. Catat kalau lepas dari 0
sum(rate(nginx_ingress_controller_requests{ingress="online-boutique",status!~"2.."}[1m]))
```

Tiap query = satu grafik. Yang ditonton terus selama flash sale: p95, request rate, dan CPU. Sisanya pembanding: memory, pod Ready, restart, network, dan request gagal.

Garis p95 baru muncul setelah ada request (smoke atau loadgen). Sebelum itu query boleh kosong. Kalau setelah ada beban tetap kosong, buka kotak metrik, ketik `nginx_ingress_controller_request_duration_seconds_bucket`, dan pakai nilai label `ingress` yang benar-benar ada.

Query Linkerd tidak dipakai. Di run ini kolom itu kosong karena mesh-nya tidak terpasang.

Untuk Tugas 1, yang wajib tetap `combined.csv`. Grafik ini supaya kamu melihat lonjakan p95 pada saat itu terjadi.

### 3.7 Grafana — dashboard di atas Prometheus

**Fungsi:** visualisasi dengan refresh otomatis. Datasource default menunjuk ke Prometheus di cluster. Untuk Tugas 1, Grafana dipakai menonton p95 dan request rate toko sambil loadgen berjalan, plus CPU/memory namespace. Replica tidak ditambah dari sini.

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

**Tutorial singkat — latency langsung**

1. Login `admin` + password dari perintah di atas.
2. Menu **Explore** (ikon kompas). Datasource: **Prometheus**.
3. Time range **Last 15 minutes**. Refresh **5s**.
4. Tempel query dari §3.6, satu query per tab Explore. Minimal tiga tab: p95, request rate, CPU. Tab memory, pod Ready, restart, network, dan request non-2xx dibuka kalau mau melihat pembandingnya sekaligus.
5. Bentuk yang harus kelihatan di request rate, kalau replica masih bawaan:
   - sekitar 2 menit di 10 RPS;
   - lonjakan ke 400 RPS selama sekitar 1 menit;
   - turun pelan menuju 10 RPS selama sekitar 6 menit, bukan jatuh sekaligus;
   - 1 menit terakhir diam di 10 RPS.
   p95 saat 10 RPS di awal ada di kisaran puluhan ms. Saat 400 RPS, dan selama request rate sudah turun tapi masih tinggi, bandingkan apakah p95 ikut turun atau masih di kisaran detik. CPU dipakai sebagai pembanding garis itu.

**CPU dan memory (pembanding)**

1. Menu **Dashboards** → *Kubernetes / Compute Resources / Namespace (Pods)*.
2. Filter **namespace** = `cloud-dynamics`.
3. Time range **Last 15 minutes**.
4. Bandingkan CPU dan memory toko dengan garis p95 di Explore. Jangan mengubah replica di tengah run.

Grafana tidak menggantikan `combined.csv`. CSV untuk angka yang ditulis di laporan. Grafana untuk melihat garisnya saat eksperimen masih jalan.

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
| `scenarios/burst-flash-sale.env` | Flash sale, `DURATION=600`. 0–120 dtk: 10 RPS. 120–180: 400 RPS. 180–540: turun pelan 400 → 10. 540–600: 10 RPS. `WORKERS=2000` (400 × timeout 5 dtk) supaya antrean tidak mentok di generator |

`scenarios/burst.env` adalah profil kotak lama (150 RPS lalu langsung balik ke 10). Bukan run Tugas 1 ini.

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
kubectl -n monitoring get servicemonitor ingress-nginx
kubectl -n cloud-dynamics get deploy -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas
# REPLICAS kosong atau 1 = bawaan. Jangan diubah untuk run ini.

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

Replica tetap seperti manifest. Jangan pasang autoscaler dan jangan menaikkan `replicas` sebelum kedua run ini selesai. Tujuannya melihat p95 waktu semua service masih satu pod.

**Sebelum** menjalankan beban, buka Grafana Explore (atau Prometheus Graph) dengan query §3.6. Range 15 menit, refresh 5 detik. Biarkan jendela itu terbuka.

Jalankan di **satu** terminal lain, env sudah di-set (§3.1).

```bash
cd kubernetes/research/cloud-dynamics-experiments
export TARGET_HOST="online-boutique.${HOST_IP}.sslip.io"
export APPLICATION_NAME=online-boutique
export APPLICATION_ARCHITECTURE=online-boutique

./scripts/check-environment.sh
./scripts/run-experiment.sh scenarios/constant.env
# tunggu selesai (~30 dtk ukur + warmup)

./scripts/run-experiment.sh scenarios/burst-flash-sale.env
# ~10 menit ukur + warmup. Toko bisa lag — itu diharapkan.
# Setelah warmup, bentuk bebannya:
#   0–120 dtk   10 RPS
#   120–180     400 RPS
#   180–540     turun pelan 400 → 10
#   540–600     10 RPS
# Yang ditonton: request rate sudah menurun, p95 belum tentu ikut turun.
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
└── burst-flash-sale-<stamp>-rN/
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
  ../cloud-dynamics-experiments/results/burst-flash-sale-<id> \
  online-boutique
```

Ganti `constant-<id>` / `burst-flash-sale-<id>` dengan nama folder nyata. Tiap folder harus punya `combined.csv` setelah collect sukses.

**Saat eksperimen jalan, jendela yang dibuka:**

| Alat | Untuk apa |
|---|---|
| Grafana Explore, query p95 | Garis latency toko, dalam milidetik. Ini yang ditonton |
| Grafana Explore, query request rate | 10 RPS, lonjak ke 400, lalu turun pelan ke 10. Bukan jatuh sekaligus |
| Grafana dashboard CPU/memory | Pembanding namespace `cloud-dynamics` saat p95 sedang tinggi |
| Toko di browser | Halaman terasa lambat saat garis p95 naik |
| Octant, namespace `cloud-dynamics` | Cek pod Ready, replica, dan restart. Replica tidak boleh dinaikkan manual |
| Prometheus Targets | Hanya kalau garis p95 kosong: pastikan target ingress `UP` |

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

Run flash sale belum selesai. Tunggu proses `loadgen.py` / `run-experiment.sh` exit. Baru collect. Kalau ingress jatuh (`too many open files`) di tengah 400 RPS, lihat §8.1, lalu turunkan `BURST_RPS` di `scenarios/burst-flash-sale.env` dan set `WORKERS` ke `BURST_RPS` kali 5.

### 8.4 Smoke / toko 404 atau reset

Ingress down, atau Ingress host bentrok dengan case lama. Preflight + §8.1.

### 8.5 Grafik p95 kosong padahal toko kebuka

1. **Status → Targets** di Prometheus. Target `ingress-nginx` harus `UP`. Kalau ServiceMonitor belum ada, tempel YAML di §3.6.
2. Generate sedikit trafik dulu (buka homepage, atau jalankan `constant`). Histogram kosong kalau belum ada request.
3. Di kotak metrik Prometheus, cari `nginx_ingress_controller_request_duration_seconds_bucket`. Filter `ingress` harus `online-boutique`. Kalau nama ingress beda, ganti label di query.

---

## 9. Analisis (opsional Jupyter)

```bash
cd kubernetes/research/cloud-dynamics-analysis-venv
./scripts/create-venv.sh
./scripts/start-jupyter.sh
# http://127.0.0.1:8888
```

Buka `combined.csv` dari folder `constant-…` dan `burst-flash-sale-…`. Untuk Bagian 2, jawab empat pertanyaan: apa yang terjadi, pada kondisi apa, metrics apa, mengapa penting di cloud — **dari angka**, bukan dugaan kosong.

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
- [ ] Prometheus healthy, target `ingress-nginx` UP, Grafana login OK
- [ ] Grafana Explore: query p95 + request rate terbuka sebelum run (replica tetap bawaan)
- [ ] Octant (opsional tapi disarankan), namespace `cloud-dynamics`
- [ ] Sibling `ka-ecommerce-microservices`
- [ ] Case lab lama disapu
- [ ] Deploy + smoke boutique
- [ ] Saat `constant` / `burst-flash-sale` jalan, garis p95 dan request rate kelihatan di Grafana atau Prometheus
- [ ] Run `constant` → results
- [ ] Run `burst-flash-sale` → results. Request rate: 10, lonjak 400, turun pelan ke 10
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
