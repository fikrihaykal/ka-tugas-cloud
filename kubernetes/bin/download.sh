#curl -LO https://github.com/k0sproject/k0sctl/releases/download/v0.16.0/k0sctl-linux-x64
#curl -Lo ./rke  https://github.com/rancher/rke/releases/download/v1.4.10/rke_linux-amd64
#chmod a+x ./rke

# kind v0.20.0 ships Kubernetes 1.27, which matches the vendored
# ingress-nginx v1.9.4 manifest (requires 1.25-1.28). kind v0.11.1
# only provides Kubernetes 1.21, so that controller never becomes ready.
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod a+x ./kind

curl -Lo ./kubectl https://dl.k8s.io/release/v1.27.16/bin/linux/amd64/kubectl
chmod a+x ./kubectl


export PATH=$PATH:$(pwd)



