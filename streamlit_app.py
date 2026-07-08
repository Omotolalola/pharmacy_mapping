import json

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as st_html

from pharmadeliv_mapping_v2 import (
    charger_pharmacies,
    scanner_ecosysteme,
    calculer_kpi,
    generer_carte,
    exporter_csv,
    OUTPUT_CSV,
    OUTPUT_KPI,
    OUTPUT_MAP,
)

st.set_page_config(page_title="Pharmadeliv Mapping interactif", layout="wide")

st.title("Pharmadeliv — Mapping interactif")
st.write(
    "Recherche de pharmacie, génération du mapping territorial et partage facile de la carte interactive."
)

@st.cache_data
def load_pharmacies() -> pd.DataFrame:
    return charger_pharmacies()

@st.cache_data(show_spinner=False, ttl=86400)
def cached_scanner_ecosysteme(pharmacie_data: dict):
    return scanner_ecosysteme(pharmacie_data)

pharmacies = load_pharmacies()

with st.sidebar:
    st.header("Recherche de pharmacie partenaire")
    query = st.text_input("Nom ou ville", placeholder="Exemple : Paris, Pharmacie Dupont")

    # On ne travaille QUE sur les pharmacies déjà partenaires Pharmadeliv.
    # (cast explicite en bool pour éviter tout souci si le CSV est un jour
    # régénéré avec des valeurs "True"/"False" en texte ou 0/1)
    partenaires = pharmacies[pharmacies["accepte_commandes"].astype(bool) == True]

    resultats = partenaires
    if query:
        resultats = resultats[
            resultats["nom"].str.contains(query, case=False, na=False)
            | resultats["ville"].str.contains(query, case=False, na=False)
        ]

    if resultats.empty:
        if query:
            st.info(
                f"Aucune pharmacie **partenaire** ne correspond à « {query} ». "
                "Rappel : seules les pharmacies déjà partenaires Pharmadeliv sont proposées ici."
            )
            with st.expander("Voir les villes où Pharmadeliv a des pharmacies partenaires"):
                st.write(sorted(partenaires["ville"].unique().tolist()))
        else:
            st.warning("Aucune pharmacie partenaire trouvée dans le fichier chargé.")
        selected_pharmacie = None
    else:
        preview = resultats[["nom", "ville", "departement", "adresse_complete", "accepte_commandes"]].copy()
        preview["statut"] = preview["accepte_commandes"].map({True: "Partenaire", False: "Prospect", pd.NA: "Inconnu"})
        preview = preview.rename(
            columns={
                "nom": "Nom",
                "ville": "Ville",
                "departement": "Département",
                "adresse_complete": "Adresse",
                "statut": "Statut",
            }
        )
        st.dataframe(preview.head(20), use_container_width=True)

        selection_items = [
            f"{idx} — {row['nom']} ({row['ville']})"
            for idx, row in resultats.reset_index(drop=False).iterrows()
        ]
        choice = st.selectbox("Choisir une pharmacie", selection_items)
        selected_index = int(choice.split(" — ")[0])
        selected_pharmacie = resultats.reset_index(drop=False).loc[selected_index]

    st.markdown("---")
    st.write("**Résultats export**")
    st.write("La carte HTML et les fichiers CSV/JSON sont générés automatiquement après le scan.")

if selected_pharmacie is not None:
    st.sidebar.success(f"Pharmacie sélectionnée : {selected_pharmacie['nom']}")

    if st.sidebar.button("Générer le mapping"):
        with st.spinner("Scan de l'écosystème en cours..."):
            pharmacie_data = selected_pharmacie.to_dict()
            acteurs, scan_logs = cached_scanner_ecosysteme(pharmacie_data)
            kpi = calculer_kpi(acteurs, selected_pharmacie)
            generer_carte(selected_pharmacie, acteurs, kpi)
            exporter_csv(acteurs, selected_pharmacie, kpi)

        st.markdown("## Résultats du scan")

        if scan_logs:
            with st.expander(f"⚠ {len(scan_logs)} avertissement(s) pendant le scan", expanded=(kpi["nb_acteurs_total"] == 0)):
                for l in scan_logs:
                    st.write(f"- {l}")

        if kpi["nb_acteurs_total"] == 0:
            st.warning(
                "Aucun acteur trouvé autour de cette pharmacie. Regarde le détail des "
                "avertissements ci-dessus : c'est très probablement un HTTP 429 "
                "(rate-limit de l'API recherche-entreprises.api.gouv.fr) si tu as lancé "
                "plusieurs scans à la suite. Dans ce cas, attends 1 à 2 minutes et relance."
            )

        metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
        metrics_col1.metric("Acteurs identifiés", kpi["nb_acteurs_total"])
        metrics_col2.metric("Catégories couvertes", kpi["nb_categories"])
        metrics_col3.metric("Couverture (%)", f"{kpi['couverture_pct']} %")

        expander = st.expander("Détails KPI")
        expander.json(kpi)

        st.markdown("### Tableau complet des acteurs")
        df_acteurs = pd.DataFrame(acteurs)
        if "score" in df_acteurs.columns:
            df_acteurs = df_acteurs.drop(columns=["score"])
        st.dataframe(df_acteurs, use_container_width=True)

        st.markdown("### Carte interactive")
        try:
            with open(OUTPUT_MAP, "r", encoding="utf-8") as f:
                map_html = f.read()
            st_html(map_html, height=750, scrolling=True)
        except FileNotFoundError:
            st.error(f"Le fichier {OUTPUT_MAP} est introuvable.")

        st.markdown("### Téléchargement")
        try:
            with open(OUTPUT_CSV, "rb") as f_csv:
                csv_bytes = f_csv.read()
            with open(OUTPUT_MAP, "r", encoding="utf-8") as f_map:
                html_bytes = f_map.read().encode("utf-8")
            json_bytes = json.dumps(kpi, ensure_ascii=False, indent=2).encode("utf-8")

            st.download_button("Télécharger la carte HTML", data=html_bytes, file_name=OUTPUT_MAP, mime="text/html")
            st.download_button("Télécharger le CSV des acteurs", data=csv_bytes, file_name=OUTPUT_CSV, mime="text/csv")
            st.download_button("Télécharger les KPI JSON", data=json_bytes, file_name=OUTPUT_KPI, mime="application/json")
        except FileNotFoundError as e:
            st.warning(f"Fichier non trouvé : {e}")
else:
    st.info("Sélectionne une pharmacie dans la barre latérale pour lancer le mapping.")