#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

CALLER_NAMESPACE=${NAMESPACE-}
. "$ROOT/config/environment.env"
[ -n "$CALLER_NAMESPACE" ] && NAMESPACE=$CALLER_NAMESPACE

APP=${1:?Usage: remove.sh APP}

kubectl -n "$NAMESPACE" delete ingress "$APP" --ignore-not-found
if [ "$APP" = online-boutique ]; then
  kubectl kustomize --load-restrictor LoadRestrictionsNone "$ROOT/k8s/online-boutique" | kubectl delete -f - --ignore-not-found
else
  kubectl delete -f "$ROOT/k8s/$APP.yaml" --ignore-not-found
fi
