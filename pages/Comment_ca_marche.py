import streamlit as st

import auth
import common
import db
import base64


st.set_page_config(
    page_title="Comment ça marche ?",
    layout="wide",
)

common.icon_title("Comment ça marche ?", "Comment_ca_marche.png", "📋")

col1, col2, col3 = st.columns(3,gap="medium",border=True)
with col1:
    if common.icon_button("Composer mon menu", "generer_mon_menu.png", "🛒", key="home-btn-generer"):
        st.switch_page("pages/2_Composer_mon_menu.py")
    st.markdown("Sélectionne des recettes pour "
    "composer ton menu. Indique le "
    "nombre de personnes pour chaque recette. Télécharge "
    "ta liste de courses et le carnet avec les recettes sélectionnées en PDF. "
    "Si tu as un compte, tu peux enregistrer ton menu pour consulter "
    "la liste de courses et les recettes plus tard.")

with col2:
    if common.icon_button("Ajouter une recette", "ajouter_une_recette.png", "🍳", key="home-btn-ajouter"):
        st.switch_page("pages/1_Ajouter_une_recette.py")
    st.markdown("Partage tes recettes coup de coeur ou celles de ton grand-père, ta tante, etc. "
    "**Réservé aux utilisateur·rices avec un compte** —"
    "Crée un compte ou connecte-toi via le menu à gauche.")

with col3:
    if common.icon_button("Mes menus", "mes_menus.png", "📋", key="home-btn-ajouter"):
        st.switch_page("pages/5_Mes_menus.py")
    st.markdown("Partage tes menus et ta liste de courses : parce que la gestion des repas, c'est un sport d'équipe"
    "**Réservé aux utilisateur·rices avec un compte** —"
    "Crée un compte ou connecte-toi via le menu à gauche.")

st.markdown("Utilise les deux boutons ci-dessus ou le menu à gauche pour naviguer entre les pages (appuye sur les >> en haut à gauche si tu utilises un smartphone ou une tablette.")

recipes = db.get_all_recipes()

col1, col2 = st.columns(2)
col1.metric("Recettes enregistrées", len(recipes))

recent = db.get_recent_recipes(limit=5)
if recent:
    st.subheader("Dernières recettes ajoutées")
    recent_cols = st.columns(len(recent))
    for col, r in zip(recent_cols, recent):
        with col:
            common.render_recipe_image_card(r["name"], r["image"])
            st.caption(
                f"👤 {r['created_by'] or 'inconnu'}  \n"
                f"🗓️ {common.format_datetime(r['created_at'])}"
            )
else:
    st.info("Aucune recette pour l'instant. Rendez-vous sur la page « Ajouter une recette ».")


