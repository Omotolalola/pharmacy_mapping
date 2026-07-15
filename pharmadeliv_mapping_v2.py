"""
Pharmadeliv — Mapping Écosystème Territorial v2
------------------------------------------------
Conforme au document de cadrage v1 :
- 8 catégories d'acteurs dont CPTS (base HubSpot)
- Rayons différenciés par type d'acteur
- Score de priorité combiné (type + distance)
- Indicateurs de succès (densité, couverture, activation, impact)

Usage :
    pip install pandas requests folium openpyxl python-dotenv
    (clé API à définir dans un fichier .env : GOOGLE_PLACES_API_KEY=...)
    python pharmadeliv_mapping_v2.py
"""

import math
import os
import time
import json
import pandas as pd
import requests
import folium
from folium.plugins import MarkerCluster
from datetime import datetime
from dotenv import load_dotenv

# Charge les variables définies dans le fichier .env (à faire AVANT
# tout appel à os.getenv() qui en dépend, ex: GOOGLE_PLACES_API_KEY)
load_dotenv()

# ─────────────────────────────────────────────
# CONFIG GÉNÉRALE
# ─────────────────────────────────────────────
CSV_PHARMACIES = os.getenv("PHARMADELIV_PHARMACIES_CSV", "pharmadeliv_pharmacies_clean.csv")
CSV_CPTS       = os.getenv("PHARMADELIV_CPTS_CSV", "cpts_hubspot.csv")
OUTPUT_MAP     = os.getenv("PHARMADELIV_OUTPUT_MAP", "mapping_ecosysteme.html")
OUTPUT_CSV     = os.getenv("PHARMADELIV_OUTPUT_CSV", "acteurs_identifies.csv")
OUTPUT_KPI     = os.getenv("PHARMADELIV_OUTPUT_KPI", "kpi_ecosysteme.json")

# ── Enrichissement contact (téléphone / site web / email)
# SIRENE/RNA ne fournissent JAMAIS ces informations (registres légaux Insee,
# pas des annuaires). La source complémentaire utilisée est Google Places.
GOOGLE_PLACES_API_KEY    = os.getenv("GOOGLE_PLACES_API_KEY")
if not GOOGLE_PLACES_API_KEY:
    raise RuntimeError(
        "Variable d'environnement GOOGLE_PLACES_API_KEY manquante. "
        "Définis-la avant de lancer le script (ex: export GOOGLE_PLACES_API_KEY=... ou fichier .env)."
    )

# ── Rayons par catégorie (conforme cadrage §4)
RAYONS_KM = {
    "cabinet":  2.5,
    "idel":     2.5,
    "ehpad":    5.0,
    "ssiad":    5.0,
    "asso":     5.0,
    "ccas":    10.0,   # couvre un territoire communal
    "cpts":    15.0,   # couvre un bassin de vie entier
}

# ── Codes NAF par catégorie SIRENE
# NB : "ccas" n'est PAS filtré ici. Le NAF 84.11Z correspond à
# "Administration publique générale" — bien trop large : il remonte aussi
# les ministères, préfectures, DGFIP, douanes, régions, autorités
# indépendantes... qui partagent ce même code NAF que les CCAS.
# Les CCAS sont identifiés séparément via leur code de nature juridique
# INSEE, spécifique et sans ambiguïté (cf. NATURE_JURIDIQUE_CODES ci-dessous).
NAF_CODES = {
    "cabinet": ["86.21Z", "86.22A", "86.22B"],
    "idel":    ["86.90A"],
    "ehpad":   ["87.10A", "87.10B", "87.10C"],
    "ssiad":   ["88.10A", "88.10B"],
}

# ── Codes de nature juridique INSEE par catégorie
# 7361 = "Centre communal d'action sociale" (nomenclature des Catégories
# Juridiques INSEE, niveau III). Contrairement au NAF 84.11Z, ce code
# identifie spécifiquement les CCAS et exclut par construction tout le
# reste de l'administration publique.
# Réf : https://xml.insee.fr/schema/cj-enum.html
NATURE_JURIDIQUE_CODES = {
    "ccas": ["7361"],
}

# ── Mots-clés d'exclusion par catégorie (filtre de sécurité post-scan)
# Le NAF 88.10A ("Aide à domicile") est auto-déclaré à la création de
# l'entreprise et regroupe aussi bien des SSIAD/SAAD (aide à la personne)
# que des sociétés de nettoyage/ménage pur, qui choisissent parfois ce code
# faute de mieux. On les retire par mot-clé sur le nom, à défaut d'un NAF
# plus précis pour distinguer les deux.
EXCLUSION_MOTS_CLES = {
    "ssiad": [
        "nettoyage", "clean", "menage", "ménage", "pressing",
        "jardinage", "jardin services", "espaces verts",
    ],
}

# ── Score de priorité de base par catégorie (cadrage §3 — levier de croissance)
PRIORITE_BASE = {
    "ehpad":   5,   # clientèle captive et régulière
    "cpts":    5,   # référencement territorial
    "cabinet": 4,   # génèrent le flux d'ordonnances
    "idel":    4,   # relais quotidien
    "ssiad":   3,   # contact direct patients fragiles
    "asso":    3,   # prescription sociale
    "ccas":    2,   # oriente publics isolés
}

COULEURS = {
    "cabinet": "#378ADD",
    "idel":    "#7F77DD",
    "ehpad":   "#1D9E75",
    "ssiad":   "#BA7517",
    "ccas":    "#888780",
    "asso":    "#D4537E",
    "cpts":    "#D85A30",
}

LABELS = {
    "cabinet": "Cabinet médical",
    "idel":    "IDEL",
    "ehpad":   "EHPAD / Résidence",
    "ssiad":   "Aide à domicile (SSIAD/SAAD)",
    "ccas":    "CCAS",
    "asso":    "Association seniors / aidants",
    "cpts":    "CPTS",
}

ICONES = {
    "cabinet": "Cabinet",
    "idel":    "IDEL",
    "ehpad":   "EHPAD",
    "ssiad":   "SSIAD",
    "ccas":    "CCAS",
    "asso":    "Association",
    "cpts":    "CPTS",
}

# ─────────────────────────────────────────────
# 1. CHARGEMENT & SÉLECTION DE LA PHARMACIE
# ─────────────────────────────────────────────
def charger_pharmacies():
    if not os.path.exists(CSV_PHARMACIES):
        raise FileNotFoundError(
            f"Fichier de pharmacies introuvable : {CSV_PHARMACIES}. "
            "Placez-le hors du dépôt ou définissez la variable d’environnement PHARMADELIV_PHARMACIES_CSV."
        )
    df = pd.read_csv(CSV_PHARMACIES)
    df = df.dropna(subset=["latitude", "longitude"])
    return df

def choisir_pharmacie(df):
    print("\n╔══════════════════════════════════════════════╗")
    print("║   PHARMADELIV — Mapping Écosystème v2       ║")
    print("╚══════════════════════════════════════════════╝\n")
    print("Rechercher une pharmacie (nom ou ville) :")
    query = input("  → ").strip().lower()

    resultats = df[
        df["nom"].str.lower().str.contains(query, na=False) |
        df["ville"].str.lower().str.contains(query, na=False)
    ].head(10)

    if resultats.empty:
        print("❌ Aucun résultat. Relance le script.")
        exit()

    print(f"\n{len(resultats)} résultat(s) :\n")
    for i, (_, row) in enumerate(resultats.iterrows()):
        statut  = "✅ Partenaire" if row.get("accepte_commandes") else "⬜ Prospect"
        adresse = row["adresse_complete"] if pd.notna(row.get("adresse_complete")) else "Adresse non renseignée"
        dept    = row["departement"] if pd.notna(row.get("departement")) else "N/A"
        print(f"  [{i}] {row['nom']} — {adresse} ({dept}) {statut}")

    while True:
        saisie = input("\nNuméro de la pharmacie : ").strip()
        if saisie.isdigit() and 0 <= int(saisie) < len(resultats):
            choix = int(saisie)
            break
        print(f"❌ Entre un numéro entre 0 et {len(resultats) - 1}.")

    pharmacie = resultats.iloc[choix]
    print(f"\n✓ Sélectionnée : {pharmacie['nom']} ({pharmacie['latitude']}, {pharmacie['longitude']})\n")
    return pharmacie

# ─────────────────────────────────────────────
# 2. CALCUL DE DISTANCE
# ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 3)


# ─────────────────────────────────────────────
# 3. SCORE DE PRIORITÉ
# Combine type d'acteur + distance (cadrage §4 — étape 5)
# Score 1–10 : plus élevé = à activer en premier
# ─────────────────────────────────────────────
def calculer_score(categorie, distance_km, rayon_max):
    base  = PRIORITE_BASE.get(categorie, 1)
    # Score distance : 5 si très proche, décroît linéairement jusqu'à 0 au bord du rayon
    dist_score = max(0, 5 * (1 - distance_km / rayon_max))
    return round(base + dist_score, 1)


def extraire_siren(siret):
    if not siret:
        return ""
    s = str(siret).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:9] if len(digits) >= 9 else ""

_debug_dump_fait = set()  # évite de spammer les logs : 1 dump JSON brut par NAF/mot-clé

def extraire_siret(r, siege):
    """Essaie plusieurs emplacements possibles pour le SIRET dans la réponse
    de recherche-entreprises.api.gouv.fr, car son schéma a pu évoluer."""
    candidats = [
        siege.get("siret"),
        r.get("siret"),
        r.get("siege_siret"),
    ]
    matching = r.get("matching_etablissements") or []
    if matching and isinstance(matching, list):
        candidats.append(matching[0].get("siret"))
    for c in candidats:
        if c:
            return str(c)
    return ""

def _debug_dump_resultat(tag, r):
    """En mode debug (PHARMADELIV_DEBUG=1), journalise une fois par
    catégorie/mot-clé la structure JSON brute du premier résultat reçu,
    pour diagnostiquer précisément quels champs l'API renvoie vraiment."""
    debug = os.getenv("PHARMADELIV_DEBUG", "") in ("1", "true", "True")
    if not debug or tag in _debug_dump_fait:
        return
    _debug_dump_fait.add(tag)
    _log(f"[DEBUG {tag}] clés de premier niveau : {sorted(r.keys())}")
    siege = r.get("siege", {})
    if isinstance(siege, dict):
        _log(f"[DEBUG {tag}] clés de 'siege' : {sorted(siege.keys())}")
    _log(f"[DEBUG {tag}] extrait brut : {json.dumps(r, ensure_ascii=False)[:500]}")

# ─────────────────────────────────────────────
# 3bis. JOURNAL DES ERREURS DE SCAN
# Alimenté par les fonctions de scan ci-dessous, remis à zéro au début
# de chaque scanner_ecosysteme(). Permet à l'interface Streamlit d'afficher
# les erreurs API au lieu qu'elles ne restent invisibles dans la console.
# ─────────────────────────────────────────────
_SCAN_LOGS = []

def _log(message):
    _SCAN_LOGS.append(message)
    print(f"    {message}")

def dernier_scan_logs():
    """Retourne les messages (avertissements/erreurs) du dernier scan."""
    return list(_SCAN_LOGS)

# ─────────────────────────────────────────────
# 4. SCAN SIRENE
# ─────────────────────────────────────────────
def _scanner_sirene_generique(lat, lon, params_filtre, departement, rayon_km, tag, naf_valeur):
    """Coeur commun des scans SIRENE. `params_filtre` porte le(s) paramètre(s)
    de filtrage envoyés tels quels à l'API (ex: {"activite_principale": "84.11Z"}
    ou {"nature_juridique": "7361"}). `tag` sert uniquement aux logs/debug.
    `naf_valeur` est la valeur stockée dans le champ "naf" de l'acteur (utile
    pour les filtres qui ne portent pas sur activite_principale)."""
    url         = "https://recherche-entreprises.api.gouv.fr/search"
    acteurs     = []
    page        = 1
    non_diffusibles = 0

    while True:
        params = {
            **params_filtre,
            "departement": str(departement).zfill(2),
            "per_page": 25,
            "page": page,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)

            # Rate-limiting (429) : l'API gouv limite le nombre de requêtes
            # par minute. On patiente puis on retente 2 fois avant d'abandonner
            # cette catégorie, plutôt que de silencieusement retourner 0 résultat.
            retries = 0
            while resp.status_code == 429 and retries < 3:
                wait = 2 * (retries + 1)
                _log(f"HTTP 429 (rate-limit) sur {tag}, nouvelle tentative dans {wait}s...")
                time.sleep(wait)
                resp = requests.get(url, params=params, timeout=10)
                retries += 1

            if resp.status_code != 200:
                _log(f"Erreur SIRENE ({tag}) : HTTP {resp.status_code} — {resp.text[:150]}")
                break
            data    = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for r in results:
                siege = r.get("siege", {})
                lat2  = siege.get("latitude")
                lon2  = siege.get("longitude")
                if lat2 is None or lon2 is None:
                    continue
                # Établissements non-diffusibles (RGPD) : lat/lon renvoient
                # parfois la chaîne '[NON-DIFFUSIBLE]' au lieu d'un nombre.
                # On les ignore individuellement sans interrompre le scan.
                try:
                    lat2 = float(lat2)
                    lon2 = float(lon2)
                except (TypeError, ValueError):
                    non_diffusibles += 1
                    continue
                dist = haversine(lat, lon, lat2, lon2)
                if dist <= rayon_km:
                    _debug_dump_resultat(f"SIRENE/{tag}", r)
                    siret = extraire_siret(r, siege)
                    telephone = siege.get("telephone", "")
                    email = siege.get("email", "")
                    siren = r.get("siren") or extraire_siren(siret)
                    acteurs.append({
                        "nom":         r.get("nom_complet", ""),
                        "adresse":     siege.get("adresse", ""),
                        "latitude":    lat2,
                        "longitude":   lon2,
                        "distance_km": dist,
                        "siret":       siret,
                        "siren":       siren,
                        "naf":         naf_valeur,
                        "contact":     "",
                        "telephone":   telephone,
                        "telephone_source": "SIRENE" if telephone else "",
                        "email":       email,
                        "email_source": "SIRENE" if email else "",
                        "source":      "SIRENE",
                    })

            if page >= data.get("total_pages", 1):
                break
            page += 1
            time.sleep(0.3)

        except Exception as e:
            _log(f"Erreur SIRENE ({tag}) : {e}")
            break

    if non_diffusibles:
        print(f"    {non_diffusibles} etablissement(s) non-diffusible(s) (RGPD) ignores pour {tag}")

    return acteurs


def scanner_sirene(lat, lon, naf_code, departement, rayon_km):
    """Scan filtré par code NAF (activite_principale)."""
    return _scanner_sirene_generique(
        lat, lon,
        params_filtre={"activite_principale": naf_code},
        departement=departement, rayon_km=rayon_km,
        tag=naf_code, naf_valeur=naf_code,
    )


def scanner_sirene_nature_juridique(lat, lon, nature_juridique_code, departement, rayon_km, naf_valeur):
    """Scan filtré par code de nature juridique INSEE (ex: 7361 = CCAS),
    plus précis qu'un NAF pour les catégories d'administration publique."""
    return _scanner_sirene_generique(
        lat, lon,
        params_filtre={"nature_juridique": nature_juridique_code},
        departement=departement, rayon_km=rayon_km,
        tag=f"nature_juridique={nature_juridique_code}", naf_valeur=naf_valeur,
    )



# ─────────────────────────────────────────────
# 5. SCAN ASSOCIATIONS (RNA)
# NB : l'ancien endpoint api.asso.api.gouv.fr n'existe plus (DNS mort).
# On réutilise l'API Recherche d'Entreprises (déjà utilisée pour SIRENE),
# qui indexe aussi les associations via le filtre est_association=true
# et renvoie directement des coordonnées géocodées.
# ─────────────────────────────────────────────
def scanner_rna(lat, lon, departement, rayon_km):
    url       = "https://recherche-entreprises.api.gouv.fr/search"
    mots_cles = ["seniors", "alzheimer", "aidants", "personnes agees", "admr"]
    acteurs   = []

    for mot in mots_cles:
        try:
            params = {
                "q": mot,
                "departement": str(departement).zfill(2),
                "est_association": "true",
                "per_page": 25,
                "page": 1,
            }
            resp = requests.get(url, params=params, timeout=10)

            retries = 0
            while resp.status_code == 429 and retries < 3:
                wait = 2 * (retries + 1)
                _log(f"HTTP 429 (rate-limit) sur RNA/{mot}, nouvelle tentative dans {wait}s...")
                time.sleep(wait)
                resp = requests.get(url, params=params, timeout=10)
                retries += 1

            if resp.status_code != 200:
                _log(f"Erreur RNA ({mot}) : HTTP {resp.status_code} — {resp.text[:150]}")
                continue
            for r in resp.json().get("results", []):
                siege = r.get("siege", {})
                lat2  = siege.get("latitude")
                lon2  = siege.get("longitude")
                if lat2 is None or lon2 is None:
                    continue
                try:
                    lat2 = float(lat2)
                    lon2 = float(lon2)
                except (TypeError, ValueError):
                    continue  # établissement non-diffusible
                dist = haversine(lat, lon, lat2, lon2)
                if dist <= rayon_km:
                    _debug_dump_resultat(f"RNA/{mot}", r)
                    siret = extraire_siret(r, siege)
                    telephone = siege.get("telephone", "")
                    email = siege.get("email", "")
                    siren = r.get("siren") or extraire_siren(siret)
                    acteurs.append({
                        "nom":         r.get("nom_complet", ""),
                        "adresse":     siege.get("adresse", ""),
                        "latitude":    lat2,
                        "longitude":   lon2,
                        "distance_km": dist,
                        "siret":       siret,
                        "siren":       siren,
                        "naf":         "asso",
                        "telephone":   telephone,
                        "telephone_source": "RNA" if telephone else "",
                        "email":       email,
                        "email_source": "RNA" if email else "",
                        "source":      "RNA (via Recherche d'Entreprises)",
                    })
            time.sleep(0.3)
        except Exception as e:
            _log(f"Erreur RNA ({mot}) : {e}")

    return acteurs

# ─────────────────────────────────────────────
# 6. CHARGEMENT CPTS (base HubSpot interne)
# Le fichier cpts_hubspot.csv doit contenir :
# nom, adresse, latitude, longitude, contact, telephone, email, territoire
# ─────────────────────────────────────────────
def charger_cpts(lat, lon, rayon_km):
    acteurs = []
    try:
        df = pd.read_csv(CSV_CPTS)
        df = df.dropna(subset=["latitude", "longitude"])
        for _, row in df.iterrows():
            dist = haversine(lat, lon, float(row["latitude"]), float(row["longitude"]))
            if dist <= rayon_km:
                siret = row.get("siret", "")
                telephone = row.get("telephone", "")
                email = row.get("email", "")
                acteurs.append({
                    "nom":         row.get("nom", ""),
                    "adresse":     row.get("adresse", ""),
                    "latitude":    float(row["latitude"]),
                    "longitude":   float(row["longitude"]),
                    "distance_km": dist,
                    "siret":       siret,
                    "siren":       extraire_siren(siret),
                    "naf":         "cpts",
                    "contact":     telephone or email or row.get("contact", ""),
                    "telephone":   telephone,
                    "telephone_source": "HubSpot CRM" if telephone else "",
                    "email":       email,
                    "email_source": "HubSpot CRM" if email else "",
                    "source":      "HubSpot CRM",
                })
        print(f"    {len(acteurs)} CPTS trouvée(s) dans le rayon")
    except FileNotFoundError:
        print(f"    Fichier {CSV_CPTS} introuvable — CPTS ignorées")
        print(f"      → Exporte ta base HubSpot en CSV avec : nom, adresse, latitude, longitude, contact")
    return acteurs

# ─────────────────────────────────────────────
# 6quater. ENRICHISSEMENT CONTACT — Google Places (optionnel, payant)
# Traite tous les acteurs sans téléphone connus. No-op silencieux sans clé API.
# ─────────────────────────────────────────────
def enrichir_contacts_google_places(acteurs, api_key=None):
    api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY", "") or GOOGLE_PLACES_API_KEY

    if not api_key:
        _log("Enrichissement Google Places ignoré : aucune clé API fournie.")
        return acteurs

    restants = [a for a in acteurs if not a.get("telephone")]
    a_enrichir = sorted(restants, key=lambda a: -a.get("score", 0))
    cibles     = {id(a) for a in a_enrichir}

    if not a_enrichir:
        _log("Enrichissement Google Places : tous les acteurs prioritaires ont déjà un téléphone.")
        return acteurs

    search_url  = "https://places.googleapis.com/v1/places:searchText"
    trouves, echecs = 0, 0

    for a in acteurs:
        if id(a) not in cibles:
            continue
        requete = f"{a['nom']} {a.get('adresse','')}".strip()
        if not requete:
            continue
        try:
            resp = requests.post(
                search_url,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": (
                        "places.nationalPhoneNumber,"
                        "places.internationalPhoneNumber,"
                        "places.websiteUri"
                    ),
                },
                json={
                    "textQuery": requete,
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": a["latitude"], "longitude": a["longitude"]},
                            "radius": 500.0,
                        }
                    },
                    "maxResultCount": 1,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                _log(f"Google Places : HTTP {resp.status_code} pour « {a['nom']} » — {resp.text[:150]}")
                echecs += 1
                continue

            places = resp.json().get("places", [])
            if not places:
                continue
            place = places[0]
            tel  = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
            site = place.get("websiteUri", "")
            if tel:
                a["telephone"] = tel
            if site and not a.get("site_web"):
                a["site_web"] = site
            if tel or site:
                trouves += 1

            time.sleep(0.1)

        except Exception as e:
            _log(f"Erreur Google Places pour « {a['nom']} » : {e}")
            echecs += 1

    _log(f"Google Places : {trouves}/{len(a_enrichir)} acteur(s) enrichi(s), {echecs} échec(s).")
    return acteurs

# ─────────────────────────────────────────────
# 7. SCAN COMPLET ÉCOSYSTÈME
# ─────────────────────────────────────────────
def scanner_ecosysteme(pharmacie):
    if not pharmacie.get("accepte_commandes"):
        raise ValueError(
            "Pipeline réservé aux pharmacies partenaires : 'accepte_commandes' doit être True."
        )

    _SCAN_LOGS.clear()

    lat  = pharmacie["latitude"]
    lon  = pharmacie["longitude"]
    dept = str(pharmacie["num_departement"]).zfill(2)

    tous = []
    print("Scan de l'écosystème en cours...\n")

    # SIRENE — filtre par NAF (cabinet, idel, ehpad, ssiad)
    for cat, codes in NAF_CODES.items():
        rayon = RAYONS_KM[cat]
        print(f"  {LABELS[cat]} (rayon {rayon} km)...")
        mots_exclus = [m.lower() for m in EXCLUSION_MOTS_CLES.get(cat, [])]
        for naf in codes:
            acteurs = scanner_sirene(lat, lon, naf, dept, rayon)
            if mots_exclus:
                avant = len(acteurs)
                acteurs = [
                    a for a in acteurs
                    if not any(m in a["nom"].lower() for m in mots_exclus)
                ]
                exclus = avant - len(acteurs)
                if exclus:
                    _log(f"{exclus} acteur(s) exclu(s) de {LABELS[cat]} ({naf}) par mot-clé (nettoyage/ménage/...).")
            for a in acteurs:
                a["categorie"] = cat
                a["label"]     = LABELS[cat]
                a["score"]     = calculer_score(cat, a["distance_km"], rayon)
            tous.extend(acteurs)

    # SIRENE — filtre par nature juridique INSEE (ccas)
    for cat, codes in NATURE_JURIDIQUE_CODES.items():
        rayon = RAYONS_KM[cat]
        print(f"  {LABELS[cat]} (rayon {rayon} km)...")
        for code_nj in codes:
            acteurs = scanner_sirene_nature_juridique(lat, lon, code_nj, dept, rayon, naf_valeur=cat)
            for a in acteurs:
                a["categorie"] = cat
                a["label"]     = LABELS[cat]
                a["score"]     = calculer_score(cat, a["distance_km"], rayon)
            tous.extend(acteurs)

    # RNA
    rayon_asso = RAYONS_KM["asso"]
    print(f"  {LABELS['asso']} (rayon {rayon_asso} km)...")
    assos = scanner_rna(lat, lon, dept, rayon_asso)
    for a in assos:
        a["categorie"] = "asso"
        a["label"]     = LABELS["asso"]
        a["score"]     = calculer_score("asso", a["distance_km"], rayon_asso)
    tous.extend(assos)

    # CPTS (HubSpot)
    rayon_cpts = RAYONS_KM["cpts"]
    print(f"  {LABELS['cpts']} (rayon {rayon_cpts} km — base HubSpot)...")
    cpts = charger_cpts(lat, lon, rayon_cpts)
    for a in cpts:
        a["categorie"] = "cpts"
        a["label"]     = LABELS["cpts"]
        a["score"]     = calculer_score("cpts", a["distance_km"], rayon_cpts)
    tous.extend(cpts)

    # Dédoublonnage par siret ou nom+coords
    seen, uniques = set(), []
    for a in tous:
        key = a.get("siret") or f"{a['nom']}_{a['latitude']:.4f}_{a['longitude']:.4f}"
        if key not in seen:
            seen.add(key)
            uniques.append(a)

    # Tri par score décroissant
    uniques.sort(key=lambda x: -x["score"])

    # Enrichissement contact sur les acteurs prioritaires :
    # Google Places est utilisé seul pour l'enrichissement.
    print("  Enrichissement contact (Google Places)...")
    enrichir_contacts_google_places(uniques)

    print(f"\n{len(uniques)} acteurs uniques identifiés.")
    return uniques, list(_SCAN_LOGS)

# ─────────────────────────────────────────────
# 8. INDICATEURS DE SUCCÈS (cadrage §6)
# ─────────────────────────────────────────────
def calculer_kpi(acteurs, pharmacie):
    cats_presentes  = set(a["categorie"] for a in acteurs)
    toutes_cats     = set(LABELS.keys())
    taux_couverture = round(len(cats_presentes) / len(toutes_cats) * 100, 1)

    cats_manquantes = toutes_cats - cats_presentes

    kpi = {
        "pharmacie":             pharmacie["nom"],
        "adresse":               pharmacie.get("adresse_complete", ""),
        "date_scan":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "statut_pharmacie":      "Partenaire" if pharmacie.get("accepte_commandes") else "Prospect",
        # Densité écosystème
        "nb_acteurs_total":      len(acteurs),
        "nb_categories":         len(cats_presentes),
        "densite_ecosysteme":    f"{len(acteurs)} acteurs / {len(cats_presentes)} catégories",
        # Couverture
        "couverture_pct":        taux_couverture,
        "categories_presentes":  sorted(list(cats_presentes)),
        "categories_manquantes": sorted(list(cats_manquantes)),
        # Détail par catégorie
        "detail_categories": {
            cat: {
                "nb":            sum(1 for a in acteurs if a["categorie"] == cat),
                "rayon_km":      RAYONS_KM.get(cat, 2.5),
                "score_max":     max((a["score"] for a in acteurs if a["categorie"] == cat), default=0),
                "plus_proche_km": min((a["distance_km"] for a in acteurs if a["categorie"] == cat), default=None),
            }
            for cat in toutes_cats
        },
        # Top 5 acteurs prioritaires
        "top5_prioritaires": [
            {
                "nom":       a["nom"],
                "categorie": LABELS[a["categorie"]],
                "distance":  a["distance_km"],
                "contact":   a.get("contact", ""),
            }
            for a in acteurs[:5]
        ],
        # Activation & impact — à renseigner manuellement après démarchage
        "nb_partenaires_contactes": 0,
        "nb_mises_en_relation":     0,
        "patientele_livree_initiale": None,
        "note": "Compléter après activation commerciale",
    }

    with open(OUTPUT_KPI, "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)

    return kpi

# ─────────────────────────────────────────────
# 9. CARTE FOLIUM
# ─────────────────────────────────────────────
def generer_carte(pharmacie, acteurs, kpi):
    lat = pharmacie["latitude"]
    lon = pharmacie["longitude"]

    carte = folium.Map(location=[lat, lon], zoom_start=14, tiles="CartoDB positron")

    # Cercles de rayon par catégorie
    rayons_affiches = set()
    for cat, r in RAYONS_KM.items():
        if r not in rayons_affiches:
            folium.Circle(
                location=[lat, lon],
                radius=r * 1000,
                color=COULEURS.get(cat, "#888"),
                fill=False,
                weight=0.8,
                dash_array="4 4",
                tooltip=f"Rayon {cat} : {r} km",
            ).add_to(carte)
            rayons_affiches.add(r)

    # Marqueur pharmacie centrale
    folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(html=f"""
            <div style="background:#185FA5;color:white;font-size:11px;
            font-weight:600;padding:5px 10px;border-radius:20px;
            white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.3)">
            💊 {pharmacie['nom']}</div>
        """),
        tooltip=pharmacie["nom"],
        popup=folium.Popup(
            f"<b>{pharmacie['nom']}</b><br>{pharmacie.get('adresse_complete','')}<br>"
            f"Statut : {kpi['statut_pharmacie']}<br>"
            f"Densité : {kpi['nb_acteurs_total']} acteurs identifiés<br>"
            f"Couverture : {kpi['couverture_pct']}%",
            max_width=280
        ),
    ).add_to(carte)

    # Clusters par catégorie
    for cat in LABELS:
        cluster = MarkerCluster(name=f"{ICONES.get(cat,'')} {LABELS[cat]}").add_to(carte)
        for a in acteurs:
            if a["categorie"] != cat:
                continue
            color = COULEURS[cat]
            contact_lines = []
            if a.get('telephone'):
                contact_lines.append(f"Tel : {a['telephone']}")
            if a.get('email'):
                contact_lines.append(f"Email : {a['email']}")
            if a.get('siren'):
                contact_lines.append(f"SIREN : {a['siren']}")
            contact_html = "<br>".join(contact_lines)
            if contact_html:
                contact_html = f"{contact_html}<br>"
            popup_html = f"""
                <b>{a['nom']}</b><br>
                {a.get('adresse','')}<br>
                <span style="color:{color}">■ {LABELS[cat]}</span><br>
                Distance : <b>{a['distance_km']} km</b><br>
                Source : {a.get('source','')}<br>
                {contact_html}
            """
            folium.CircleMarker(
                location=[a["latitude"], a["longitude"]],
                radius=7,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.75,
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"{ICONES.get(cat,'')} {a['nom']} — {a['distance_km']} km",
            ).add_to(cluster)

    legend_items = []
    for cat in LABELS:
        color = COULEURS.get(cat, "#888")
        legend_items.append(
            f"<div style='display:flex;align-items:center;margin:3px 0;'><span style='display:inline-block;width:12px;height:12px;background:{color};border-radius:2px;margin-right:6px;'></span>{LABELS[cat]}</div>"
        )

    legend_html = f"""
    <div style="position: fixed; bottom: 25px; left: 25px; z-index: 1000;
        background: white; border: 1px solid #cccccc; border-radius: 8px;
        padding: 10px 12px; font-size: 13px; line-height: 1.4;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25); max-width: 260px;">
        <div style="font-weight: 700; margin-bottom: 6px;">Légende</div>
        <div style="margin-bottom: 6px;">Chaque couleur correspond à une catégorie d'acteur.</div>
        {''.join(legend_items)}
    </div>
    """
    carte.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=False).add_to(carte)
    carte.save(OUTPUT_MAP)
    print(f"\n✓ Carte : {OUTPUT_MAP}")

# ─────────────────────────────────────────────
# 10. EXPORT CSV
# ─────────────────────────────────────────────
def exporter_csv(acteurs, pharmacie, kpi):
    rows = []
    for a in acteurs:
        rows.append({
            "pharmacie_reference":   pharmacie["nom"],
            "pharmacie_adresse":     pharmacie.get("adresse_complete", ""),
            "pharmacie_statut":      kpi["statut_pharmacie"],
            "acteur_nom":            a["nom"],
            "acteur_categorie":      LABELS[a["categorie"]],
            "acteur_adresse":        a.get("adresse", ""),
            "acteur_siret":          a.get("siret", ""),
            "acteur_siren":          a.get("siren", ""),
            "acteur_telephone":      a.get("telephone", ""),
            "acteur_email":          a.get("email", ""),
            "distance_km":           a["distance_km"],
            "source":                a.get("source", ""),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"✓ CSV acteurs : {OUTPUT_CSV} ({len(df)} lignes)")

# ─────────────────────────────────────────────
# RÉSUMÉ CONSOLE
# ─────────────────────────────────────────────
def afficher_resume(acteurs, kpi):
    print("\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Écosystème : {kpi['pharmacie'][:38]:38s}  ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Densité    : {kpi['densite_ecosysteme']:38s}  ║")
    print(f"║  Couverture : {str(kpi['couverture_pct'])+'%':38s}  ║")
    if kpi["categories_manquantes"]:
        manq = ", ".join(LABELS.get(c, c) for c in kpi["categories_manquantes"])
        print(f"║  Manquants  : {manq[:38]:38s}  ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  TOP 5 ACTEURS PRIORITAIRES                          ║")
    for i, a in enumerate(kpi["top5_prioritaires"], 1):
        ligne = f"{i}. {a['nom'][:30]} ({a['distance']:.2f}km)"
        print(f"║  {ligne:52s}  ║")
    print("╚══════════════════════════════════════════════════════╝\n")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    df_pharmacies = charger_pharmacies()
    pharmacie     = choisir_pharmacie(df_pharmacies)
    acteurs, logs = scanner_ecosysteme(pharmacie)
    if logs:
        print("\n⚠ Avertissements pendant le scan :")
        for l in logs:
            print(f"  - {l}")
    kpi           = calculer_kpi(acteurs, pharmacie)
    afficher_resume(acteurs, kpi)
    generer_carte(pharmacie, acteurs, kpi)
    exporter_csv(acteurs, pharmacie, kpi)
    print(f"✅ KPI sauvegardés : {OUTPUT_KPI}")
    print("✅ Mapping terminé !\n")