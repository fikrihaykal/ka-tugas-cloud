#curl -LO https://github.com/k0sproject/k0sctl/releases/download/v0.16.0/k0sctl-linux-x64
#curl -Lo ./rke  https://github.com/rancher/rke/releases/download/v1.4.10/rke_linux-amd64
#chmod a+x ./rke
#https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64

# kind v0.33.0 defaults to Kubernetes 1.37; vendored ingress-nginx v1.9.4 needs 1.25–1.28.
# cluster-config.yaml pins kindest/node v1.28.13 so the controller can become Ready.
curl -Lo ./kind https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64
chmod a+x ./kind

curl -Lo ./kubectl https://dl.k8s.io/release/v1.28.13/bin/linux/amd64/kubectl
chmod a+x ./kubectl


curl -Lo ./helm.tar.gz "https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz"
tar -xzvf helm.tar.gz
mv linux-amd64/helm .
rm -rf linux-amd64
rm -f helm.tar.gz
chmod +x ./helm
export PATH=$PATH:$(pwd)



