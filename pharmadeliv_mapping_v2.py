"""
Pharmadeliv — Mapping Écosystème Territorial v2
------------------------------------------------
Conforme au document de cadrage v1 :
- 8 catégories d'acteurs dont CPTS (base HubSpot)
- Rayons différenciés par type d'acteur
- Score de priorité combiné (type + distance)
- Indicateurs de succès (densité, couverture, activation, impact)

Usage :
    pip install pandas requests folium openpyxl
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

# ─────────────────────────────────────────────
# CONFIG GÉNÉRALE
# ─────────────────────────────────────────────
CSV_PHARMACIES = os.getenv("PHARMADELIV_PHARMACIES_CSV", "pharmadeliv_pharmacies_clean.csv")
CSV_CPTS       = os.getenv("PHARMADELIV_CPTS_CSV", "cpts_hubspot.csv")
OUTPUT_MAP     = os.getenv("PHARMADELIV_OUTPUT_MAP", "mapping_ecosysteme.html")
OUTPUT_CSV     = os.getenv("PHARMADELIV_OUTPUT_CSV", "acteurs_identifies.csv")
OUTPUT_KPI     = os.getenv("PHARMADELIV_OUTPUT_KPI", "kpi_ecosysteme.json")

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
NAF_CODES = {
    "cabinet": ["86.21Z", "86.22A", "86.22B"],
    "idel":    ["86.90A"],
    "ehpad":   ["87.10A", "87.10B", "87.10C"],
    "ssiad":   ["88.10A", "88.10B"],
    "ccas":    ["84.11Z"],
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
    "cabinet": "🩺",
    "idel":    "💉",
    "ehpad":   "🏥",
    "ssiad":   "🤝",
    "ccas":    "🏛️",
    "asso":    "👥",
    "cpts":    "🔗",
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

# ─────────────────────────────────────────────
# 4. SCAN SIRENE
# ─────────────────────────────────────────────
def scanner_sirene(lat, lon, naf_code, departement, rayon_km):
    url         = "https://recherche-entreprises.api.gouv.fr/search"
    acteurs     = []
    page        = 1
    non_diffusibles = 0

    while True:
        params = {
            "activite_principale": naf_code,
            "departement": str(departement).zfill(2),
            "per_page": 25,
            "page": page,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
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
                    acteurs.append({
                        "nom":         r.get("nom_complet", ""),
                        "adresse":     siege.get("adresse", ""),
                        "latitude":    lat2,
                        "longitude":   lon2,
                        "distance_km": dist,
                        "siret":       r.get("siret", ""),
                        "naf":         naf_code,
                        "contact":     "",
                        "source":      "SIRENE",
                    })

            if page >= data.get("total_pages", 1):
                break
            page += 1
            time.sleep(0.2)

        except Exception as e:
            print(f"    ⚠ Erreur SIRENE ({naf_code}) : {e}")
            break

    if non_diffusibles:
        print(f"    ℹ {non_diffusibles} établissement(s) non-diffusible(s) (RGPD) ignoré(s) pour {naf_code}")

    return acteurs

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
            if resp.status_code != 200:
                print(f"    ⚠ Erreur RNA ({mot}) : HTTP {resp.status_code}")
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
                    acteurs.append({
                        "nom":         r.get("nom_complet", ""),
                        "adresse":     siege.get("adresse", ""),
                        "latitude":    lat2,
                        "longitude":   lon2,
                        "distance_km": dist,
                        "siret":       r.get("siret", ""),
                        "naf":         "asso",
                        "contact":     "",
                        "source":      "RNA (via Recherche d'Entreprises)",
                    })
            time.sleep(0.2)
        except Exception as e:
            print(f"    ⚠ Erreur RNA ({mot}) : {e}")

    return acteurs

# ─────────────────────────────────────────────
# 6. CHARGEMENT CPTS (base HubSpot interne)
# Le fichier cpts_hubspot.csv doit contenir :
# nom, adresse, latitude, longitude, contact, territoire
# ─────────────────────────────────────────────
def charger_cpts(lat, lon, rayon_km):
    acteurs = []
    try:
        df = pd.read_csv(CSV_CPTS)
        df = df.dropna(subset=["latitude", "longitude"])
        for _, row in df.iterrows():
            dist = haversine(lat, lon, float(row["latitude"]), float(row["longitude"]))
            if dist <= rayon_km:
                acteurs.append({
                    "nom":         row.get("nom", ""),
                    "adresse":     row.get("adresse", ""),
                    "latitude":    float(row["latitude"]),
                    "longitude":   float(row["longitude"]),
                    "distance_km": dist,
                    "siret":       row.get("siret", ""),
                    "naf":         "cpts",
                    "contact":     row.get("contact", ""),
                    "source":      "HubSpot CRM",
                })
        print(f"    ✓ {len(acteurs)} CPTS trouvée(s) dans le rayon")
    except FileNotFoundError:
        print(f"    ⚠ Fichier {CSV_CPTS} introuvable — CPTS ignorées")
        print(f"      → Exporte ta base HubSpot en CSV avec : nom, adresse, latitude, longitude, contact")
    return acteurs

# ─────────────────────────────────────────────
# 7. SCAN COMPLET ÉCOSYSTÈME
# ─────────────────────────────────────────────
def scanner_ecosysteme(pharmacie):
    lat  = pharmacie["latitude"]
    lon  = pharmacie["longitude"]
    dept = str(pharmacie["num_departement"]).zfill(2)

    tous = []
    print("Scan de l'écosystème en cours...\n")

    # SIRENE
    for cat, codes in NAF_CODES.items():
        rayon = RAYONS_KM[cat]
        print(f"  {ICONES[cat]} {LABELS[cat]} (rayon {rayon} km)...")
        for naf in codes:
            acteurs = scanner_sirene(lat, lon, naf, dept, rayon)
            for a in acteurs:
                a["categorie"] = cat
                a["label"]     = LABELS[cat]
                a["score"]     = calculer_score(cat, a["distance_km"], rayon)
            tous.extend(acteurs)

    # RNA
    rayon_asso = RAYONS_KM["asso"]
    print(f"  {ICONES['asso']} {LABELS['asso']} (rayon {rayon_asso} km)...")
    assos = scanner_rna(lat, lon, dept, rayon_asso)
    for a in assos:
        a["categorie"] = "asso"
        a["label"]     = LABELS["asso"]
        a["score"]     = calculer_score("asso", a["distance_km"], rayon_asso)
    tous.extend(assos)

    # CPTS (HubSpot)
    rayon_cpts = RAYONS_KM["cpts"]
    print(f"  {ICONES['cpts']} {LABELS['cpts']} (rayon {rayon_cpts} km — base HubSpot)...")
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
    print(f"\n✓ {len(uniques)} acteurs uniques identifiés.")
    return uniques

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
            popup_html = f"""
                <b>{a['nom']}</b><br>
                {a.get('adresse','')}<br>
                <span style="color:{color}">■ {LABELS[cat]}</span><br>
                Distance : <b>{a['distance_km']} km</b><br>
                Source : {a.get('source','')}<br>
                {"Contact : " + a['contact'] if a.get('contact') else ""}
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
            "acteur_contact":        a.get("contact", ""),
            "distance_km":           a["distance_km"],
            "source":                a.get("source", ""),
            "siret":                 a.get("siret", ""),
            "date_scan":             kpi["date_scan"],
            # Colonnes activation à remplir manuellement
            "contacte":              "",
            "date_contact":          "",
            "reponse":               "",
            "mise_en_relation":      "",
            "patientele_generee":    "",
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
    acteurs       = scanner_ecosysteme(pharmacie)
    kpi           = calculer_kpi(acteurs, pharmacie)
    afficher_resume(acteurs, kpi)
    generer_carte(pharmacie, acteurs, kpi)
    exporter_csv(acteurs, pharmacie, kpi)
    print(f"✅ KPI sauvegardés : {OUTPUT_KPI}")
    print("✅ Mapping terminé !\n")