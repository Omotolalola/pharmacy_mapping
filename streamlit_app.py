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

pharmacies = load_pharmacies()

with st.sidebar:
    st.header("Recherche de pharmacie")
    query = st.text_input("Nom ou ville", placeholder="Exemple : Paris, Pharmacie Dupont")
    filtrer_partenaire = st.checkbox("Afficher uniquement les pharmacies déjà associées à Pharmadeliv", value=True)

    if query:
        resultats = pharmacies[
            pharmacies["nom"].str.contains(query, case=False, na=False)
            | pharmacies["ville"].str.contains(query, case=False, na=False)
        ]
    else:
        resultats = pharmacies.copy()

    if filtrer_partenaire:
        resultats = resultats[resultats["accepte_commandes"] == True]

    st.write(f"{len(resultats)} résultat(s) trouvés")

    if resultats.empty:
        st.info("Aucun résultat à afficher. Essaye un autre terme de recherche.")
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
            acteurs = scanner_ecosysteme(selected_pharmacie)
            kpi = calculer_kpi(acteurs, selected_pharmacie)
            generer_carte(selected_pharmacie, acteurs, kpi)
            exporter_csv(acteurs, selected_pharmacie, kpi)

        st.success("Mapping généré avec succès !")

        st.markdown("## Résultats du scan")

        metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
        metrics_col1.metric("Acteurs identifiés", kpi["nb_acteurs_total"])
        metrics_col2.metric("Catégories couvertes", kpi["nb_categories"])
        metrics_col3.metric("Couverture (%)", f"{kpi['couverture_pct']} %")

        expander = st.expander("Détails KPI")
        expander.json(kpi)

        st.markdown("### Tableau complet des acteurs")
        df_acteurs = pd.DataFrame(acteurs)
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
