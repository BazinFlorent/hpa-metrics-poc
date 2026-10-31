# ADR-001 — Choix des métriques de pilotage de l'autoscaling

**Statut :** Proposition — à confirmer après les expérimentations S3 et S5  
**Contexte :** POC `hpa-metrics-poc` — Kubernetes HPA, Prometheus et Prometheus Adapter

## 1. Trois niveaux de signaux

| Niveau | Pictogramme | Exemples de métriques | Ce que la métrique exprime | Apport potentiel à l'autoscaling | Point de vigilance |
|---|:---:|---|---|---|---|
| **Ressource** | 🖥️ | CPU, mémoire | Consommation de capacité technique | Détecter une pression sur les ressources des Pods | Une hausse de la demande ne se traduit pas toujours par une hausse CPU/RAM ; la mémoire n'est pas toujours corrélée à une charge réversible |
| **Activité applicative** | 📈 | Requêtes/s (RPS), requêtes simultanées | Volume de demandes et travail en cours | Adapter la capacité à l'activité, éventuellement avant une saturation CPU | Un RPS élevé ne signifie pas nécessairement une saturation ; le coût de traitement varie selon les requêtes |
| **Pression métier** | 💼 | Transactions en attente, âge du plus ancien message, délai de traitement | Travail fonctionnel restant et qualité de service | Aligner la capacité sur un délai ou un objectif métier/SLO | Nécessite une métrique fiable et une relation démontrable entre replicas ajoutés et travail résorbé |

> **Principe :** le signal le plus pertinent est celui qui représente le mieux le facteur limitant du service et sur lequel l'ajout de replicas a réellement un effet.

## 2. Interprétation architecturale

- **CPU/RAM** indiquent *combien de ressources sont consommées* : c'est un signal technique de capacité.
- **RPS/concurrence** indiquent *combien d'activité arrive ou s'exécute* : c'est un signal de demande applicative, qui peut être plus précoce dans certains cas.
- **Backlog/délai métier** indiquent *combien de travail doit encore être réalisé, et sous quel engagement* : c'est un signal potentiellement plus proche de la valeur de service.

Il n'existe **pas de hiérarchie universelle** : une métrique applicative ou métier n'est pas intrinsèquement plus proactive qu'une métrique CPU. Sa pertinence dépend de la charge, des délais de collecte, du temps de démarrage des Pods et des véritables goulots d'étranglement.

## 3. Ne pas confondre nature du signal et API Kubernetes

Les trois niveaux précédents décrivent **ce que l'on mesure**. Ils sont distincts des catégories techniques par lesquelles le HPA obtient les valeurs :

| API Kubernetes | Association / usage HPA | Exemple dans le POC |
|---|---|---|
| `metrics.k8s.io` | Métriques de ressources CPU et mémoire (`Resource`) | Consommation CPU d'un Pod via Metrics Server |
| `custom.metrics.k8s.io` | Métrique associée à un objet Kubernetes (`Pods` ou `Object`) | `http_requests_per_second` par Pod via Prometheus Adapter |
| `external.metrics.k8s.io` | Métrique non nécessairement associée à un objet Kubernetes (`External`) | Taille globale d'une file simulée, à implémenter |

Une métrique d'activité ou métier peut être exposée comme **Custom** ou **External**, selon la manière dont elle est associée aux objets Kubernetes. « External » ne signifie pas forcément que sa source est située hors du cluster.

## 4. Hypothèses à éprouver dans le POC

| Expérience | Question évaluée | Critère d'observation |
|---|---|---|
| **S3 — HPA RPS vs HPA CPU** | Le RPS peut-il déclencher une adaptation de capacité alors que le CPU reste faible ? | Même charge, un seul HPA actif à la fois ; comparer RPS, CPU, replicas, latence et erreurs |
| **S5 — External Metrics** | Une mesure de travail en attente est-elle un meilleur signal pour un traitement asynchrone ? | Évolution de la file, délais de traitement et effet réel de l'ajout de replicas |

**Position provisoire :** sélectionner la métrique à partir du comportement du workload et de l'objectif de service, puis vérifier expérimentalement qu'elle prédit une demande de capacité utile. Un scaling ne corrige pas un goulot extérieur aux Pods (par exemple une gateway ou un quota APIM).

---

**Documents associés :** [Architecture](../03-architecture.md) · [Démonstration](../02-demonstration.md)
