import streamlit as st

import auth
import common
import base64


st.set_page_config(
    page_title="Comment ça marche ?",
    layout="wide",
)

common.icon_title("Comment ça marche ?", "comment_ca_marche.png", "📋")

col1, col2, col3 = st.columns(3,gap="medium",border=True)
with col1:
    if common.icon_button("Composer mon menu", "generer_mon_menu.png", "🛒", key="home-btn-generer"):
        st.switch_page("pages/2_Composer_mon_menu.py")
    st.markdown("Sélectionne des recettes pour "
    "composer ton menu. Indique le "
    "nombre de personnes pour chaque recette. Télécharge "
    "ta liste de courses et le carnet avec les recettes sélectionnées en PDF. "
    "Si tu as un compte, tu peux enregistrer ton menu pour consulter "
    "la liste de courses et les recettes plus tard, directement dans l'app.")

with col2:
    if common.icon_button("Ajouter une recette", "ajouter_une_recette.png", "🍳", key="home-btn-ajouter"):
        st.switch_page("pages/1_Ajouter_une_recette.py")
    st.markdown("Tu es le contrôle qualité ! Ici, on ne partage que du vécu "
    ": ajoute tes recettes coup de cœur ou les pépites de ton grand-père, "
    "à condition de les avoir testées et approuvées. Encode précisément "
    "chaque ingrédient et étape : ta recette te servira à composer tes menus "
    "et régalera automatiquement tou·tes les CookPotes."
    "<p>**Réservé aux utilisateur·rices avec un compte** —"
    "Crée un compte ou connecte-toi via le menu à gauche.</p>",unsafe_allow_html=True)

with col3:
    if common.icon_button("Mes menus", "mes_menus.png", "📋", key="home-btn-menu"):
        st.switch_page("pages/5_Mes_menus.py")
    st.markdown("Consulte tes menus enregistrés, coche les produits de ta liste pendant "
    "tes courses et affiche tes recettes étape par étape. "
    "Et parce que la gestion des repas, c'est un sport d'équipe : partage tes menus (et ta charge mentale) "
    "avec ton/ta cohéquipier·e ! "
    "<p>**Réservé aux utilisateur·rices avec un compte** —"
    "Crée un compte ou connecte-toi via le menu à gauche.</p>",unsafe_allow_html=True,)

st.markdown("Utilise les trois boutons ci-dessus ou le menu à gauche pour naviguer entre les pages (appuye sur les >> en haut à gauche si tu utilises un smartphone ou une tablette.")



