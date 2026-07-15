# Pharmadeliv Mapping interactif

## Description

Cette application Streamlit permet de rechercher une pharmacie, d’analyser son environnement territorial et de générer une carte interactive des acteurs proches.

Elle peut identifier des acteurs locaux tels que les CPTS, cabinets médicaux, IDEL, EHPAD, SSIAD, associations et CCAS, puis produire :
- une carte interactive HTML,
- un export CSV des acteurs identifiés (fiche de contact pour le démarchage),
- un export JSON des KPI.

Pour chaque acteur identifié, l'application tente de récupérer automatiquement ses informations légales (SIRET/SIREN) et ses coordonnées de contact (téléphone, site web) — voir la section [Obtention des informations de contact](#obtention-des-informations-de-contact) ci-dessous pour le détail des sources utilisées.

## Fichiers principaux

- `streamlit_app.py` : interface Streamlit de recherche, filtrage et génération du mapping.
- `pharmadeliv_mapping_v2.py` : logique métier, appels de données, calculs de proximité et génération de la carte.
- `requirements.txt` : dépendances Python nécessaires au projet.
- `pharmadeliv_pharmacies_clean.csv` : fichier de données des pharmacies à charger (à garder privé si nécessaire).
- `.gitignore` : exclut les fichiers sensibles et les sorties générées du dépôt Git.

## Installation

Depuis la racine du projet :

```powershell
pip install -r requirements.txt
```

## Lancer l’application localement

```powershell
streamlit run streamlit_app.py
```


## Données privées et déploiement


- par défaut, l’application cherche `pharmadeliv_pharmacies_clean.csv` dans le dossier courant ;


Vous pouvez faire la même chose pour la base CPTS avec :

```powershell
$env:PHARMADELIV_CPTS_CSV = "C:\chemin\vers\cpts_hubspot.csv"
```

## Déploiement sur Streamlit Cloud

Pour un déploiement public, le code peut rester sur GitHub, mais les fichiers sensibles doivent être fournis via des variables d’environnement ou secrets de l’environnement de déploiement.

## Obtention des informations de contact

Chaque acteur passe par un pipeline en plusieurs étapes, résumé ci-dessous, puis détaillé plus bas.

| Donnée | Source | Fiabilité | Coût |
|---|---|---|---|
| Nom, adresse, SIRET, SIREN | API SIRENE / RNA (recherche-entreprises.api.gouv.fr) | Officielle, quasi-exhaustive | Gratuit |
| Téléphone, site web | Google Places | Élevée | Payant à l'usage |
| Email | — | Non automatisable de façon fiable | — |

### 1. Identité légale (SIRET / SIREN) — toujours actif

Pour chaque catégorie d'acteur (cabinet médical, IDEL, EHPAD, SSIAD, CCAS, associations), l'application interroge l'**API Recherche d'Entreprises** (`recherche-entreprises.api.gouv.fr`), qui agrège les données officielles Insee (SIRENE) et le Répertoire National des Associations (RNA). Cette API est publique, gratuite et ne nécessite aucune clé.

Elle fournit : nom, adresse, coordonnées GPS, code NAF, SIRET et SIREN. Elle **ne fournit jamais** de téléphone ni d'email : il s'agit d'un registre légal, pas d'un annuaire de contact.

⚠️ Certains établissements (professions libérales notamment) exercent leur droit d'opposition à la diffusion de leurs données et remontent en `[NON-DIFFUSIBLE]` — ils sont automatiquement ignorés lors du scan (comptabilisés dans les logs, mais absents des résultats).

### 2. Téléphone / site web — Google Places (payant à l'usage)

Une fois les acteurs identifiés et triés par score de priorité, l'application interroge la Google Places API pour rechercher les numéros de téléphone et les sites web des établissements.

- **Nécessite une clé API Google Places**, configurée via les secrets ou variables d'environnement.
- **Meilleure couverture** qu'une source communautaire, mais reste dépendante des données Google.
- Cette étape est la seule source d'enrichissement contact dans le projet.

### 3. Email — non automatisé

Aucune source publique fiable et gratuite ne fournit d'email d'entreprise à grande échelle. Le champ `email` peut être trouvé ponctuellement via certains résultats Google Places, mais il reste globalement à compléter manuellement pendant le démarchage — le champ `site_web` sert de point de départ pour trouver la page "Contact" du site.

**Activation :**

1. Créer un projet sur la [Google Cloud Console](https://console.cloud.google.com/), activer l'API **"Places API (New)"**, générer une clé API, et activer la facturation du projet (un crédit gratuit mensuel est généralement offert — vérifier le montant actuel sur la [page tarifaire officielle](https://mapsplatform.google.com/pricing/)).
2. Restreindre la clé à l'API Places uniquement (recommandé).
3. Configurer la clé **sans jamais la saisir dans l'interface** :
   - **Streamlit Cloud** : *Manage app* → *Settings* → *Secrets* :
     ```toml
     GOOGLE_PLACES_API_KEY = "AIzaSy...ta_clé"
     ```
   - **En local** : créer `.streamlit/secrets.toml` (déjà exclu du dépôt via `.gitignore`) avec le même contenu, ou définir la variable d'environnement `GOOGLE_PLACES_API_KEY`.
4. Aucun engagement : la facturation est à l'usage, désactivable à tout moment (Console → Billing → *Disable billing*), et des alertes de budget peuvent être configurées (Console → Billing → *Budgets & alerts*).

Sans clé configurée, cette étape est silencieusement ignorée (aucune erreur, juste une ligne de log informative).

### 4. Email — non automatisé

Aucune source publique fiable et gratuite ne fournit d'email d'entreprise à grande échelle. Le champ `email` peut être trouvé ponctuellement via certains résultats Google Places, mais il reste globalement à compléter manuellement pendant le démarchage — le champ `site_web` récupéré via Google Places sert de point de départ pour trouver la page "Contact" du site.

### Diagnostiquer les résultats d'un scan

Après chaque scan, un panneau **"⚠ avertissements pendant le scan"** liste, étape par étape, les erreurs API rencontrées (codes HTTP, messages exacts). En cas de résultat vide ou surprenant, c'est le premier endroit à consulter.

Un **mode debug** plus poussé est disponible en définissant `PHARMADELIV_DEBUG=1` (variable d'environnement ou `st.secrets`) : il journalise la structure JSON brute renvoyée par l'API SIRENE/RNA pour le premier résultat de chaque catégorie, utile si l'API change de schéma.

### Variables de configuration disponibles

| Variable | Rôle | Défaut |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | Active l'enrichissement Google Places | (vide = désactivé) |

## Fonctionnalités actuelles

- recherche et filtrage des pharmacies,
- filtre pour n’afficher que les pharmacies déjà associées à Pharmadeliv,
- identification des acteurs de l'écosystème (SIRET/SIREN via SIRENE/RNA),
- enrichissement automatique téléphone/site web via Google Places,
- génération d’une carte interactive avec légende,
- export des résultats en CSV/JSON (fiche de contact pour le démarchage),
- affichage des résultats avec score de priorité visible dans l’interface.
