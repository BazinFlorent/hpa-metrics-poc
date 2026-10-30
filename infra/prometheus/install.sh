kubectl create namespace monitoring \
  --dry-run=client -o yaml | kubectl apply -f -

helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts

helm repo update

helm upgrade --install hpa-monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f infra/prometheus/values.yaml

# Activation de la collecte FastAPI
kubectl apply -f infra/prometheus/servicemonitor.yaml