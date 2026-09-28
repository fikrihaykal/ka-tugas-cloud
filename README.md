# ka-tugas-cloud

Praktikum infrastruktur cloud pada host Linux x86_64.

**Ini bukan satu sistem yang harus hidup barengan.** Ada **6 modul terpisah**. Tiap modul berdiri sendiri: jalankan, buktikan, matikan, baru lanjut modul berikutnya. Urutan di bawah hanya urutan belajar, bukan alur runtime.

![Urutan lab: VM, runc, Docker, image, Compose, Kubernetes](docs/images/lab-path.png)

## Daftar modul

| Modul | Direktori | Topik |
|---|---|---|
| **1. VM** | `vm01/` | Dua VM Alpine di QEMU, bridge, volume, simulasi putus jaringan |
| **2. runc** | `containers/runc/` | Runtime container level rendah: `run`, `exec`, `kill`, `delete` |
| **3. Docker** | `containers/docker/` | Proses Alpine, web Python, MySQL + phpMyAdmin |
| **4. Image** | `containers/compose/images/` | Build dan jalankan image custom (Apache, noVNC, Nginx) |
| **5. Compose** | `containers/compose/compose/` | Stack multi-container (Nginx, TLS, WordPress, app+MySQL) |
| **6. Kubernetes** | `kubernetes/` | Cluster kind, ingress, Octant, workload contoh |

## Cara menjalankan

1. Pilih **satu modul**.
2. Ikuti tutorial modul itu sampai selesai.
3. **Matikan** semua yang dinyalakan di modul itu.
4. Baru buka modul berikutnya.

Jangan nyalain beberapa modul sekaligus. Port **80**, **443**, **9999**, dan **10000** dipakai ulang antar modul/case. VM TCG juga makan CPU; matikan guest sebelum masuk modul Kubernetes.

Di dalam modul Docker / Image / Compose / Kubernetes, **case juga satu per satu**: nyalakan → cek → hentikan → case berikutnya.

```text
.
├── vm01/                 Modul 1 — mesin virtual
├── containers/
│   ├── runc/             Modul 2 — runc
│   ├── docker/           Modul 3 — Docker
│   └── compose/
│       ├── images/       Modul 4 — image custom
│       └── compose/      Modul 5 — Compose
└── kubernetes/           Modul 6 — Kubernetes
```

---

## Prasyarat host (sekali saja)

Pasang sebelum modul mana pun. Bukan modul praktikum.

```bash
sudo apt-get update
sudo apt-get install -y \
  docker.io qemu-system-x86 qemu-utils iptables runc \
  openssh-client curl ca-certificates unzip
sudo usermod -aG docker "$USER"
```

Keluar lalu masuk lagi supaya grup `docker` dipakai. Cek:

```bash
docker version
qemu-system-x86_64 --version
runc --version
```

Packer (hanya untuk Modul 1):

```bash
mkdir -p "$HOME/.local/bin"
curl -fsSL -o /tmp/packer.zip \
  https://releases.hashicorp.com/packer/1.11.2/packer_1.11.2_linux_amd64.zip
unzip -o /tmp/packer.zip -d "$HOME/.local/bin"
chmod +x "$HOME/.local/bin/packer"
export PATH="$HOME/.local/bin:$PATH"
packer plugins install github.com/hashicorp/qemu
packer version
```

Kalau `/dev/kvm` tidak bisa dipakai (umum di WSL), Packer dan QEMU memakai TCG. Tambahkan `export PATH="$HOME/.local/bin:$PATH"` ke shell yang menjalankan Packer.

Plugin Compose (Modul 5), bila `docker compose` belum ada:

```bash
mkdir -p "$HOME/.docker/cli-plugins"
curl -fsSL -o "$HOME/.docker/cli-plugins/docker-compose" \
  https://github.com/docker/compose/releases/download/v2.36.2/docker-compose-linux-x86_64
chmod +x "$HOME/.docker/cli-plugins/docker-compose"
docker compose version
```

---

## Modul 1 — VM

**Tujuan:** dua guest Alpine di atas satu image dasar, IP statis, volume persisten, putus/pulihkan `tap2`.

**Login guest:** `root` / `packer`  
**Jaringan:** bridge `10.10.0.1/24`, VM-1 `10.10.0.11`, VM-2 `10.10.0.12`

![Topologi VM: image dasar, overlay, volume, bridge, dan NAT](docs/images/vm-topology.png)

### 1.1 Build image dasar

ISO dan checksum sudah tertulis di `vm01/packer/alpine-qemu.json`.

```bash
cd vm01
mkdir -p iso
curl -fL -o iso/alpine-standard-3.24.1-x86_64.iso \
  https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-standard-3.24.1-x86_64.iso
sha256sum iso/alpine-standard-3.24.1-x86_64.iso
```

Checksum yang diharapkan: `f4dd613206676c62949144c8ad75fc64582099f444dd1485bae104a60f51dd26`.

Build (lama). Tanpa KVM pakai TCG:

```bash
packer build -var accelerator=tcg packer/alpine-qemu.json
mkdir -p "$HOME/minicloud-lab/images"
cp output-alpine/alpine-base.qcow2 "$HOME/minicloud-lab/images/alpine-base.qcow2"
```

Kalau KVM tersedia: `-var accelerator=kvm`.

![Alur build image dasar dengan Packer](docs/images/packer-build.png)

### 1.2 Siapkan disk dan jaringan

```bash
cd vm01
./run-all-preparation.sh
sudo ./061-enable-vm-outside.sh
```

Skrip membuat overlay `vm1`/`vm2`, volume data, bridge `qemu-br0`, `tap1`, dan `tap2`. VM belum dinyalakan.

Docker memasang policy `FORWARD` ke `DROP`. Tanpa aturan ini, guest bisa ping gateway tetapi tidak bisa ping satu sama lain:

```bash
sudo iptables -I FORWARD -i qemu-br0 -o qemu-br0 -j ACCEPT
```

Tanpa `/dev/kvm`:

```bash
export FORCE_TCG=1
```

### 1.3 Nyalakan guest

Dua terminal, masih di `vm01`:

```bash
./08-run-vm1-bridge.sh
```

```bash
./09-run-vm2-bridge.sh
```

Login `root` / `packer`. Salin skrip guest lewat HTTP di bridge. Terminal host ketiga:

```bash
cd vm01
python3 -m http.server 8765 --bind 10.10.0.1
```

Di konsol **VM-1**:

```sh
ip link set eth0 up
ip addr add 10.10.0.11/24 dev eth0
ip route add default via 10.10.0.1
cd /root
curl -fsSL -O http://10.10.0.1:8765/guest-configure-ip.sh
curl -fsSL -O http://10.10.0.1:8765/guest-prepare-volume.sh
curl -fsSL -O http://10.10.0.1:8765/guest-mount-volume.sh
bash ./guest-configure-ip.sh eth0 10.10.0.11/24 10.10.0.1 1.1.1.1
bash ./guest-prepare-volume.sh /dev/vdb /data
```

Ketik `FORMAT` saat diminta. Cek `/data/test.txt`.

Di konsol **VM-2**:

```sh
ip link set eth0 up
ip addr add 10.10.0.12/24 dev eth0
ip route add default via 10.10.0.1
cd /root
curl -fsSL -O http://10.10.0.1:8765/guest-configure-ip.sh
bash ./guest-configure-ip.sh eth0 10.10.0.12/24 10.10.0.1 1.1.1.1
```

Hentikan `python3 -m http.server` setelah skrip tersalin. Boot berikutnya memakai `/etc/network/interfaces`. Volume tidak masuk fstab; mount lagi dengan:

```sh
bash ./guest-mount-volume.sh /dev/vdb /data
cat /data/test.txt
```

### 1.4 Ping, putus `tap2`, pulihkan

Dari VM-1:

```sh
ping -c 3 10.10.0.12
```

Biarkan ping panjang berjalan (`ping 10.10.0.12`), lalu di host:

```bash
cd vm01
sudo ./12-fail-vm2-network.sh
```

Ping putus. Pulihkan:

```bash
sudo ./13-restore-vm2-network.sh
```

Ping kembali.

### 1.5 Selesai Modul 1 — matikan

Di kedua guest:

```sh
poweroff
```

Opsional, bersihkan jaringan dan disk generate (image dasar tidak ikut terhapus):

```bash
cd vm01
sudo ./15-cleanup-network.sh
./18-reset-generated-storage.sh
```

**Sebelum Modul 6 (Kubernetes):** pastikan kedua VM sudah `poweroff`. TCG makan CPU cluster.

---

## Modul 2 — runc

**Tujuan:** siklus hidup container tanpa daemon Docker: `run`, `list`, `exec`, `kill`, `delete`.

`runc` di sini butuh root. Modul ini tidak memakai port host.

![Siklus hidup container runc](docs/images/runc-lifecycle.png)

### 2.1 Rootfs dan spec

```bash
mkdir -p /tmp/runc-lab/rootfs
cd /tmp/runc-lab
cid=$(docker run -d alpine:3.18)
docker export "$cid" | sudo tar -C rootfs -xv
docker rm -f "$cid"
sudo runc spec
```

Sesuaikan `config.json`:

```bash
sudo python3 - << 'PY'
import json
with open("config.json") as f:
    cfg = json.load(f)
cfg["process"]["terminal"] = False
cfg["process"]["user"] = {"uid": 0, "gid": 0}
cfg["process"]["args"] = ["sh", "-c", "while true; do sleep 1000; done"]
cfg["root"]["readonly"] = False
with open("config.json", "w") as f:
    json.dump(cfg, f, indent=2)
PY
```

### 2.2 Jalankan dan uji

```bash
sudo runc run -d lab1
sudo runc list
sudo runc exec lab1 echo hello
sudo runc exec --user 1000:1000 lab1 echo hello-user
```

### 2.3 Selesai Modul 2 — matikan

```bash
sudo runc kill lab1 KILL
sudo runc delete lab1
```

---

## Modul 3 — Docker

**Tujuan:** menjalankan container Docker satu per satu.

**Aturan modul:** satu case → cek → `docker rm` → case berikutnya. Port **9999** dan **10000** bentrok dengan Modul 4 dan 5.

![Alur tiga case Docker: proses, web server, dan MySQL](docs/images/docker-cases.png)

### Case 1 — proses Alpine

```bash
cd containers/docker/case1
sh run_process.sh
docker exec myprocess1 ls /data
docker rm -f myprocess1
```

Container `myprocess1` menulis joke ke `files/` tiap 8 detik.

### Case 2 — web server Python (port 9999)

```bash
cd containers/docker/case2
sh run_simple_web.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/
curl -s http://127.0.0.1:9999/
docker rm -f webserver1
```

### Case 3 — MySQL dan phpMyAdmin (port 10000)

```bash
cd containers/docker/case3
sh run_mysql.sh
sh run_myadmin.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10000/
docker rm -f phpmyadmin1 mysql1
```

Password MySQL ada di `run_mysql.sh`. phpMyAdmin memakai `--link mysql1`, jadi MySQL harus sudah jalan.

### Selesai Modul 3

Pastikan tidak ada container modul ini yang masih jalan:

```bash
docker rm -f myprocess1 webserver1 phpmyadmin1 mysql1 2>/dev/null || true
```

---

## Modul 4 — Image custom

**Tujuan:** build image sendiri, lalu jalankan.

**Aturan modul:** satu case → cek → `docker rm` → case berikutnya. Port **9999** bentrok dengan Modul 3 dan 5.

### Case 1 — Apache/PHP `mywebserver:1.0` (port 9999)

Dockerfile di `platform/`. Skrip run memasang `html/` dari `runcontainer/`.

```bash
cd containers/compose/images/case1/platform
sh build.sh
cd ../runcontainer
sh run-mywebserver.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/
docker rm -f mywebserver
```

### Case 2 — desktop noVNC `mylinux:1.0`

Build mengunduh noVNC. Akun desktop: `user1`. VNC host **12111**, noVNC **11111**.

```bash
cd containers/compose/images/case2/platform
sh build.sh
cd ../runcontainer
sh run-mylinux.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:11111/
docker rm -f mylinux
```

![Jalur browser ke desktop Firefox lewat noVNC](docs/images/novnc.png)

### Case 3 — Nginx statis `mywebserver:2.0` (port 9999)

```bash
cd containers/compose/images/case3
sh build.sh
sh run-server.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/
docker rm -f webserver2
```

### Case 4 — Nginx dan PHP-FPM `mywebserver:2.1` (port 9999)

```bash
cd containers/compose/images/case4
sh build.sh
sh run-server.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/test.php
docker rm -f webserver2
```

### Selesai Modul 4

```bash
docker rm -f mywebserver mylinux webserver2 2>/dev/null || true
```

---

## Modul 5 — Compose

**Tujuan:** stack multi-container dengan `docker compose`.

**Aturan modul:** satu case → cek → `docker compose down` → case berikutnya.  
`docker compose down` tidak menghapus volume `dbdata/` dan `wp_vol/`.

Port yang bentrok: **9999**, **10000**, **80**, **443** (dengan Modul 3, 4, dan 6).

### Example — MySQL 8 dan phpMyAdmin (port 10000)

```bash
cd containers/compose/compose/example
docker compose up -d
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10000/
docker compose down
```

### Case 1 — Nginx statis (port 9999)

```bash
cd containers/compose/compose/case1
docker compose up -d
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9999/
docker compose down
```

### Case 2 — Nginx TLS (port 80 dan 443)

```bash
cd containers/compose/compose/case2
docker compose up -d
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
docker compose down
```

### Case 3 — WordPress, Nginx TLS, phpMyAdmin

`.env` memakai hostname `pm99.rm-dev.my.id`. Cek lewat `--resolve`, tanpa mengubah `/etc/hosts`. phpMyAdmin di port `PHPMYADMIN_PORT` (`30081`).

```bash
cd containers/compose/compose/case3
docker compose up -d
curl -sk --resolve pm99.rm-dev.my.id:443:127.0.0.1 \
  -o /dev/null -w '%{http_code}\n' https://pm99.rm-dev.my.id/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:30081/
docker compose down
```

![Stack Compose case 3: Nginx, WordPress, MySQL, phpMyAdmin](docs/images/compose-case3.png)

### Case 4 — aplikasi PHP, MySQL 5.7, phpMyAdmin

Aplikasi **34001**, phpMyAdmin **10000**. Service `alpine` tidak membuka port.

```bash
cd containers/compose/compose/case4
docker compose up -d --build
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:34001/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10000/
docker compose down
```

![Stack Compose case 4: Apache/PHP, MySQL, phpMyAdmin](docs/images/compose-case4.png)

### Selesai Modul 5

Pastikan semua stack Compose sudah `docker compose down` di direktori case masing-masing. Port **80** dan **443** harus kosong sebelum Modul 6.

---

## Modul 6 — Kubernetes

**Tujuan:** cluster kind lokal, ingress NGINX, Octant, workload contoh.

**Syarat:** Modul 1 (VM) sudah dimatikan. Port **80** dan **443** kosong (Modul 5 sudah `down`).

Cluster `mylab99`: 1 control-plane, 2 worker. API host **16443**. Ingress **80**, **443**, **30080**, **30443**.

`download.sh` mengambil kind **v0.20.0** (Kubernetes 1.27) dan kubectl **v1.27.16**. Manifest ingress di repo butuh Kubernetes 1.25–1.28.

![Cluster kind: control-plane, dua worker, ingress, dan Octant](docs/images/k8s-cluster.png)

### 6.1 Alat, cluster, ingress

```bash
cd kubernetes/bin
sh download.sh
source set.sh
cd ../setup-cluster/kind
sh 1-create-cluster.sh
sh 2-set-config.sh
export KUBECONFIG="$PWD/kubeconfig"
sh 3-install-ingress.sh
sh 4-cek-ingress.sh
kubectl get nodes
```

`export` di dalam `sh 2-set-config.sh` tidak masuk ke shell pemanggil. Terminal lain perlu:

```bash
export KUBECONFIG=/path/ke/kubernetes/setup-cluster/kind/kubeconfig
export PATH="/path/ke/kubernetes/bin:$PATH"
```

`4-cek-ingress.sh` menunggu controller paling lama 90 detik. Ulangi bila pod belum Ready.

### 6.2 Octant

```bash
cd kubernetes/apps/1_visualizer
sh download.sh
export KUBECONFIG=/path/ke/kubernetes/setup-cluster/kind/kubeconfig
sh run.sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:22222/
```

Antarmuka: `http://127.0.0.1:22222`. PID di `octant.pid`.

### Case 1 — ingress HTTP

```bash
cd kubernetes/apps/2_case1
sh run.sh
kubectl get pods
curl -s -o /dev/null -w 'foo %{http_code}\n' http://127.0.0.1/foo/
curl -s -o /dev/null -w 'bar4 %{http_code}\n' http://127.0.0.1/bar4/
curl -s -o /dev/null -w 'counter %{http_code}\n' http://127.0.0.1/counter/
curl -s -o /dev/null -w 'coba %{http_code}\n' http://127.0.0.1/coba/
curl -s -o /dev/null -w 'web1 %{http_code}\n' http://127.0.0.1/web1/
curl -s -o /dev/null -w 'web2 %{http_code}\n' http://127.0.0.1/web2/
```

| Path | Service |
|---|---|
| `/foo` | `foo-service:8080` (`agnhost`) |
| `/bar4` | `bar-service:8080` |
| `/counter` | `counter-service:8888` |
| `/coba` | `coba-service:80` |
| `/web1` | `web1-service:80` (Deployment nginx, 10 replika) |
| `/web2` | `web2-service:80` (StatefulSet nginx, 5 replika) |

![Ingress case 1 dan service di belakang tiap path](docs/images/ingress-case1.png)

Ingress case 1 dan case 2 sama-sama bernama `case1-ingress`. Hapus case 1 sebelum case 2:

```bash
kubectl delete \
  -f foo.yaml -f bar.yaml -f coba.yaml -f counter.yaml \
  -f web1.yaml -f web2.yaml -f ingress.yaml
```

### Case 2 — ingress HTTPS + image privat

```bash
cd kubernetes/apps/3_case2
sh run.sh
curl -sk -o /dev/null -w 'foo %{http_code}\n' https://127.0.0.1/foo/
curl -sk -o /dev/null -w 'bar %{http_code}\n' https://127.0.0.1/bar/
curl -sk -o /dev/null -w 'coba %{http_code}\n' https://127.0.0.1/coba/
curl -sk -o /dev/null -w 'coba2 %{http_code}\n' https://127.0.0.1/coba2/
kubectl get pod coba2-app
```

`/foo`, `/bar`, `/coba` menjawab 200. Pod `coba2-app` memakai image privat `royyana/mywebserver:2.1`; tanpa secret registry yang valid, pod `ImagePullBackOff` dan `/coba2` 503. Jangan memublikasikan `docker-secret.yaml`.

![Ingress case 2 dengan TLS dan image privat](docs/images/ingress-case2.png)

### Case 3 — log pod

```bash
cd kubernetes/apps/4_case3
sh run.sh
kubectl logs counter --tail=5
```

### Selesai Modul 6 — matikan

```bash
kind delete cluster --name mylab99
kill "$(cat kubernetes/apps/1_visualizer/octant.pid)" 2>/dev/null || true
```
