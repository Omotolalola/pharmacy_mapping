# Pharmadeliv Mapping interactif

## Description

Cette application Streamlit permet de rechercher une pharmacie, d’analyser son environnement territorial et de générer une carte interactive des acteurs proches.

Elle peut identifier des acteurs locaux tels que les CPTS, cabinets médicaux, IDEL, EHPAD, SSIAD, associations et CCAS, puis produire :
- une carte interactive HTML,
- un export CSV des acteurs identifiés,
- un export JSON des KPI.

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

## Fonctionnalités actuelles

- recherche et filtrage des pharmacies,
- filtre pour n’afficher que les pharmacies déjà associées à Pharmadeliv,
- génération d’une carte interactive avec légende,
- export des résultats en CSV/JSON,
- affichage des résultats sans score visible dans l’interface.
