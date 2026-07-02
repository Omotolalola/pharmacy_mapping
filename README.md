# Pharmadeliv Mapping interactif

## Description

Ce projet contient une application Streamlit pour générer un mapping territorial autour d'une pharmacie sélectionnée.

L'application effectue un scan de différents acteurs locaux (CPTS, cabinets médicaux, IDEL, EHPAD, SSIAD, associations, CCAS) à partir d'une pharmacie choisie et produit :
- une carte interactive (`mapping_ecosysteme.html`),
- un CSV des acteurs identifiés (`acteurs_identifies.csv`),
- des KPI stockés en JSON (`kpi_ecosysteme.json`).

## Fichiers principaux

- `streamlit_app.py` : interface Streamlit. Permet de rechercher une pharmacie, de la sélectionner, puis de lancer le scan et la génération de résultats.
- `pharmadeliv_mapping_v2.py` : logique métier et génération de carte.
- `pharmadeliv_pharmacies_clean.csv` : source des pharmacies à rechercher.
- `acteurs_identifies.csv` : fichier de sortie généré après scan.
- `kpi_ecosysteme.json` : KPI générés après scan.
- `mapping_ecosysteme.html` : carte Folium générée.

## Ce qui a été fait

- Correction de l'import Streamlit : `streamlit_app.py` importait `OUTPUT_j` alors que le module `pharmadeliv_mapping_v2.py` expose `OUTPUT_KPI`.
- Ajout d'une légende de couleurs sur la carte générée pour expliquer chaque catégorie d'acteur.
- Mise en place d'un filtre pour n'afficher que les pharmacies déjà associées à Pharmadeliv lors de la sélection.
- Explication du numéro affiché à côté de chaque pharmacie dans l'interface Streamlit : il s'agit de l'index de la ligne dans la liste de résultats filtrés, utilisé pour sélectionner une pharmacie.

## Comment lancer l'application

1. Ouvrez PowerShell dans le dossier du projet :

```powershell
cd C:\Users\Lenovo\Downloads\Mapping
```

2. Installez les dépendances si besoin :

```powershell
pip install streamlit pandas requests folium openpyxl
```

3. Lancez l'application Streamlit :

```powershell
streamlit run streamlit_app.py
```

4. Ouvrez l'URL indiquée dans le terminal (généralement `http://localhost:8501`).

## Déploiement gratuit

Pour partager l'application avec vos collaborateurs gratuitement, utilisez Streamlit Community Cloud :

1. Poussez ce projet dans un dépôt GitHub.
2. Connectez-vous sur https://share.streamlit.io/.
3. Créez une nouvelle app en pointant sur ce dépôt.
4. Sélectionnez `streamlit_app.py` comme fichier principal.

## Notes importantes

- `pharmadeliv_pharmacies_clean.csv` doit rester présent pour que l'application puisse charger la liste des pharmacies.
- Si vous souhaitez enrichir la base CPTS, ajoutez un fichier `cpts_hubspot.csv` avec les colonnes : `nom`, `adresse`, `latitude`, `longitude`, `contact`, `territoire`.
- Le fichier `mapping_ecosysteme.html` est régénéré à chaque scan réussi et inclut maintenant la légende des catégories de couleur.

## Structure du code

- `streamlit_app.py` :
  - charge les pharmacies,
  - recherche et filtre par nom/ville,
  - affiche une table de résultats,
  - sélectionne une pharmacie et génère le mapping,
  - propose le téléchargement des fichiers produits.

- `pharmadeliv_mapping_v2.py` :
  - charge les pharmacies et les CPTS,
  - effectue des recherches SIRENE et RNA,
  - calcule les distances et les scores de priorité,
  - génère une carte Folium avec des marqueurs et la légende,
  - exporte les résultats en CSV et JSON.
