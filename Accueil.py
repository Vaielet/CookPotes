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

Les icônes personnalisées du menu (et des boutons ci-dessous) sont gérées
par common.icon_page_link / common.icon_button — utilisables de la même
façon depuis n'importe quelle autre page de l'appli, pas seulement ici.

Au tout premier lancement, un compte administrateur par défaut est créé
automatiquement : identifiant "admin", mot de passe "admin123". Connectez-
vous avec ce compte puis changez immédiatement ce mot de passe depuis la
page « Gestion des utilisateur·rices ».
"""

import streamlit as st

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

    col1, col2 = st.columns(2,gap="large",border=True)
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

home_page_obj = st.Page(home_page, title="Accueil", default=True)
generer_page = st.Page("pages/2_Composer_mon_menu.py", title="Composer mon menu")
ajouter_page = st.Page("pages/1_Ajouter_une_recette.py", title="Ajouter une recette")

# (page, fichier d'icône dans images/icons/, emoji de secours si le fichier
# n'existe pas encore — le menu reste donc toujours fonctionnel même avant
# d'avoir déposé vos propres images).
NAV_ITEMS = [
    (home_page_obj, "accueil.png", "🏠"),
    (generer_page, "generer_mon_menu.png", "🛒"),
    (ajouter_page, "ajouter_une_recette.png", "🍳"),
]
pages = [home_page_obj, generer_page, ajouter_page]

if auth.is_editor():
    mes_listes_page = st.Page("pages/5_Mes_menus.py", title="Mes menus")
    pages.append(mes_listes_page)
    NAV_ITEMS.append((mes_listes_page, "mes_menus.png", "📋"))

if auth.is_admin():
    gestion_users_page = st.Page(
        "pages/3_Gestion_des_utilisateur·rices.py",
        title="Gestion des utilisateur·rices",
    )
    pages.append(gestion_users_page)
    NAV_ITEMS.append((gestion_users_page, "gestion_utilisateurs.png", "👤"))

if auth.can_manage_products():
    gestion_produits_page = st.Page(
        "pages/4_Produits.py",
        title="Gestion des produits",
    )
    pages.append(gestion_produits_page)
    NAV_ITEMS.append((gestion_produits_page, "gestion_produits.png", "🧺"))


# Menu automatique désactivé (position="hidden") : on affiche notre propre
# menu juste en dessous, avec des icônes personnalisées à la place des
# émojis, alignées à gauche (common.icon_page_link). st.navigation reste
# néanmoins nécessaire tel quel : c'est lui qui route vers la bonne page
# (pg.run() plus bas) et qui gère les URLs.
pg = st.navigation(pages, position="hidden")


# Injection CSS avancée avec media query pour la barre réduite
st.html("""
  <style>
    /* --- STYLES PAR DÉFAUT (Sidebar OUVERTE) --- */

    /* Centre et donne de l'espace au conteneur principal */
    div[data-testid="stSidebarHeader"] {
        display: flex !important;
        justify-content: center !important; /* Centrage horizontal */
        align-items: center !important;     /* Centrage vertical */
        padding-top: 1.5rem !important;
        padding-bottom: 1rem !important;
        height: auto !important;
        max-height: none !important;
    }

    /* Définit la taille du logo et le centre */
    [alt="Logo"] {
        height: 100px !important; /* Taille sidebar ouverte */
        width: auto !important;
        margin-left: auto !important;
        margin-right: auto !important;
        display: block !important;
        object-fit: contain !important;
        transition: height 0.3s ease; /* Animation fluide lors du changement de taille */
    }


    /* --- STYLES SPÉCIFIQUES (Sidebar RÉDUITE / FERMÉE) --- */

    /* Le sélecteur [data-sidebar-collapsed="true"] cible la sidebar quand elle est fermée */
    [data-sidebar-collapsed="true"] div[data-testid="stSidebarHeader"] {
        padding-top: 0.5rem !important; /* Moins d'espace en haut */
        padding-bottom: 0.5rem !important;
        justify-content: center !important;
    }

    /* Réduit la taille du logo pour qu'il ne dépasse pas */
    [data-sidebar-collapsed="true"] [alt="Logo"] {
        height: 35px !important; /* Taille réduite sidebar fermée (ajustez si besoin) */
        margin: 0 auto !important; /* Centrage strict */
    }

  </style>
""")

# Utilisation de st.logo
st.logo(
    image="images/CookPotes_logo_transparent.png",
    # Vous n'avez pas besoin d'icon_image, le CSS gère le redimensionnement de l'image principale
    size="large"
)
with st.sidebar:
    # Resserre l'espacement vertical entre les éléments du menu : par
    # défaut, Streamlit met ~1rem d'écart entre les blocs empilés dans la
    # sidebar (chaque lien vit dans son propre st.container), ce qui
    # donnait un menu très aéré. Ciblé sur la sidebar uniquement — ne
    # touche pas le contenu des pages.
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
            gap: 0.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for page, icon_filename, fallback_emoji in NAV_ITEMS:
        common.icon_page_link(page, icon_filename, fallback_emoji)

pg.run()

