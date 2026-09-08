#!/usr/bin/env python3
"""
Accueil.py — Point d'entrée de l'application.

Lancement :
    streamlit run Accueil.py

IMPORTANT — architecture de navigation :
Ce fichier utilise st.navigation() pour construire le menu de gauche
dynamiquement, plutôt que la détection automatique du dossier pages/. Ça
permet de faire apparaître/disparaître une page selon l'état de connexion —
en particulier, la page « Gestion des utilisateur·rices » n'est incluse
dans la liste que si la personne est connectée en tant qu'admin.

Conséquence technique : avec st.navigation(), toutes les pages s'exécutent
dans le MÊME run Streamlit (contrairement à l'ancien système de dossier
pages/, où chaque page était un script top-level indépendant). st.set_page
_config() ne peut être appelé qu'UNE SEULE FOIS par run : il doit rester
ici, et a été retiré du haut de chaque fichier de pages/.

Au tout premier lancement, un compte administrateur par défaut est créé
automatiquement : identifiant "admin", mot de passe "admin123". Connectez-
vous avec ce compte puis changez immédiatement ce mot de passe depuis la
page « Gestion des utilisateur·rices ».
"""

import streamlit as st
from pathlib import Path

import auth
import common
import db

st.set_page_config(
    page_title="Liste de courses & carnet de recettes",
    page_icon="🛒",
    layout="wide",
)

def home_page() -> None:
    db.init_db()
    auth.render_sidebar_auth()

    common.header_logo()

    st.markdown(
        """
Bienvenue ! Cette application te permet de :
        """
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🛒 Générer ma liste"):
            st.switch_page("pages/2_Generer_ma_liste.py")
        st.markdown("Sélectionne les recettes pour "
        "la semaine (ou le mois, soyons foufolles). Indique le "
        "nombre de personnes pour chaque recette, un clic et le tour est joué ! Tu reçois "
        "ta liste de courses et un carnet avec les recettes sélectionnées en PDF.")

    with col2:
        if st.button("🍳 Ajouter une recette"):
            st.switch_page("pages/1_🍳_Ajouter_une_recette.py")
        st.markdown("Partage tes recettes coup de coeur ou celles de ton grand-père, ta tante, etc. "
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


# ---------------------------------------------------------------------------
# Navigation : construite à chaque run, donc reflète toujours l'état de
# connexion courant (mis à jour dans st.session_state par auth.login() lors
# d'un rerun précédent).
#
# On garde une référence à chaque objet st.Page dans NAV_ITEMS (avec le nom
# de fichier d'icône perso associé) pour pouvoir reconstruire nous-mêmes le
# menu ci-dessous, à la place du menu automatique de st.navigation.
# ---------------------------------------------------------------------------

home_page_obj = st.Page(home_page, title="Accueil", icon="🏠", default=True)
generer_page = st.Page("pages/2_Generer_ma_liste.py", title="Générer ma liste", icon="🛒")
ajouter_page = st.Page("pages/1_🍳_Ajouter_une_recette.py", title="Ajouter une recette", icon="🍳")

# (page, fichier d'icône dans assets/icons/, emoji de secours si le fichier
# n'existe pas encore — le menu reste donc toujours fonctionnel même avant
# d'avoir déposé vos propres images).
NAV_ITEMS = [
    (home_page_obj, "accueil.png", "🏠"),
    (generer_page, "generer_ma_liste.png", "🛒"),
    (ajouter_page, "ajouter_une_recette.png", "🍳"),
]
pages = [home_page_obj, generer_page, ajouter_page]

if auth.is_editor():
    mes_listes_page = st.Page("pages/5_📋_Mes_listes.py", title="Mes listes", icon="📋")
    pages.append(mes_listes_page)
    NAV_ITEMS.append((mes_listes_page, "mes_listes.png", "📋"))

if auth.is_admin():
    gestion_users_page = st.Page(
        "pages/3_👤_Gestion_des_utilisateur·rices.py",
        title="Gestion des utilisateur·rices",
        icon="👤",
    )
    pages.append(gestion_users_page)
    NAV_ITEMS.append((gestion_users_page, "gestion_utilisateurs.png", "👤"))

if auth.can_manage_products():
    gestion_produits_page = st.Page(
        "pages/4_🧺_Produits.py",
        title="Gestion des produits",
        icon="🧺",
    )
    pages.append(gestion_produits_page)
    NAV_ITEMS.append((gestion_produits_page, "gestion_produits.png", "🧺"))


# Menu automatique désactivé (position="hidden") : on affiche notre propre
# menu juste en dessous, avec des icônes personnalisées à la place des
# émojis. st.navigation reste néanmoins nécessaire tel quel : c'est lui qui
# route vers la bonne page (pg.run() plus bas) et qui gère les URLs.
pg = st.navigation(pages, position="hidden")

ICONS_DIR = Path(__file__).parent / "assets" / "icons"

with st.sidebar:
    st.markdown(
        """
        <style>
        /* Resserre le lien de page pour qu'il s'aligne avec l'icône à côté. */
        div[data-testid="stPageLink"] > a { padding-top: 0.15em; padding-bottom: 0.15em; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for page, icon_filename, fallback_emoji in NAV_ITEMS:
        icon_col, link_col = st.columns([1, 5], gap="small", vertical_alignment="center")
        icon_path = ICONS_DIR / icon_filename
        with icon_col:
            if icon_path.exists():
                st.image(str(icon_path), width=24)
            else:
                # Pas (encore) de logo perso pour cette page : on retombe
                # sur l'émoji d'origine plutôt que de laisser un trou.
                st.markdown(
                    f"<div style='font-size:1.3em; text-align:center;'>{fallback_emoji}</div>",
                    unsafe_allow_html=True,
                )
        with link_col:
            st.page_link(page, label=page.title)

pg.run()

