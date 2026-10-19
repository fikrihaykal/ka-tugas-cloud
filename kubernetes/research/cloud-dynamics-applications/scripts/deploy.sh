#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

CALLER_HOST_IP=${HOST_IP-}
CALLER_NAMESPACE=${NAMESPACE-}
. "$ROOT/config/environment.env"
[ -n "$CALLER_HOST_IP" ] && HOST_IP=$CALLER_HOST_IP
[ -n "$CALLER_NAMESPACE" ] && NAMESPACE=$CALLER_NAMESPACE

APP=${1:?Usage: deploy.sh APP}

case "$APP" in
  stateless-api|cpu-bound|memory-stateful|database-api|cache-api|microservices|online-boutique) ;;
  *) echo "Unknown application: $APP" >&2; exit 1 ;;
esac

kubectl apply -f "$ROOT/k8s/namespace.yaml"
if [ "$APP" = online-boutique ]; then
  # Release manifest lives in the sibling ecommerce repo, outside this kustomize root.
  kubectl kustomize --load-restrictor LoadRestrictionsNone "$ROOT/k8s/online-boutique" | kubectl apply -f -
else
  kubectl apply -f "$ROOT/k8s/$APP.yaml"
fi

sed \
  -e "s/APP_NAME/$APP/g" \
  -e "s/HOST_IP/$HOST_IP/g" \
  "$ROOT/k8s/ingress-template.yaml" | kubectl apply -f -

if [ "$APP" = online-boutique ]; then
  for name in $(kubectl -n "$NAMESPACE" get deployment -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}'); do
    kubectl -n "$NAMESPACE" rollout status "deployment/$name" --timeout=180s
  done
else
  kubectl -n "$NAMESPACE" rollout status deployment/"$APP" --timeout=180s
fi

echo
echo "Application : $APP"
echo "HOST_IP     : $HOST_IP"
echo "URL         : http://$APP.$HOST_IP.sslip.io/"
