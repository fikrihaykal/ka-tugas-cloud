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

File `6-install-linkerd.sh` sampai `9-install-otel-collector.sh` di `kubernetes/setup-cluster/supporting/` bukan bagian Tugas 1. Jangan dijalankan.

---

## 1. Apa yang dinilai

| Bagian | Yang harus ada |
|---|---|
| **1 — Environment** | Cluster + monitoring + toko jalan; dua run (`constant`, `burst-flash-sale`); metrik terkumpul pada window yang sama |
| **2 — Satu perilaku** | Satu fenomena dari data (workload ↔ resource ↔ performance), dengan evidence angka |
| **3 — Research problem** | Satu pertanyaan riset yang lahir dari fenomena itu |

Bagian 2 menjawab dari angka: apa yang terjadi, pada kondisi apa, metrics apa, mengapa penting di cloud. Rubrik soal ada di canvas/brief. File ini cara menjalankan alatnya.

---

## 2. Alat — buat apa

Bukan satu website. Tiap baris punya peran sendiri. Perintah menjalankannya ada di bagian 3, urut.

| Alat | Buat apa | Kapan ada |
|---|---|---|
| **Docker + kind** | Node Kubernetes sebagai container. Cluster lab: `mylab99`, 1 control-plane + 3 worker, Kubernetes 1.28.13. API `127.0.0.1:16443`. | Langkah 1 |
| **kubectl** | Bicara ke API Kubernetes: list pod, log, delete. `kubectl get pods` tanpa `-n` hanya melihat namespace `default`, dan namespace itu tetap kosong. | Sepanjang lab |
| **ingress-nginx** | Pintu HTTP port 80/443. Baca header `Host`, teruskan ke Service. | Langkah 2 |
| **Helm** | Memasang chart `kube-prometheus-stack`. Tidak ada UI Helm. | Langkah 3 |
| **Prometheus** | Simpan metrik cluster, pod, dan latency ingress. Sumber `combined.csv`, plus grafik saat beban jalan. | Langkah 3, http://prometheus.127.0.0.1.sslip.io/ |
| **Grafana** | Grafik p95, request rate, CPU, memory. Tidak menggantikan CSV. | Langkah 3, http://grafana.127.0.0.1.sslip.io/ |
| **Online Boutique** | Toko multi-service yang di-load. 11 service. Frontend 5 pod, sisanya 1. | Langkah 4, http://online-boutique.127.0.0.1.sslip.io/ |
| **Octant** | Lihat pod, log, deployment. Bukan grafik metrik. Opsional. | Langkah 5, http://127.0.0.1:22222/ |
| **cloud-dynamics-experiments** | Loadgen `constant` dan `burst-flash-sale` → `workload.csv`. | Langkah 6 |
| **cloud-dynamics-metrics** | Tarik PromQL untuk window yang sama → `combined.csv`. | Langkah 7 |

DNS **sslip.io**: nama `foo.127.0.0.1.sslip.io` resolve ke `127.0.0.1`.

| Namespace | Isi | Muncul di langkah |
|---|---|---|
| `kube-system`, `local-path-storage` | Pod sistem cluster | 1 |
| `ingress-nginx` | Controller ingress | 2 |
| `monitoring` | Prometheus, Grafana, Alertmanager | 3 |
| `cloud-dynamics` | Toko | 4 |
| `default` | Kosong. Sisa case lab lama disapu di langkah 4 | — |

---

## 3. Jalankan urut

Semua perintah dari **root repo** `ka-tugas-cloud`, kecuali blok yang `cd` dulu. Jangan loncat. `kubectl` di sebuah langkah hanya untuk resource yang langkah itu baru membuat.

`3-install-ingress.sh`, `4-cek-ingress.sh`, dan `5-install-prometheus.sh` wajib dijalankan dari folder `supporting/`. Skrip itu membaca `./variables.sh`. Dari root, skrip itu gagal.

### 3.0 Tiap terminal baru

`export` di dalam skrip tidak masuk ke shell pemanggil. Terminal lain, dan shell setelah `2-set-config.sh`, set ulang:

```bash
export PATH="$PWD/kubernetes/bin:$PATH"
export KUBECONFIG="$PWD/kubernetes/setup-cluster/kind/kubeconfig"
export HOST_IP="${HOST_IP:-127.0.0.1}"
```

### 3.1 Cluster kind

**Buat apa:** Kubernetes lokal. Tiap node = satu container Docker.

Sekali per cluster. `download.sh` mengunduh `kind`, `kubectl`, dan `helm` ke `kubernetes/bin/`. `source set.sh` hanya berlaku di shell itu. `1-create-cluster.sh` minta password `sudo`, menaikkan `fs.inotify.max_user_*` (hilang setelah reboot WSL; ulang di bagian 5), lalu menarik image `kindest/node:v1.28.13`. Beberapa menit. Selesai kalau ada baris `You can now use your cluster`.

```bash
cd kubernetes/bin
sh download.sh
source set.sh

cd ../setup-cluster/kind
sh 1-create-cluster.sh
sh 2-set-config.sh
export KUBECONFIG="$PWD/kubeconfig"
```

`2-set-config.sh` menulis `kubeconfig` di folder `kind/` lalu menjalankan `kubectl get nodes`. Baris `export` di atas wajib, selagi masih di folder itu.

Lolos kalau empat node `Ready`, versi `v1.28.13`:

```text
mylab99-control-plane   Ready    control-plane
mylab99-worker          Ready
mylab99-worker2         Ready
mylab99-worker3         Ready
```

Cek pod yang memang sudah ada. `kubectl get pods` tanpa `-A` mencetak `No resources found in default namespace.` Itu benar.

```bash
kubectl get pods -A
kind get clusters
docker ps --filter name=mylab99
```

`kubectl get pods -A` berisi `kube-system` (`coredns`, `etcd`, `kube-apiserver`, `kube-proxy`, `kindnet`) dan `local-path-storage`. Belum ada `ingress-nginx`, `monitoring`, `cloud-dynamics`.

### 3.2 Ingress

**Buat apa:** menerima HTTP di port 80/443 dan meneruskan menurut header `Host`.

Env 3.0 sudah di-set.

```bash
cd kubernetes/setup-cluster/supporting
sh 3-install-ingress.sh
sh 4-cek-ingress.sh
```

`3-install-ingress.sh` apply ingress-nginx v1.9.4, lalu CRD Gateway API **v1.4.1** (butuh jaringan). Lolos kalau prompt kembali tanpa exit 1, dan CRD `gatewayclasses`, `gateways`, `httproutes`, `grpcroutes`, `referencegrants`, `backendtlspolicies` tertulis `created` atau `unchanged`.

Gateway API v1.5.x gagal di Kubernetes 1.28.13: tidak ada `ValidatingAdmissionPolicy` v1 dan fungsi CEL `isIP()`. Kalau log memuat `undeclared reference to 'isIP'`, skrip masih menempelkan v1.5.x.

Image controller di cluster baru ditarik dulu (bisa lewat 1 menit) dan secret webhook belum ada, jadi pod sempat `ContainerCreating`. `4-cek-ingress.sh` menunggu Ready paling lama 180 detik. Timeout artinya batas tunggu habis. Ulangi `sh 4-cek-ingress.sh` setelah controller `Running`.

Lolos langkah ini kalau baris terakhir:

```text
pod/ingress-nginx-controller-… condition met
Checking ingress host port...
Ingress HTTP reachable (status: 404)
```

**404 itu sukses.** Host percobaan `ingress-test.127.0.0.1.sslip.io` tidak punya Ingress, jadi controller menjawab 404. Port 80 hidup. Toko belum ada, jadi belum ada URL yang mengembalikan 200. Gagal hanya kalau teksnya `Ingress HTTP check failed`.

Baru sekarang namespace `ingress-nginx` punya pod:

```bash
kubectl -n ingress-nginx get pods
```

Controller `1/1 Running`. Dua job `admission-create` dan `admission-patch` berstatus `Completed`.

### 3.3 Prometheus dan Grafana

**Buat apa:** Helm memasang Prometheus (gudang metrik) dan Grafana (grafiknya). Latency toko masuk lewat ServiceMonitor `ingress-nginx`.

Masih di `kubernetes/setup-cluster/supporting/`, setelah 3.2 lolos. `HOST_IP=127.0.0.1` supaya URL-nya `prometheus.127.0.0.1.sslip.io` dan `grafana.127.0.0.1.sslip.io`.

```bash
HOST_IP="${HOST_IP:-127.0.0.1}" sh 5-install-prometheus.sh
```

Skrip menambah repo Helm, membuat namespace `monitoring`, memasang chart, lalu Ingress Prometheus dan Grafana. Pertama kali chart diunduh, diam beberapa menit itu normal. Kalau skrip berhenti karena IngressClass `nginx` tidak ada, langkah 3.2 belum lolos.

`Installation completed` artinya objek sudah diajukan. Pod masih boleh `ContainerCreating`. Tunggu image selesai:

```bash
kubectl get pods -n monitoring
```

Ulangi sampai semua ini `Running` dan READY penuh:

- `prometheus-monitoring-kube-prometheus-prometheus-0`
- `monitoring-grafana-…`
- `monitoring-kube-prometheus-operator-…`
- `alertmanager-monitoring-kube-prometheus-alertmanager-0`
- `monitoring-kube-state-metrics-…`
- `monitoring-prometheus-node-exporter-…` empat buah (satu per node)

`kube-state-metrics` yang tetap `CrashLoopBackOff` membuat metrik pod Ready dan restart kosong. Lihat lognya sebelum eksperimen:

```bash
kubectl -n monitoring logs deploy/monitoring-kube-state-metrics --tail=50
```

Lolos:

```bash
helm list -n monitoring
curl -fsS "http://prometheus.${HOST_IP:-127.0.0.1}.sslip.io/-/healthy"
kubectl -n monitoring get servicemonitor ingress-nginx
```

`helm list` status `deployed`. Curl mencetak `Prometheus Server is Healthy.` ServiceMonitor bernama `ingress-nginx`.

Buka http://prometheus.127.0.0.1.sslip.io/ . UI Prometheus tampil. Grafana http://grafana.127.0.0.1.sslip.io/ meminta login. Password:

```bash
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-user}' | base64 -d; echo
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Halaman login yang muncul berarti Ingress Grafana sudah benar. Belum ada garis p95: toko dan beban belum jalan.

`monitoring` sekarang punya pod. `cloud-dynamics` belum ada. Jangan `kubectl get pods -n cloud-dynamics` di langkah ini.

### 3.4 Toko

**Buat apa:** Online Boutique, 11 service. Frontend 5 replica dari kustomize adapter. Service lain 1 replica. Manifest dari sibling repo. Loadgenerator bawaan Google tidak dipakai.

Env 3.0 sudah di-set. Sibling repo wajib ada.

```bash
cd "$HOME/project/ka-tugas-cloud"
test -f ../ka-ecommerce-microservices/release/kubernetes-manifests.yaml && echo "manifest OK"
```

Kalau `manifest OK` tidak tercetak, berhenti.

Sapu sisa case lab di namespace `default` (abaikan NotFound). Pod `web1-deployment-*` di `default` bukan toko.

```bash
sudo sysctl -w fs.inotify.max_user_instances=8192
sudo sysctl -w fs.inotify.max_user_watches=1048576

kubectl delete \
  -f kubernetes/apps/2_case1/foo.yaml \
  -f kubernetes/apps/2_case1/bar.yaml \
  -f kubernetes/apps/2_case1/coba.yaml \
  -f kubernetes/apps/2_case1/counter.yaml \
  -f kubernetes/apps/2_case1/ingress.yaml \
  -f kubernetes/apps/2_case1/web1.yaml \
  -f kubernetes/apps/2_case1/web2.yaml \
  --ignore-not-found
kubectl delete namespace cloud-exp --ignore-not-found

cd kubernetes/research/cloud-dynamics-applications
./scripts/build-and-load.sh online-boutique
./scripts/deploy.sh online-boutique
```

`build-and-load.sh online-boutique` tidak membangun image. Dua baris, exit 0. Node kind menarik image saat pod mulai.

`deploy.sh` membuat namespace `cloud-dynamics`, 11 deployment, dan Ingress `online-boutique.<HOST_IP>.sslip.io`. Tiap deployment ditunggu paling lama 180 detik. Pertama kali lama. Jangan putus. Selesai kalau:

```text
Application : online-boutique
HOST_IP     : 127.0.0.1
URL         : http://online-boutique.127.0.0.1.sslip.io/
```

Baru sekarang cek pod toko:

```bash
kubectl -n cloud-dynamics get deploy
kubectl get pods -n cloud-dynamics
```

Sebelas deployment. `frontend` **5/5**. Sisanya **1/1**: `cartservice`, `checkoutservice`, `productcatalogservice`, `recommendationservice`, `adservice`, `currencyservice`, `emailservice`, `paymentservice`, `shippingservice`, `redis-cart`. Lima belas pod `Running`. Jangan ubah replica lagi dan jangan pasang autoscaler.

`kubectl get pods` tanpa `-n` tetap kosong. Toko tidak di namespace `default`.

```bash
./scripts/smoke-test.sh online-boutique
```

Lolos kalau exit 0 dan terminal memuat HTML. HTTP 404 atau 500 membuat curl gagal. 404: Ingress atau pod belum siap. 500: pod Running tapi proses di dalam pod error:

```bash
kubectl -n cloud-dynamics logs deploy/frontend --tail=50
```

Browser: http://online-boutique.127.0.0.1.sslip.io/ — home, product, add to cart, checkout.

### 3.5 Octant (opsional)

**Buat apa:** UI objek cluster. Bukan grafik metrik.

Setelah toko jalan, dari root repo:

```bash
cd kubernetes/apps/1_visualizer
sh download.sh
export KUBECONFIG="$HOME/project/ka-tugas-cloud/kubernetes/setup-cluster/kind/kubeconfig"
sh run.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:22222/
```

`download.sh` sekali. `run.sh` bind `127.0.0.1:22222` (IPv4). Buka http://127.0.0.1:22222/ . Namespace **`cloud-dynamics`**. Workloads → Pods: lima belas pod di langkah 3.4 (`frontend` lima, sisanya satu). Network → Ingress: host toko.

Stop, dari root repo:

```bash
kill "$(cat kubernetes/apps/1_visualizer/octant.pid)" 2>/dev/null || true
```

### 3.6 Beban

**Buat apa:** `constant` = kondisi normal, sekitar 30 detik ukur, 25 RPS. `burst-flash-sale` = flash sale, 600 detik ukur. `scenarios/burst.env` profil lama (150 RPS lalu langsung 10). Bukan run ini.

Sebelum loadgen, buka Grafana (login dari langkah 3.3) atau Prometheus. Range **Last 15 minutes**, refresh **5s**. Tempel query bagian 4. Minimal tiga: p95, request rate, CPU. Biarkan terbuka.

Di terminal lain, env 3.0 sudah di-set:

```bash
cd kubernetes/research/cloud-dynamics-experiments
export TARGET_HOST="online-boutique.${HOST_IP}.sslip.io"
export APPLICATION_NAME=online-boutique
export APPLICATION_ARCHITECTURE=online-boutique

./scripts/check-environment.sh
```

Lolos kalau ada `OK: target is reachable.` Kalau `ERROR: target is not reachable`, kembali ke langkah 3.4. Jangan jalankan loadgen.

```bash
./scripts/run-experiment.sh scenarios/constant.env
```

Tunggu selesai sendiri. Jangan Ctrl-C. Selesai kalau prompt kembali dan ada folder `results/constant-<stamp>-rN/` berisi `workload.csv`, `metadata.json`, `measurement-window.env`, `scenario.env`.

```bash
./scripts/run-experiment.sh scenarios/burst-flash-sale.env
```

Sekitar 10 menit ditambah warmup. Toko boleh lambat. Setelah warmup:

| Detik | RPS |
|---|---|
| 0–120 | 10 |
| 120–180 | 400 |
| 180–540 | turun pelan dari 400 ke 10 |
| 540–600 | 10 |

Di Grafana, request rate mengikuti tabel itu. p95 saat 10 RPS di awal ada di kisaran puluhan milidetik. Saat 400 RPS, dan selama request rate sudah turun tapi masih tinggi, catat apakah p95 ikut turun atau masih di kisaran detik. CPU pembanding garis itu.

Selesai kalau folder `results/burst-flash-sale-<stamp>-rN/` punya `measurement-window.env`.

```text
kubernetes/research/cloud-dynamics-experiments/results/
├── constant-<stamp>-rN/
│   ├── workload.csv
│   ├── metadata.json
│   ├── measurement-window.env
│   └── scenario.env
└── burst-flash-sale-<stamp>-rN/
    └── …
```

### 3.7 Collect

**Buat apa:** menggabungkan `workload.csv` dengan metrik Prometheus pada window yang sama → `combined.csv`.

Setelah **kedua** run selesai. Jangan collect selagi `run-experiment.sh` masih jalan.

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

Ganti `<id>` dengan nama folder nyata. Tiap folder harus punya `combined.csv`.

### 3.8 Jupyter (opsional)

**Buat apa:** notebook untuk membaca kedua `combined.csv`.

```bash
cd kubernetes/research/cloud-dynamics-analysis-venv
./scripts/create-venv.sh
./scripts/start-jupyter.sh
```

Buka http://127.0.0.1:8888 .

Penelitian berhenti di sini. Cabut toko dan hapus cluster ada di bagian 6, setelah `combined.csv` aman.

---

## 4. Query yang ditempel di langkah 3.6

Bukan perintah shell. Tempel di Prometheus Graph atau Grafana Explore, satu query per grafik. Range 15 menit. Satuan p95 **milidetik**, sama dengan kolom `p95_latency_ms`.

Delapan grafik sekaligus, range 15 menit. Buka atau salin:

```text
http://prometheus.127.0.0.1.sslip.io/query?g0.expr=%23+p95+latency+toko%2C+milidetik%0Ahistogram_quantile%28%0A++0.95%2C%0A++sum+by+%28le%29+%28%0A++++rate%28nginx_ingress_controller_request_duration_seconds_bucket%7B%0A++++++ingress%3D%22online-boutique%22%0A++++%7D%5B1m%5D%29%0A++%29%0A%29+*+1000&g0.show_tree=0&g0.tab=graph&g0.range_input=15m&g0.res_type=auto&g0.res_density=medium&g0.display_mode=lines&g0.show_exemplars=0&g1.expr=%23+request+per+detik+yang+lewat+ingress+toko%0Asum%28rate%28nginx_ingress_controller_requests%7Bingress%3D%22online-boutique%22%7D%5B1m%5D%29%29&g1.show_tree=0&g1.tab=graph&g1.range_input=15m&g1.res_type=auto&g1.res_density=medium&g1.display_mode=lines&g1.show_exemplars=0&g2.expr=%23+CPU+namespace+toko%2C+core%0Asum%28rate%28container_cpu_usage_seconds_total%7Bnamespace%3D%22cloud-dynamics%22%2Ccontainer%21%3D%22%22%2Ccontainer%21%3D%22POD%22%7D%5B1m%5D%29%29&g2.show_tree=0&g2.tab=graph&g2.range_input=15m&g2.res_type=auto&g2.res_density=medium&g2.display_mode=lines&g2.show_exemplars=0&g3.expr=%23+memory+working+set+toko%2C+MB%0Asum%28container_memory_working_set_bytes%7Bnamespace%3D%22cloud-dynamics%22%2Ccontainer%21%3D%22%22%2Ccontainer%21%3D%22POD%22%7D%29+%2F+1024+%2F+1024&g3.show_tree=0&g3.tab=graph&g3.range_input=15m&g3.res_type=auto&g3.res_density=medium&g3.display_mode=lines&g3.show_exemplars=0&g4.expr=%23+pod+Ready+di+namespace+toko.+Baseline+sebelum+beban%3A+11%0Asum%28kube_pod_status_ready%7Bnamespace%3D%22cloud-dynamics%22%2Ccondition%3D%22true%22%7D%29&g4.show_tree=0&g4.tab=graph&g4.range_input=15m&g4.res_type=auto&g4.res_density=medium&g4.display_mode=lines&g4.show_exemplars=0&g5.expr=%23+restart+container+toko.+Baseline+sebelum+beban%3A+0%0Asum%28kube_pod_container_status_restarts_total%7Bnamespace%3D%22cloud-dynamics%22%7D%29&g5.show_tree=0&g5.tab=graph&g5.range_input=15m&g5.res_type=auto&g5.res_density=medium&g5.display_mode=lines&g5.show_exemplars=0&g6.expr=%23+network+receive+toko%2C+byte%2Fdetik%0Asum%28rate%28container_network_receive_bytes_total%7Bnamespace%3D%22cloud-dynamics%22%7D%5B1m%5D%29%29&g6.show_tree=0&g6.tab=graph&g6.range_input=15m&g6.res_type=auto&g6.res_density=medium&g6.display_mode=lines&g6.show_exemplars=0&g7.expr=%23+request+non-2xx+per+detik+di+ingress+toko%0Asum%28rate%28nginx_ingress_controller_requests%7Bingress%3D%22online-boutique%22%2Cstatus%21%7E%222..%22%7D%5B1m%5D%29%29&g7.show_tree=0&g7.tab=graph&g7.range_input=15m&g7.res_type=auto&g7.res_density=medium&g7.display_mode=lines&g7.show_exemplars=0
```

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
# CPU namespace toko, core
sum(rate(container_cpu_usage_seconds_total{namespace="cloud-dynamics",container!="",container!="POD"}[1m]))
```

```promql
# memory working set toko, MB
sum(container_memory_working_set_bytes{namespace="cloud-dynamics",container!="",container!="POD"}) / 1024 / 1024
```

```promql
# pod Ready di namespace toko. Baseline sebelum beban: 11
sum(kube_pod_status_ready{namespace="cloud-dynamics",condition="true"})
```

```promql
# restart container toko. Baseline sebelum beban: 0
sum(kube_pod_container_status_restarts_total{namespace="cloud-dynamics"})
```

```promql
# network receive toko, byte/detik
sum(rate(container_network_receive_bytes_total{namespace="cloud-dynamics"}[1m]))
```

```promql
# request non-2xx per detik di ingress toko
sum(rate(nginx_ingress_controller_requests{ingress="online-boutique",status!~"2.."}[1m]))
```

Yang ditonton terus saat flash sale: p95, request rate, CPU. Sisanya pembanding. Garis p95 kosong sebelum ada request (smoke atau loadgen). Query Linkerd tidak dipakai.

CPU dan memory di Grafana juga ada di **Dashboards** → *Kubernetes / Compute Resources / Namespace (Pods)*, filter namespace `cloud-dynamics`.

---

## 5. Kalau rusak

### 5.1 Ingress / kube-proxy: `too many open files`

Setelah reboot, `fs.inotify.max_user_instances` sering kembali ~128. Env 3.0 dulu, lalu:

```bash
sudo sysctl -w fs.inotify.max_user_instances=8192
sudo sysctl -w fs.inotify.max_user_watches=1048576
docker exec --privileged mylab99-control-plane \
  sysctl -w fs.inotify.max_user_instances=8192 fs.inotify.max_user_watches=1048576

kubectl -n kube-system delete pod -l k8s-app=kube-proxy
kubectl -n ingress-nginx delete pod -l app.kubernetes.io/component=controller
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=180s
curl -fsS "http://prometheus.127.0.0.1.sslip.io/-/healthy"
```

Baris `docker exec` alternatif kalau `sudo` tidak kepakai. Ulangi kalau ingress jatuh di tengah 400 RPS, lalu turunkan `BURST_RPS` di `scenarios/burst-flash-sale.env` dan set `WORKERS` ke `BURST_RPS` kali 5.

### 5.2 `4-cek-ingress.sh` timeout

Controller belum Ready karena image masih ditarik. `kubectl -n ingress-nginx get pods`. Kalau sudah `1/1 Running`, ulangi `sh 4-cek-ingress.sh` dari folder `supporting/`.

### 5.3 Octant: Firefox Windows tidak connect

`ss -ltn | grep 22222` harus `127.0.0.1:22222`. Pakai `sh run.sh` dari langkah 3.5.

### 5.4 Collect: missing `measurement-window.env`

Run belum selesai. Tunggu `run-experiment.sh` exit.

### 5.5 Smoke 404, 500, atau connection reset

404 sebelum langkah 3.4 normal: Ingress toko belum ada. 404 setelah deploy: ingress mati (5.1) atau host bentrok dengan case lab (sapu di langkah 3.4). 500: `kubectl -n cloud-dynamics logs deploy/frontend --tail=50`.

### 5.6 Grafik p95 kosong padahal toko kebuka

1. Prometheus → **Status → Targets**. Job `ingress-nginx` harus `UP`.
2. Kalau ServiceMonitor tidak ada, tempel sekali (sama dengan yang ditulis `5-install-prometheus.sh`):

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

3. Tunggu sekitar 15 detik. Histogram tetap kosong kalau belum ada request: buka homepage atau jalankan `constant`.
4. Di kotak metrik, cari `nginx_ingress_controller_request_duration_seconds_bucket`. Label `ingress` harus `online-boutique`.

---

## 6. Selesai penelitian

Dua cara. **6.1 mematikan** cluster, jadi toko, ingress, dan Prometheus ikut berhenti, lalu **6.2 menyalakan** lagi tanpa install ulang. **6.3 menghapus** semuanya. Setelah 6.3, mulai lagi dari langkah 3.1.

### 6.1 Matikan

Toko, ingress, dan Prometheus adalah pod di dalam node kind. Node itu container Docker. Menghentikan keempat container itu mematikan ketiganya sekaligus. Tidak ada yang dihapus.

Octant di host ikut dimatikan. Lewati baris `kill` kalau tidak pernah dijalankan.

```bash
kill "$(cat kubernetes/apps/1_visualizer/octant.pid)" 2>/dev/null || true
docker stop mylab99-worker mylab99-worker2 mylab99-worker3 mylab99-control-plane
```

Lolos kalau `docker ps --filter name=mylab99` kosong, dan port 80 serta 443 tidak listen. `kubectl` akan ditolak koneksinya. Itu keadaan mati, bukan cluster terhapus.

### 6.2 Nyalakan lagi

Jangan ulang 3.1–3.3. Control-plane dulu, baru worker.

```bash
docker start mylab99-control-plane
docker start mylab99-worker mylab99-worker2 mylab99-worker3
```

Env 3.0, lalu tunggu node dan pod Ready:

```bash
kubectl get nodes
kubectl -n ingress-nginx get pods
kubectl get pods -n monitoring
kubectl get pods -n cloud-dynamics
```

Empat node `Ready`. Controller ingress `1/1 Running`. Pod monitoring `Running`. Kalau toko belum dicabut, lima belas pod `cloud-dynamics` kembali `Running`. Lalu lanjut beban di langkah 3.6.

Kalau namespace `cloud-dynamics` sudah tidak ada, ulang langkah 3.4, bukan 3.1.

### 6.3 Hapus

Hanya kalau modul selesai dan tidak ada run susulan. Ini membongkar node kind, ingress, dan monitoring. Setelah ini, mulai lagi dari langkah 3.1. Env 3.0 dulu.

```bash
cd "$HOME/project/ka-tugas-cloud"
kind delete cluster --name mylab99
kind get clusters
docker ps --filter name=mylab99
```

Lolos kalau `kind get clusters` mencetak `No kind clusters found` dan tidak ada container `mylab99`. Port 80, 443, dan 16443 bebas.

---

## 7. Checklist

- [ ] 3.1 Empat node Ready. `kubectl get pods` tanpa `-A` kosong
- [ ] 3.2 `Ingress HTTP reachable (status: 404)`, controller `1/1 Running`
- [ ] 3.3 Prometheus healthy, pod monitoring `Running`, Grafana login tampil
- [ ] 3.4 Frontend `5/5`, service lain `1/1` (15 pod), smoke HTML
- [ ] 3.5 Octant opsional, namespace `cloud-dynamics`
- [ ] 3.6 Query bagian 4 terbuka sebelum beban. `constant` lalu `burst-flash-sale`
- [ ] 3.7 `combined.csv` di kedua folder
- [ ] Bagian 1–3 laporan selesai
- [ ] 6.1 Matikan kalau berhenti sementara. 6.2 nyalakan lagi. 6.3 hapus hanya kalau tidak ada run susulan

---

## 8. Referensi di repo

| Path | Isi |
|---|---|
| `README.md` (root) | Modul 1–6; Modul 6.1–6.3 setup cluster |
| `kubernetes/research/cloud-dynamics-applications/README.md` | App under test |
| `kubernetes/research/cloud-dynamics-experiments/README.md` | Skenario beban |
| `kubernetes/research/cloud-dynamics-metrics/README.md` | Collector PromQL |
| `kubernetes/setup-cluster/supporting/5-install-prometheus.sh` | Helm monitoring |
| `kubernetes/apps/1_visualizer/` | Octant |
