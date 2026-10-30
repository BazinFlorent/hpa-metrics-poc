# Prometheus for the HPA demo

Install the operator and Prometheus (without Grafana / Alertmanager):

```bash
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install hpa-monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f infra/prometheus/values.yaml
kubectl apply -f infra/prometheus/servicemonitor.yaml
```

The FastAPI Service in `hpa-demo` must have label `app: hpa-demo-app` and
port `name: http` targeting port 8000. Verify with:

```bash
kubectl get svc hpa-demo-app -n hpa-demo -o yaml
kubectl get servicemonitor -n monitoring
kubectl get prometheus -n monitoring
kubectl get pods -n monitoring
```

For the Prometheus UI, find its Service using `kubectl get svc -n monitoring`,
then use `kubectl port-forward -n monitoring svc/hpa-monitoring-kube-prometheus 9090:9090`
if that is the observed name. Query `up{namespace="hpa-demo"}` and
`demo_http_requests_total`. Generate several requests to `/work` before querying
`rate(demo_http_requests_total[1m])`.
