# ka-tugas-cloud

Repo praktikum infrastruktur cloud. Isinya berjalan dari bawah ke atas: mesin virtual, runtime container, Docker, Compose, lalu cluster Kubernetes lokal.

Semua skrip ditulis untuk host **Linux x86_64**. Bagian VM butuh QEMU/KVM. Binary `kind`, `kubectl`, dan Octant yang diunduh skrip juga build Linux amd64, jadi di macOS langsung tidak akan jalan.

![Urutan lab: VM, runc, Docker, image, Compose, Kubernetes](docs/images/lab-path.png)

## Isi repo

```text
.
├── vm01/                 mesin virtual Alpine di QEMU/KVM
├── containers/
│   ├── runc/             runtime container level rendah
│   ├── docker/           container Docker satu per satu
│   └── compose/          image custom + stack Compose
└── kubernetes/           cluster kind + workload contoh
```

| Bagian | Apa yang dipraktikkan |
|---|---|
| `vm01/` | Dua VM Alpine di atas satu image dasar, overlay disk, volume persisten, bridge `qemu-br0`, NAT ke luar, dan simulasi putus jaringan |
| `containers/runc/` | `runc spec`, rootfs, `runc run`, `exec`, `kill`, `delete` |
| `containers/docker/` | Proses Alpine, web server Python, MySQL + phpMyAdmin |
| `containers/compose/images/` | Image buatan sendiri: Apache/PHP, desktop noVNC, Nginx, Nginx + PHP-FPM |
| `containers/compose/compose/` | Stack Nginx, TLS, WordPress, dan aplikasi PHP yang terhubung ke MySQL |
| `kubernetes/` | Cluster kind (1 control-plane + 2 worker), ingress NGINX, visualizer Octant, dan beberapa case workload |

Dokumen yang lebih detail sudah ada di dalam folder masing-masing. README ini hanya peta dan cara menjalankannya.

## Dokumen lain

| Dokumen | Isi |
|---|---|
| [`vm01/README.md`](vm01/README.md) | Model lab, urutan skrip, jaringan guest, volume, kegagalan jaringan, cleanup |
| [`vm01/packer/README.md`](vm01/packer/README.md) | Build `alpine-base.qcow2` dengan Packer |
| [`containers/runc/README.MD`](containers/runc/README.MD) | Catatan perintah `runc` |
| [`kubernetes/README.txt`](kubernetes/README.txt) | Catatan singkat unduh tool, buat cluster, jalankan Octant |

Konfigurasi bersama VM ada di [`vm01/00-config.sh`](vm01/00-config.sh): path lab, ukuran vCPU/RAM, nama bridge, dan alamat IP.

## Prasyarat

Pasang sesuai bagian yang mau dijalankan.

**VM**

- `qemu-system-x86_64`, `qemu-img`
- akses `/dev/kvm` (atau set `FORCE_TCG=1` kalau cuma ada TCG; jauh lebih lambat)
- `iproute2`, `bridge-utils` atau setara, sudo untuk bridge/TAP/NAT
- Packer, kalau image dasar belum ada
- ISO Alpine Standard x86_64

**Container**

- Docker Engine
- `runc` untuk bagian runtime rendah
- `curl`, `jq` dipakai di dalam container case proses (di-install skrip guest, bukan host)

**Kubernetes**

- Docker, karena kind menjalankan node sebagai container
- `curl` untuk mengunduh `kind` dan `kubectl`
- port host `80`, `443`, `30080`, `30443`, dan `16443` kosong

## Menjalankan VM

Detail lengkap ada di [`vm01/README.md`](vm01/README.md). Ringkasnya:

Dua guest memakai overlay di atas satu image dasar. Disk data hanya menempel ke VM-1. Keduanya masuk bridge yang sama lewat TAP.

![Topologi VM: image dasar, overlay, volume, bridge, dan NAT](docs/images/vm-topology.png)

`12-fail-vm2-network.sh` mematikan `tap2`. VM-1 tidak bisa mencapai `10.10.0.12` sampai `13-restore-vm2-network.sh` dijalankan. Image dasar tidak ikut terhapus saat cleanup.

Build image dasar, kalau belum ada:

![Alur build image dasar dengan Packer](docs/images/packer-build.png)

Urutan di host:

![Urutan skrip persiapan dan nyala VM di host](docs/images/vm-host-order.png)

Image dasar yang diharapkan:

```text
~/minicloud-lab/images/alpine-base.qcow2
```

Kalau belum ada, build dulu dari `vm01/` mengikuti [`vm01/packer/README.md`](vm01/packer/README.md). Letakkan ISO di `vm01/iso/alpine-standard-x86_64.iso`, salin `packer/alpine-qemu-vars.example.json` menjadi `packer/alpine-qemu-vars.json`, isi checksum SHA-256 resmi, lalu:

```bash
cd vm01
packer validate -var-file=packer/alpine-qemu-vars.json packer/alpine-qemu.json
packer build -var-file=packer/alpine-qemu-vars.json packer/alpine-qemu.json
cp output-alpine/alpine-base.qcow2 ~/minicloud-lab/images/alpine-base.qcow2
```

Siapkan host (tidak menyalakan VM dan tidak memformat disk guest):

```bash
cd vm01
./run-all-preparation.sh
```

Itu menjalankan preflight, workspace, overlay `vm1`/`vm2`, volume data, lalu bridge `qemu-br0` dengan `tap1` dan `tap2`.

Opsional, beri VM jalan ke internet:

```bash
./061-enable-vm-outside.sh
```

Nyalakan guest di terminal terpisah:

```bash
./08-run-vm1-bridge.sh
./09-run-vm2-bridge.sh
```

Di dalam guest, set IP statis (tersimpan di `/etc/network/interfaces`):

```bash
sudo ./guest-configure-ip.sh eth0 10.10.0.11/24 10.10.0.1 1.1.1.1   # VM-1
sudo ./guest-configure-ip.sh eth0 10.10.0.12/24 10.10.0.1 1.1.1.1   # VM-2
```

Volume persisten, dari dalam VM-1:

```bash
sudo ./guest-prepare-volume.sh /dev/vdb /data
```

Bersihkan jaringan host, atau hapus overlay dan volume hasil generate (image dasar tidak dihapus):

```bash
./15-cleanup-network.sh
./18-reset-generated-storage.sh
```

## Menjalankan container

### runc

Ikuti [`containers/runc/README.MD`](containers/runc/README.MD).

![Siklus hidup container runc](docs/images/runc-lifecycle.png)

`rootfs` bisa diekstrak dari image Docker, misalnya Alpine, lalu `runc` menjalankannya tanpa daemon Docker.

### Docker

Masuk ke folder case, lalu jalankan skripnya.

| Case | Perintah | Hasil |
|---|---|---|
| `containers/docker/case1` | `sh run_process.sh` | Container `myprocess1` (Alpine) menarik joke tiap `DELAY=8` detik ke `files/` |
| `containers/docker/case2` | `sh run_simple_web.sh` | Python HTTP server `webserver1`, host port **9999** |
| `containers/docker/case3` | `sh run_mysql.sh` lalu `sh run_myadmin.sh` | MySQL `mysql1` + phpMyAdmin di host port **10000** |

Password database case 3 ada di skrip (`MYSQL_ROOT_PASSWORD`). phpMyAdmin memakai `--link mysql1`, jadi MySQL harus sudah jalan.

![Alur tiga case Docker: proses, web server, dan MySQL](docs/images/docker-cases.png)

### Image custom

| Case | Build | Run | Image / port |
|---|---|---|---|
| `containers/compose/images/case1` | `sh platform/build.sh` | `sh runcontainer/run-mywebserver.sh` | `mywebserver:1.0`, Apache/PHP, host **9999** |
| `containers/compose/images/case2` | `sh platform/build.sh` | `sh runcontainer/run-mylinux.sh` | `mylinux:1.0`, desktop Firefox lewat noVNC. VNC **12111**, web **11111** |
| `containers/compose/images/case3` | `sh build.sh` | `sh run-server.sh` | `mywebserver:2.0`, Nginx + HTML statis, host **9999** |
| `containers/compose/images/case4` | `sh build.sh` | `sh run-server.sh` | `mywebserver:2.1`, Nginx + PHP-FPM, host **9999** |

Build case 2 meng-clone noVNC, jadi butuh jaringan. User desktop di image itu `user1`.

![Jalur browser ke desktop Firefox lewat noVNC](docs/images/novnc.png)

### Compose

Dari folder case:

```bash
docker compose up -d
```

Compose file masih memakai `version: '3'`. Docker Compose modern tetap membacanya.

| Case | Stack | Port host |
|---|---|---|
| `containers/compose/compose/example` | MySQL 8 + phpMyAdmin | phpMyAdmin **10000** |
| `containers/compose/compose/case1` | Nginx + HTML statis | **9999** |
| `containers/compose/compose/case2` | Nginx + sertifikat di `certs/` | **80** dan **443** |
| `containers/compose/compose/case3` | MySQL, WordPress, Nginx TLS, phpMyAdmin | **80**, **443**, phpMyAdmin dari `.env` (`PHPMYADMIN_PORT`) |
| `containers/compose/compose/case4` | MySQL 5.7, app Apache/PHP (di-build), Alpine, phpMyAdmin | app **34001**, phpMyAdmin **10000** |

Case 3 membaca [`containers/compose/compose/case3/.env`](containers/compose/compose/case3/.env). `WORDPRESS_SITEURL` mengarah ke hostname tertentu; sesuaikan `.env` dan `/etc/hosts` kalau mau dibuka dari mesin sendiri.

![Stack Compose case 3: Nginx, WordPress, MySQL, phpMyAdmin](docs/images/compose-case3.png)

Case 4 butuh build image `app` dari `platform/`. `docker compose up -d --build` dari folder case itu.

![Stack Compose case 4: Apache/PHP, MySQL, phpMyAdmin](docs/images/compose-case4.png)

Service `alpine` di case 4 tidak melayani trafik. Container itu hanya tetap hidup di network yang sama.

Hentikan stack:

```bash
docker compose down
```

Volume data (`dbdata/`, `wp_vol/`) tidak ikut terhapus. Hapus manual kalau mau mulai dari kosong.

## Menjalankan Kubernetes

Cluster dibuat dengan [kind](https://kind.sigs.k8s.io/). Nama cluster di skrip: `mylab99`. Control-plane mengekspos API di port host **16443**, plus map port **80**, **443**, **30080**, dan **30443**.

![Cluster kind: control-plane, dua worker, ingress, dan Octant](docs/images/k8s-cluster.png)

Urutan setup:

![Urutan setup cluster, ingress, workload, dan Octant](docs/images/k8s-setup.png)

### Tool

```bash
cd kubernetes/bin
sh download.sh
source set.sh
```

`download.sh` mengambil `kind` v0.11.1 dan `kubectl` stable, keduanya **linux/amd64**, ke folder ini. `source set.sh` menambahkan folder itu ke `PATH` sesi shell sekarang. Ulangi `source` di terminal baru, atau panggil binary dengan path lengkap.

### Cluster dan ingress

```bash
cd kubernetes/setup-cluster/kind
sh 1-create-cluster.sh
sh 2-set-config.sh
sh 3-install-ingress.sh
sh 4-cek-ingress.sh
```

`2-set-config.sh` mengekspor kubeconfig ke `./kubeconfig` dan meng-export `KUBECONFIG` untuk sesi itu. Terminal lain perlu:

```bash
export KUBECONFIG=/path/ke/kubernetes/setup-cluster/kind/kubeconfig
```

`4-cek-ingress.sh` menunggu pod controller ingress siap, timeout 90 detik. Kalau belum ready, jalankan lagi.

Cek node:

```bash
kubectl get nodes
```

Harusnya satu control-plane dan dua worker.

### Visualizer

[Octant](https://github.com/vmware-archive/octant) 0.25.1:

```bash
cd kubernetes/apps/1_visualizer
sh download.sh
sh run.sh
```

Buka `http://<ip-host>:22222`. Proses ditulis ke `octant.pid`.

### Workload

Apply dari folder case. `KUBECONFIG` harus sudah mengarah ke cluster `mylab99`.

**Case 1** — `kubernetes/apps/2_case1`

```bash
sh run.sh
```

Ingress `case1-ingress` (rewrite path) meneruskan:

| Path | Service |
|---|---|
| `/foo` | `foo-service:8080` (`agnhost`) |
| `/bar4` | `bar-service:8080` |
| `/counter` | `counter-service:8888` (halaman HTML sederhana) |
| `/coba` | `coba-service:80` |
| `/web1` | `web1-service:80` (Deployment nginx, 10 replika) |
| `/web2` | `web2-service:80` (StatefulSet nginx, 5 replika) |

Contoh: `http://127.0.0.1/foo/`

![Ingress case 1 dan service di belakang tiap path](docs/images/ingress-case1.png)

**Case 2** — `kubernetes/apps/3_case2`

Workload yang sama polanya, plus TLS dan image privat `royyana/mywebserver:2.1` (`coba2`, butuh `imagePullSecrets` bernama `mysecret`).

Secret yang dipakai `run.sh` sudah ada sebagai YAML:

- `docker-secret.yaml` dari `1_create_secret_for_registry.sh`
- `tls-secret.yaml` dari `2_create_tls_cert.sh` (`certs/MyCert.crt` + `certs/MyPrivate.key`)

Jalankan:

```bash
sh run.sh
```

Path ingress: `/foo`, `/bar`, `/coba`, `/coba2`. Ingress ini memakai secret TLS `mytls`.

![Ingress case 2 dengan TLS dan image privat](docs/images/ingress-case2.png)

File secret registry berisi kredensial Docker. Jangan di-commit ulang ke repo publik. Kalau repo ini dishare, rotasi tokennya.

**Case 3** — `kubernetes/apps/4_case3`

```bash
sh run.sh
```

Satu Pod `counter` yang menulis timestamp tiap detik ke stdout. Lihat dengan:

```bash
kubectl logs -f counter
```

### Hapus cluster

```bash
kind delete cluster --name mylab99
```
