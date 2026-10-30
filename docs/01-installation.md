## Construction de l'environnement du POC

### 1. Initialisation de l'environnement Kubernetes

Le POC s'appuie sur un cluster Kubernetes local créé par l'outil `platform-bootstrap`.

Le bootstrap prend en charge la création du cluster kind, de ses trois nœuds, ainsi que des composants d'infrastructure associés.

Depuis la racine du projet :

```bash
platform-bootstrap -n hpa-metrics-poc bootstrap
```

**Vérification du cluster :**

```bash
kind get clusters
kubectl config current-context
kubectl get nodes -o wide
```

Résultats attendus :

- Cluster : `hpa-metrics-poc`
- Contexte Kubernetes : `kind-hpa-metrics-poc`
- Version Kubernetes : `v1.37.0`
- Trois nœuds à l'état `Ready` : un control-plane et deux workers

Si le contexte Kubernetes n'est pas défini :

```bash
kind export kubeconfig --name hpa-metrics-poc
```

### 2. Construction de l'image applicative

L'application FastAPI est construite localement avec Docker.

Depuis la racine du dépôt :

```bash
docker build -t hpa-metrics-poc-app:0.1.1 ./app
```

Vérifier la présence de l'image :

```bash
docker image ls hpa-metrics-poc-app
```

### 3. Chargement de l'image dans kind

Pour simplifier le POC, l'image est directement chargée dans les nœuds kind, sans publication dans une registry OCI.

```bash
kind load docker-image hpa-metrics-poc-app:0.1.1 \
  --name hpa-metrics-poc
```

Le Deployment Kubernetes utilise `imagePullPolicy: IfNotPresent` pour exploiter l'image présente dans le runtime des nœuds.

### 4. Déploiement de l'application

Créer le namespace et déployer l'application :

```bash
kubectl apply -f app/k8s/namespace.yaml
kubectl apply -f app/k8s/deployment.yaml
kubectl apply -f app/k8s/service.yaml
```

Attendre la disponibilité du Deployment :

```bash
kubectl rollout status deployment/hpa-metrics-poc-app \
  -n hpa-metrics-poc
```

Vérifier les ressources Kubernetes :

```bash
kubectl get pods,deploy,svc -n hpa-metrics-poc
```

**Résultats attendus :**

- Un Deployment `hpa-metrics-poc-app` disponible
- Un Pod FastAPI à l'état `1/1 Running`
- Un Service `hpa-metrics-poc-svc` de type `ClusterIP`

Le déploiement démarre volontairement avec un seul replica. Le nombre de replicas sera ensuite piloté par le HPA.

### 5. Validation du Service Kubernetes

Vérifier que le Service découvre correctement les Pods applicatifs :

```bash
kubectl get endpointslice -n hpa-metrics-poc \
  -l kubernetes.io/service-name=hpa-metrics-poc-svc
```

Le Service doit disposer d'un endpoint correspondant au Pod FastAPI, sur le port 8000.

Cette vérification permet de confirmer la cohérence des labels et sélecteurs Kubernetes.

### 6. Validation des endpoints applicatifs

Dans un premier terminal, ouvrir un accès local vers le Service :

```bash
kubectl port-forward -n hpa-metrics-poc \
  svc/hpa-metrics-poc-svc 8081:80
```

Dans un second terminal, vérifier la santé de l'application :

```bash
curl -s http://localhost:8081/health
```

Résultat attendu :

```json
{"status":"ok"}
```

### 7. Validation de l'initialisation des métriques Prometheus

L'application initialise ses compteurs Prometheus dès le démarrage, avant toute requête métier.

Cette initialisation permet aux collecteurs de découvrir les séries utilisées pour l'autoscaling, même lorsqu'aucune charge n'est encore présente.

Sans appeler `/work`, exécuter :

```bash
curl -s http://localhost:8081/metrics \
  | grep '^demo_http_requests_total'
```

**Résultat attendu :**

```text
demo_http_requests_total{method="GET",mode="cpu",status="200"} 0.0
demo_http_requests_total{method="GET",mode="io",status="200"} 0.0
```

La présence des deux séries à zéro confirme leur initialisation au démarrage du Pod.

### 8. Validation d'un traitement applicatif

Déclencher une requête simulant 200 ms de traitement CPU :

```bash
curl -s \
  "http://localhost:8081/work?mode=cpu&duration_ms=200"
```

Interroger à nouveau les métriques :

```bash
curl -s http://localhost:8081/metrics \
  | grep '^demo_http_requests_total'
```

Le compteur correspondant au mode `cpu` doit avoir augmenté de 1.

Cette vérification confirme le bon fonctionnement de l'instrumentation applicative.

### Critères de validation du socle applicatif

| Contrôle | Critère attendu |
|---|---|
| Bootstrap | Cluster kind opérationnel |
| Nœuds Kubernetes | 3 nœuds `Ready` |
| Image Docker | Version `0.1.1` construite |
| Chargement kind | Image disponible dans le cluster |
| Deployment | 1 replica disponible |
| Service | Endpoint FastAPI découvert |
| Healthcheck | HTTP 200 |
| Métriques initiales | Séries CPU et I/O présentes à zéro |
| Traitement CPU | Incrémentation du compteur |

**Jalon atteint :** le socle Kubernetes et l'application instrumentée sont déployés et vérifiés.

L'étape suivante consiste à installer Prometheus et Prometheus Operator, puis à configurer le `ServiceMonitor` afin de collecter les métriques applicatives directement depuis Kubernetes.

### Destruction de l'environnement

Le cluster et les composants créés par le bootstrap peuvent être supprimés avec :

```bash
platform-bootstrap -n hpa-metrics-poc destroy
```

Cette opération ne supprime pas automatiquement les images conservées dans le cache local du moteur Docker.

## Installation et validation de Prometheus

### 1. Configuration

Le POC utilise `kube-prometheus-stack`, limité à Prometheus et Prometheus Operator, sans Grafana, Alertmanager ni collecteurs d'infrastructure.

Deux fichiers définissent la configuration :

- `infra/prometheus/values.yaml` : configuration Helm, collecte toutes les 10 secondes, rétention de 6 heures et sélection des ServiceMonitors portant le label `monitoring: hpa-metrics-poc`.
- `infra/prometheus/servicemonitor.yaml` : découverte du Service `hpa-metrics-poc-svc` dans le namespace `hpa-metrics-poc`, sur l'endpoint `/metrics`.

### 2. Vérification du rendu Helm

Depuis la racine du projet :

```bash
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts

helm repo update

helm template hpa-metrics-poc-monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f infra/prometheus/values.yaml \
  > /tmp/hpa-metrics-poc-prometheus.yaml
```

La commande doit se terminer sans erreur. Les manifests générés sont enregistrés dans `/tmp`.

### 3. Installation de Prometheus

```bash
helm upgrade --install hpa-metrics-poc-monitoring \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f infra/prometheus/values.yaml \
  --wait
```

Vérifier les ressources :

```bash
kubectl get prometheus -n monitoring
kubectl get pods,svc -n monitoring
```

**Résultat attendu :** un Prometheus disponible (`READY=1`, `AVAILABLE=True`), ainsi que les Pods Prometheus et Operator en état `Running`.

### 4. Activation de la collecte FastAPI

```bash
kubectl apply -f infra/prometheus/servicemonitor.yaml
```

Vérifier :

```bash
kubectl get servicemonitor -n monitoring --show-labels
```

Le ServiceMonitor `hpa-metrics-poc-app` doit porter le label `monitoring=hpa-metrics-poc`.

### 5. Validation via l'interface Prometheus

Ouvrir un port-forward :

```bash
kubectl port-forward -n monitoring \
  svc/hpa-metrics-poc-monitoring-prometheus 9090:9090
```

Accéder à [http://localhost:9090](http://localhost:9090), puis à **Status → Target health**.

![Découverte de FastAPI dans Prometheus](images/prometheus-targets.png)

**Résultat constaté :** la cible `serviceMonitor/monitoring/hpa-metrics-poc-app/0` est à l'état `UP` (1/1). Prometheus collecte les métriques du Pod FastAPI sur le port 8000.

### 6. Validation des métriques Prometheus

Dans l'onglet Query, exécuter :

**Disponibilité de la cible :**

```promql
up{namespace="hpa-metrics-poc"}
```

Résultat attendu : `1`.

**Compteurs initialisés au démarrage :**

```promql
demo_http_requests_total{namespace="hpa-metrics-poc"}
```

Résultat attendu : séries `cpu` et `io` présentes à zéro, même sans trafic métier.

**Débit HTTP par Pod :**

```promql
sum by (namespace, pod) (
  rate(demo_http_requests_total{mode="cpu"}[1m])
)
```

Résultat attendu : une série par Pod avec un débit initial de `0 RPS`, après au moins deux collectes.

### Critère de validation

Prometheus découvre automatiquement FastAPI via le ServiceMonitor, collecte les compteurs applicatifs préinitialisés et permet le calcul du RPS par Pod.

**Jalon : collecte des métriques opérationnelle.**

Étape suivante : installation de Prometheus Adapter et exposition des métriques via l'API Kubernetes `custom.metrics.k8s.io`.

### Diagnostic de Prometheus Adapter

En cas d'absence de métriques ou d'erreur de lecture depuis Kubernetes :

**Vérifier l'état de l'APIService :**

```bash
kubectl describe apiservice v1beta1.custom.metrics.k8s.io
```

**Consulter les logs de l'adapter :**

```bash
kubectl logs -n monitoring \
  -l app.kubernetes.io/instance=hpa-metrics-poc-adapter \
  --tail=100
```

**Vérifier le Service Prometheus :**

```bash
kubectl get svc hpa-metrics-poc-monitoring-prometheus \
  -n monitoring
```

**Vérifier la configuration Helm appliquée :**

```bash
helm get values hpa-metrics-poc-adapter -n monitoring
```

Points de diagnostic :

| Symptôme | Vérification |
|---|---|
| APIService indisponible | État et logs de l'adapter |
| `resources: []` | Présence de la série dans Prometheus et règle `seriesQuery` |
| Métrique découverte, mais lecture impossible | Mapping `namespace` / `pod` et requête `metricsQuery` |
| Valeur `0` | Absence de trafic ou fenêtre `rate()` |
| Métrique absente après démarrage | Initialisation des compteurs et cycles de collecte |

La découverte d'une métrique par Kubernetes ne garantit pas que sa valeur soit disponible. Il faut valider séparément l'enregistrement dans l'API et la lecture effective d'une `MetricValueList`.
