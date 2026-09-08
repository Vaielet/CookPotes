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

import base64
import mimetypes
import re
from pathlib import Path

import streamlit as st

import auth
import common
import db

st.set_page_config(
    page_title="Liste de courses & carnet de recettes",
    page_icon="🛒",
    layout="wide",
)

ICONS_DIR = Path(__file__).parent / "images"/"icons"


def _slug(name: str) -> str:
    """Transforme un nom de fichier en identifiant sûr pour une clé de
    container / classe CSS (lettres, chiffres, tirets seulement)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _icon_css(container_key: str, icon_path: Path, fallback_emoji: str, tag: str = "a") -> str:
    """
    Règle CSS qui insère l'icône juste avant le texte d'un élément (lien du
    menu, ou bouton — via `tag="button"`), DANS l'élément lui-même
    (pseudo-élément ::before), plutôt que dans une colonne Streamlit
    séparée à côté. Deux avantages par rapport à une mise en page en
    colonnes :
      - alignement pile au pixel près, puisque icône et texte appartiennent
        au même élément flexbox ;
      - jamais d'empilement vertical sur mobile, puisqu'il n'y a qu'UN
        seul composant Streamlit — les st.columns, elles, s'empilent sous
        une certaine largeur d'écran.

    Si le fichier d'icône n'existe pas, l'émoji de secours est utilisé
    comme contenu texte du pseudo-élément — aucune image à charger.
    """
    if icon_path.exists():
        mime = mimetypes.guess_type(icon_path.name)[0] or "image/png"
        b64 = base64.b64encode(icon_path.read_bytes()).decode()
        before_content = f"""
            content: "";
            background-image: url("data:{mime};base64,{b64}");
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            width: 26px;
            height: 26px;
        """
    else:
        before_content = f"""
            content: "{fallback_emoji}";
            font-size: 1.4em;
            line-height: 1;
            width: 26px;
            text-align: center;
        """
    return f"""
        .st-key-{container_key} {tag} {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.6em;
        }}
        .st-key-{container_key} {tag}::before {{
            {before_content}
            display: inline-block;
            flex-shrink: 0;
        }}
    """


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
        with st.container(key="home-btn-generer"):
            if st.button("Générer ma liste"):
                st.switch_page("pages/2_Generer_ma_liste.py")
        st.markdown("Sélectionne les recettes pour "
        "la semaine (ou le mois, soyons foufolles). Indique le "
        "nombre de personnes pour chaque recette, un clic et le tour est joué ! Tu reçois "
        "ta liste de courses et un carnet avec les recettes sélectionnées en PDF.")

    with col2:
        with st.container(key="home-btn-ajouter"):
            if st.button("Ajouter une recette"):
                st.switch_page("pages/1_Ajouter_une_recette.py")
        st.markdown("Partage tes recettes coup de coeur ou celles de ton grand-père, ta tante, etc. "
        "**Réservé aux utilisateur·rices avec un compte** —"
        "Crée un compte ou connecte-toi via le menu à gauche.")

    st.markdown(
        "<style>"
        + _icon_css("home-btn-generer", ICONS_DIR / "generer_mon_menu.png", "🛒", tag="button")
        + _icon_css("home-btn-ajouter", ICONS_DIR / "ajouter_une_recette.png", "🍳", tag="button")
        + "</style>",
        unsafe_allow_html=True,
    )

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
generer_page = st.Page("pages/2_Generer_ma_liste.py", title="Générer ma liste")
ajouter_page = st.Page("pages/1_Ajouter_une_recette.py", title="Ajouter une recette")

# (page, fichier d'icône dans images/, emoji de secours si le fichier
# n'existe pas encore — le menu reste donc toujours fonctionnel même avant
# d'avoir déposé vos propres images).
NAV_ITEMS = [
    (home_page_obj, "accueil.png", "🏠"),
    (generer_page, "generer_mon_menu.png", "🛒"),
    (ajouter_page, "ajouter_une_recette.png", "🍳"),
]
pages = [home_page_obj, generer_page, ajouter_page]

if auth.is_editor():
    mes_listes_page = st.Page("pages/5_Mes_listes.py", title="Mes listes")
    pages.append(mes_listes_page)
    NAV_ITEMS.append((mes_listes_page, "mes_listes.png", "📋"))

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
# émojis. st.navigation reste néanmoins nécessaire tel quel : c'est lui qui
# route vers la bonne page (pg.run() plus bas) et qui gère les URLs.
pg = st.navigation(pages, position="hidden")

with st.sidebar:
    css_rules = []
    for page, icon_filename, fallback_emoji in NAV_ITEMS:
        container_key = f"navitem-{_slug(Path(icon_filename).stem)}"
        css_rules.append(_icon_css(container_key, ICONS_DIR / icon_filename, fallback_emoji))
        with st.container(key=container_key):
            st.page_link(page, label=page.title)

    st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)

pg.run()

