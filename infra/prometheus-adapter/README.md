# Prometheus Adapter — métriques personnalisées

## Objectif

Exposer `http_requests_per_second` pour les Pods de `hpa-demo` via l'API Kubernetes `custom.metrics.k8s.io/v1beta1`.

La règle est définie dans `values.yaml`. Elle utilise le compteur `demo_http_requests_total` et calcule le taux sur une minute pour les requêtes en mode `cpu`. La métrique exposée est un débit **par seconde**, et non un compteur cumulatif.

## Installation

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install hpa-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  -f infra/prometheus-adapter/values.yaml \
  --wait
```

## Contrôles

```bash
kubectl get pods -n monitoring
kubectl get apiservice v1beta1.custom.metrics.k8s.io
kubectl get --raw '/apis/custom.metrics.k8s.io/v1beta1' | python -m json.tool
kubectl get --raw '/apis/custom.metrics.k8s.io/v1beta1/namespaces/hpa-demo/pods/%2A/http_requests_per_second' | python -m json.tool
```

La découverte de `pods/http_requests_per_second` dans la liste API confirme seulement l'enregistrement. La dernière commande doit retourner un objet `MetricValueList` contenant une valeur associée à chaque Pod ciblé, par exemple `value: "9000m"` pour 9 requêtes/seconde. Un `value: "0"` est normal sans trafic.

Pour générer du trafic, conserver un port-forward sur l'application :

```bash
kubectl port-forward -n hpa-demo svc/hpa-demo-app 8081:80
```

Dans un autre terminal :

```bash
while true; do
  curl -fsS 'http://localhost:8081/work?mode=cpu&duration_ms=100' >/dev/null || break
done
```

Pendant le trafic, répéter l'interrogation de l'API Kubernetes. Le premier résultat peut demander deux scrapes Prometheus et un cycle de découverte de l'adapter.

## Diagnostic

```bash
kubectl describe apiservice v1beta1.custom.metrics.k8s.io
kubectl logs -n monitoring deployment/hpa-adapter-prometheus-adapter --tail=100
kubectl get svc hpa-monitoring-kube-promet-prometheus -n monitoring
```

Si le nom du Deployment de l'adapter diffère selon la version du chart, le retrouver avec `kubectl get deployments -n monitoring`.

**Périmètre :** aucun HPA n'est installé à cette étape. Les règles External Metrics seront ajoutées ultérieurement.
