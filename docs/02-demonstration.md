# Scénarios de démonstration — HPA Metrics POC

> **Statut au 31 octobre 2026 :** socle Custom Metrics et scénarios **S1/S2 validés** (montée 1 → 3 replicas, retour 3 → 1). Comparaison CPU/RPS, charges par paliers et External Metrics restent à réaliser.
>
> **Objectif :** démontrer comment Kubernetes adapte le nombre de Pods selon différents signaux de charge, puis analyser les délais, les limites et les conditions d'éligibilité d'une application à l'autoscaling.

## 1. Cadre et règles communes

Le socle est construit selon [01-installation.md](01-installation.md). Les principes de fonctionnement sont décrits dans [03-architecture.md](03-architecture.md).

| Élément | Valeur du POC |
|---|---|
| Cluster | `kind-hpa-metrics-poc` |
| Namespace applicatif | `hpa-metrics-poc` |
| Deployment | `hpa-metrics-poc-app` |
| Service | `hpa-metrics-poc-svc` |
| API Custom Metrics | `custom.metrics.k8s.io/v1beta1` |
| Métrique Custom | `http_requests_per_second` (par Pod, mode CPU) |
| Métrique source | `demo_http_requests_total` |
| Mesure RPS | `rate(...[1m])` |
| Point de départ S1/S2 | 1 replica, HPA RPS créé pour le test |

**Précautions de démonstration :**

- **Un seul HPA à la fois** pour le Deployment ; ne pas faire concourir plusieurs autoscalers sur la même cible.
- Le `spec.replicas` du Deployment sert à l'initialisation. Une fois le HPA actif, éviter de réappliquer un manifeste qui force ce nombre pendant le test.
- L'accès par `kubectl port-forward svc/...` sert aux premiers essais. Pour une charge reproductible et la comparaison des replicas, préférer un générateur **dans le cluster** ou un point d'entrée stable ; vérifier que l'acheminement répartit réellement les requêtes. Un port-forward vers un Service peut rester attaché à un seul Pod pendant la session et fausser la démonstration multi-replicas.
- Les valeurs de replicas calculées ci-dessous sont **indicatives**, non garanties : tolérance, disponibilité des métriques, comportement HPA et délais d'initialisation interviennent.
- Une augmentation de replicas ne garantit ni une réduction de latence ni une augmentation du débit : cela dépend notamment de la capacité réelle de l'application et de l'absence de goulot externe.

### Tableau de bord de contrôle commun

Dans des terminaux distincts :

```bash
kubectl get pods -n hpa-metrics-poc -w
```

```bash
kubectl get hpa -n hpa-metrics-poc -w
```

```bash
kubectl get events -n hpa-metrics-poc --sort-by=.lastTimestamp
```

Pour examiner les décisions :

```bash
kubectl describe hpa -n hpa-metrics-poc
```

Requête PromQL de référence :

```promql
sum by (namespace, pod) (
  rate(demo_http_requests_total{namespace="hpa-metrics-poc",mode="cpu"}[1m])
)
```

Mesures à consigner pour chaque essai : RPS total réellement atteint, RPS par Pod, nombre de replicas désiré/réel, délai entre début de charge et premier scale-up, délai jusqu'aux Pods `Ready`, erreurs HTTP et latence p95.

## 2. Vue d'ensemble du storyboard

| Scénario | Question démontrée | Signal | Statut |
|---|---|---|---|
| S0 — État de référence | Kubernetes lit-il une métrique métier sans HPA ? | Custom Metrics API | Socle validé |
| S1 — Montée en charge RPS | Le HPA augmente-t-il les replicas sur RPS/Pod ? | Custom `Pods` | **Validé** |
| S2 — Retour à la normale | Le HPA réduit-il les replicas de manière stabilisée ? | Custom `Pods` | **Validé** |
| S3 — Comparaison CPU / RPS | Deux signaux produisent-ils des décisions différentes ? | CPU puis Custom | À réaliser |
| S4 — Charge par paliers et saturation | Comment la boucle réagit-elle à des paliers et à un pic ? | k6, Custom | Préparation : k6 constant 15 RPS validé en S1 ; paliers à réaliser |
| S5 — Charge globale indépendante | Le HPA peut-il scaler sur une file simulée ? | External `AverageValue` | À concevoir et réaliser |
| S6 — Limites d'architecture | Où s'arrêtent les bénéfices du HPA ? | Readiness, warmup, goulots | À réaliser |

## 3. S0 — Vérifier le socle, sans HPA

**Intention :** distinguer exposition d'une métrique et pilotage d'un Deployment.

1. Vérifier qu'aucun HPA ne cible notre application :

   ```bash
   kubectl get hpa -n hpa-metrics-poc
   ```

2. Vérifier le Pod, sa santé et l'exposition de la métrique :

   ```bash
   kubectl get deployment,pods -n hpa-metrics-poc
   kubectl get --raw \
     '/apis/custom.metrics.k8s.io/v1beta1/namespaces/hpa-metrics-poc/pods/%2A/http_requests_per_second' \
     | python -m json.tool
   ```

**Observation déjà validée lors de la construction :** l'API a retourné une valeur `6614m`, soit **6,614 RPS**, pour un Pod sous charge. Cela ne prouve pas encore le fonctionnement d'un HPA.

**Message d'architecture :** Prometheus collecte ; Prometheus Adapter expose ; le HPA, s'il est créé, prend la décision de scaling.

## 4. S1 — Premier HPA sur les RPS par Pod

**Hypothèse :** en fixant un objectif de **5 RPS moyens par Pod**, une charge suffisamment élevée entraîne une augmentation du nombre de replicas.

### Préparation

Manifeste `autoscaling/hpa-custom-rps.yaml` **appliqué et validé** :

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-metrics-poc-rps
  namespace: hpa-metrics-poc
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hpa-metrics-poc-app
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "5"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 2
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
```

Appliquer et vérifier :

```bash
kubectl apply -f autoscaling/hpa-custom-rps.yaml
kubectl get hpa hpa-metrics-poc-rps -n hpa-metrics-poc
kubectl describe hpa hpa-metrics-poc-rps -n hpa-metrics-poc
```

### Charge k6 utilisée

Le test validé utilise un **Job k6 exécuté dans le cluster** contre le Service Kubernetes (pas de port-forward), avec un scénario `constant-arrival-rate` : **15 itérations/seconde visées pendant 3 minutes**, chaque itération envoyant une requête `GET /work?mode=cpu&duration_ms=100`. Le débit effectivement obtenu doit être confirmé dans le résumé k6 pour toute comparaison chiffrée ultérieure.

Fichiers utilisés : `load-tests/constant-load.js` et `load-tests/k8s/job-constant-load.yaml`. Le Job charge le script depuis un ConfigMap `hpa-k6-script`.

```bash
kubectl create configmap hpa-k6-script \
  --from-file=constant-load.js=load-tests/constant-load.js \
  -n hpa-metrics-poc \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f load-tests/k8s/job-constant-load.yaml
kubectl logs -n hpa-metrics-poc job/hpa-k6-s1 -f
```

Surveillance simultanée :

```bash
watch -n 2 'kubectl get hpa,pods -n hpa-metrics-poc'
```

Pour les décisions du contrôleur :

```bash
kubectl describe hpa hpa-metrics-poc-rps -n hpa-metrics-poc
```

### Résultats observés — 31 octobre 2026

| Indicateur | Observation |
|---|---|
| Cible du HPA | `5` RPS moyens par Pod |
| Charge k6 configurée | 15 requêtes/s visées pendant 3 min |
| Replicas | **1 → 2 → 3** |
| Valeur `TARGETS` observée à 3 replicas | `4980m/5`, soit **4,98 RPS/Pod** |
| Pods applicatifs à 3 replicas | Trois Pods `1/1 Running` |
| Pod k6 | `Completed` |
| Événements HPA | Deux événements `SuccessfulRescale`, motifs `pods metric http_requests_per_second above target` |

![HPA et Pods pendant le palier de charge — 3 replicas](images/hpa-s1-trois-replicas.png)

Les trois replicas sont cohérents avec la cible : **15 RPS offerts / 5 RPS par Pod = 3 Pods**, sous réserve du débit effectivement soutenu. Le chiffre `4980m` constitue une mesure ponctuelle du HPA, et non une moyenne sur la totalité du test.

**Résultat S1 : validé.** Le HPA a augmenté la capacité sur une métrique applicative personnalisée, sans KEDA.

## 5. S2 — Scale-down et stabilisation

**Hypothèse :** à l'arrêt de k6, la métrique RPS retourne à zéro puis le HPA revient progressivement à `minReplicas: 1`.

### Procédure

Laisser terminer le Job k6 de S1, puis continuer à observer :

```bash
watch -n 2 'kubectl get hpa,pods -n hpa-metrics-poc'
```

```bash
kubectl describe hpa hpa-metrics-poc-rps -n hpa-metrics-poc
```

### Résultats observés — 31 octobre 2026

Chronologie des événements `SuccessfulRescale` :

```text
New size: 2; reason: pods metric http_requests_per_second above target
New size: 3; reason: pods metric http_requests_per_second above target
New size: 2; reason: All metrics below target
```

Le retour final à un replica est confirmé par :

```text
NAME                  REFERENCE                       TARGETS   MINPODS   MAXPODS   REPLICAS
hpa-metrics-poc-rps   Deployment/hpa-metrics-poc-app   0/5       1         5         1
```

**Résultat S2 : validé.** La réduction observée suit **3 → 2 → 1**, jusqu'au minimum autorisé. `TARGETS=0/5` signifie un RPS moyen nul et non « zéro replica ».

**Interprétation :** la descente dépend de la fenêtre `rate(...[1m])`, des cycles de scrape, de la réconciliation HPA et de `scaleDown.stabilizationWindowSeconds: 60`. Cette dernière n'est **pas** une promesse de retour en 60 secondes.

### Synthèse S1/S2

| Étape | Charge / signal | Replicas |
|---|---|---:|
| Repos initial | Environ 0 RPS | 1 |
| Première augmentation | RPS supérieur à 5/Pod | 2 |
| Charge maintenue | `TARGETS=4980m/5` au moment de la capture | 3 |
| Arrêt du Job | Débit en décroissance puis nul | 3 → 2 |
| Retour au repos | `TARGETS=0/5` | 1 |

**Limite des preuves collectées :** nous n'avons pas encore conservé le résumé complet de k6 (`http_reqs`, `dropped_iterations`, erreurs et latence p95) ni les horodatages absolus des décisions HPA. Il serait utile de les capturer lors d'une éventuelle répétition du test, mais ils ne sont pas requis pour confirmer les scale-up/scale-down déjà observés.

## 6. S3 — Comparer HPA CPU et HPA RPS

**Objectif :** montrer qu'une métrique de ressources et une métrique applicative ne décrivent pas le même phénomène.

**Prérequis :** installer et vérifier Metrics Server (il n'est pas fourni automatiquement par Prometheus) :

```bash
kubectl top pods -n hpa-metrics-poc
kubectl get apiservice v1beta1.metrics.k8s.io
```

Si ces commandes échouent, **ne pas lancer S3** avant d'avoir établi `metrics.k8s.io`.

Préparer `autoscaling/hpa-cpu.yaml` avec `autoscaling/v2`, `minReplicas: 1`, `maxReplicas: 5` et une métrique `Resource` CPU à une cible de **60 % de la request** (`100m` actuellement). Ce seuil correspond à environ `60m` de CPU moyen par Pod, et non à 60 % de la limite CPU.

Exécuter les expériences **successivement**, jamais avec les deux HPA actifs :

```bash
kubectl delete -f autoscaling/hpa-custom-rps.yaml --ignore-not-found
kubectl scale deployment/hpa-metrics-poc-app --replicas=1 -n hpa-metrics-poc
kubectl apply -f autoscaling/hpa-cpu.yaml
```

Tester une charge CPU, consigner replicas/latence/RPS, puis revenir à l'état initial :

```bash
kubectl delete -f autoscaling/hpa-cpu.yaml --ignore-not-found
kubectl scale deployment/hpa-metrics-poc-app --replicas=1 -n hpa-metrics-poc
kubectl apply -f autoscaling/hpa-custom-rps.yaml
```

Rejouer un **profil de charge identique** et comparer. Compléter par un test `mode=io` : notre règle Custom filtre `mode="cpu"`, donc ce second profil ne peut pas être utilisé tel quel pour démontrer la supériorité d'un autoscaling métier. Une comparaison I/O équitable nécessiterait une règle Custom englobant ce trafic ou une métrique de concurrence distincte.

**Message d'architecture :** choisir un signal en fonction de la capacité réellement limitante, et non de sa seule disponibilité.

## 7. S4 — Charges reproductibles avec k6

**Objectif :** remplacer la boucle `curl` séquentielle par un trafic dont le débit offert est contrôlé, et mettre en évidence les délais de réaction.

### Préparation

Préférer un exécuteur k6 **`constant-arrival-rate`** ou **`ramping-arrival-rate`**, qui pilote le rythme de démarrage des itérations indépendamment du temps de réponse. Vérifier que le nombre de VUs disponibles suffit à tenir le débit voulu.

Deux parcours sont possibles :

- **Exploration locale :** k6 depuis le poste via un port-forward, utile pour tester les scripts mais insuffisant pour démontrer sans réserve la répartition entre plusieurs Pods.
- **Démonstration multi-replicas :** k6 lancé dans le cluster contre `http://hpa-metrics-poc-svc.hpa-metrics-poc.svc.cluster.local/work`, pour passer par le Service et ses endpoints.

Exemple de scénario **à créer** dans `load-tests/constant-load.js` :

```javascript
import http from 'k6/http';

const baseUrl = __ENV.BASE_URL || 'http://localhost:8081';
const rate = Number(__ENV.RATE || 12);

export const options = {
  discardResponseBodies: true,
  scenarios: {
    charge: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration: '4m',
      preAllocatedVUs: 10,
      maxVUs: 50,
    },
  },
};

export default function () {
  http.get(`${baseUrl}/work?mode=cpu&duration_ms=100`);
}
```

Pour un essai local préliminaire (k6 installé et port-forward actif) :

```bash
k6 run -e BASE_URL=http://localhost:8081 -e RATE=12 load-tests/constant-load.js
```

**Attention :** ceci est un exemple de script, non un test déjà exécuté. L'exécution dans le cluster, le packaging et le suivi des résultats k6 restent à construire.

### Paliers proposés

| Phase | Débit offert indicatif | Intention |
|---|---:|---|
| Baseline | 2 RPS | Pas de scaling attendu |
| Palier 1 | 8 RPS | Premier scale-up possible |
| Palier 2 | 15 RPS | Scaling supplémentaire possible |
| Pic | 25 RPS | Observer les retards et erreurs éventuelles |
| Retour | 0–2 RPS | Stabilisation et scale-down |

Les paliers sont **des hypothèses à calibrer**, pas des seuils garantissant un nombre exact de replicas. Mesurer le débit **effectivement réalisé**, les itérations abandonnées, les codes HTTP, la latence p95 et les limites CPU.

### Critères de succès

Reconstituer une chronologie datée : arrivée de la charge → hausse de la métrique → recommandation HPA → création du Pod → Pod `Ready` → éventuelle modification de latence et débit.

## 8. S5 — External Metrics : une file de travail simulée

**Statut : scénario conceptuel, non encore implémenté.** Le POC actuel n'expose aucune External Metric (`rules.external: []`).

**Question :** le HPA peut-il augmenter les replicas selon une charge globale, non attribuée individuellement à des Pods ?

### Modèle cible

Une source (simulateur de file ou petit producteur de métriques) publiera une gauge de type `demo_queue_messages_pending`, collectée par Prometheus. Une règle **External** de Prometheus Adapter exposera `queue_messages_pending` via `external.metrics.k8s.io`. Le HPA utilisera `type: External`, `target.type: AverageValue`.

```mermaid
flowchart LR
    Q["File simulée / gauge"] --> P["Prometheus"]
    P --> A["Prometheus Adapter"]
    A --> API["external.metrics.k8s.io"]
    API --> HPA["HPA External"]
    HPA --> D["Deployment de workers"]
```

**Exemple pédagogique :** si la file contient 450 messages et que la cible est de 100 messages par Pod (`AverageValue`), le calcul de base conduit à `ceil(450/100) = 5` replicas, sous réserve des règles du HPA.

### Préparation restant à faire

1. Définir la sémantique de la file et sa consommation réelle : une gauge manipulée manuellement illustre la boucle, mais pas le fonctionnement d'un système de workers.
2. Ajouter la série à la collecte Prometheus et configurer `rules.external`.
3. Vérifier `v1beta1.external.metrics.k8s.io` et interroger la valeur depuis Kubernetes.
4. Créer `autoscaling/hpa-external-queue.yaml`, puis générer une montée de backlog.
5. Observer la descente lorsque le backlog se résorbe.

**Point de comparaison :** Custom `Pods` reflète une métrique associée à chaque Pod ; External reflète une valeur globale, éventuellement issue d'un système hors cluster. Leur source technique peut pourtant être la même : Prometheus.

## 9. S6 — Limites et critères d'architecture

Ce scénario est une **discussion structurée à partir des mesures**, plutôt qu'un résultat présumé.

| Sujet | Manipulation ou observation | Message à retenir |
|---|---|---|
| Readiness | Observer l'instant de passage `Ready` des nouveaux Pods | `Ready` doit signifier apte à traiter, pas seulement HTTP 200 |
| Warmup | Ajouter ultérieurement un délai de démarrage simulé | Un Pod créé n'apporte pas immédiatement de capacité utile |
| Mesure | Comparer début du trafic, `rate[1m]` et métrique HPA | Le signal est retardé par les fenêtres de collecte et de décision |
| Répartition | Comparer RPS par Pod sous charge distribuée | Le gain dépend de l'équilibrage effectif |
| Limite de replicas | Pousser la charge au-delà de `maxReplicas` | Le HPA ne crée pas une capacité infinie |
| Throttling / gateway | Discuter un goulot situé en amont, par exemple APIM | Ajouter des Pods ne corrige pas une limitation de gateway |
| Fiabilité | Relever erreurs, p95 et débits avant/après | Le scaling est un moyen, pas un SLO à lui seul |

## 10. Synthèse et traçabilité des résultats

Pour les prochains scénarios, et en complément des résultats S1/S2 ci-dessus, renseigner après exécution :

| Champ | Valeur à relever |
|---|---|
| Date / version du POC | À compléter |
| Scénario / fichier HPA | À compléter |
| Profil k6 et débit réel | À compléter |
| RPS moyen et pic par Pod | À compléter |
| Replicas initiaux / maximaux observés | À compléter |
| Délai de scale-up / Ready / scale-down | À compléter |
| Erreurs HTTP et latence p95 | À compléter |
| Résultat et interprétation | À compléter |

### Nettoyage entre scénarios

Supprimer le HPA actif **avant** de redimensionner manuellement le Deployment :

```bash
kubectl get hpa -n hpa-metrics-poc
# Puis supprimer explicitement le HPA utilisé dans le scénario.
kubectl scale deployment/hpa-metrics-poc-app --replicas=1 -n hpa-metrics-poc
```

Ne supprimer ni Prometheus, ni Prometheus Adapter entre les démonstrations : ils constituent le socle partagé.

## Références

- [Kubernetes — Horizontal Pod Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)
- [Prometheus Adapter — Configuration](https://github.com/kubernetes-sigs/prometheus-adapter/blob/master/docs/config.md)
- [Grafana k6 — Scénarios](https://grafana.com/docs/k6/latest/using-k6/scenarios/)
- [Grafana k6 — Constant arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/)
