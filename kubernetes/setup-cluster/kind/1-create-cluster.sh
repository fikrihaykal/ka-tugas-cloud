# kind nodes share the host inotify limits. Default 128 is too low: kube-proxy
# and ingress-nginx crash with "too many open files", and host :80 resets.
# Re-run these two lines after every WSL/host reboot (sysctl does not persist).
sudo sysctl -w fs.inotify.max_user_instances=8192
sudo sysctl -w fs.inotify.max_user_watches=1048576
kind create cluster --name mylab99 --config cluster-config.yaml
