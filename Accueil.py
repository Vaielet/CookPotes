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
import base64


st.set_page_config(
    page_title="Liste de courses & carnet de recettes",
    page_icon="🛒",
    layout="wide",
)

def get_image_base64(file_path):
    """Convertit une image locale en chaîne Base64."""
    with open(file_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode("utf-8")


def home_page() -> None:
    db.init_db()
    auth.render_sidebar_auth()

    #common.header_logo()

    # --- CONVERSION DU LOGO ---
    logo_with_subtitle_b64 = get_image_base64("images/CookPotes_logo_with_subtitle.png")

    # Injection du logo en HTML/Base64 (100% natif, centré, sans overlay Streamlit)
    st.markdown(
        f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%;">
            <img src="data:image/png;base64,{logo_with_subtitle_b64}" style="width: 60%; max-width: 300px; height: auto;">
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
<p>Bienvenue sur CookPotes !</p>
<p>Chez toi aussi, la planification des repas ressemble à un parcours du combattant ?</p>
<p>Entre le casse-tête de la semaine (« On mange quoiii ce soir ? »), le marathon des courses avec une liste longue comme le bras, les quantités approximatives (« Bon, 3 kilos de pâtes ça devrait aller ») et les repas équilibrés préparés avec amour que ton petit dernier préfère balancer par terre... Tu n'es pas seul·e !
Il est temps de poser les armes. CookPotes, c'est l'application qui vient sauver tes soirées, ton portefeuille et ta santé mentale :</p>
<ul>
  <li><strong>Zéro prise de tête :</strong> Des idées de menus adaptées à toute la famille en deux clics.</li>
  <li><strong>Raid éclair au supermarché :</strong> Une liste de courses automatique avec pile les bonnes quantités (fini le gâchis, bonjour les économies !).</li>
  <li><strong>Du sain, du bon, du vrai :</strong> Même les plus récalcitrants à la table finiront par en redemander.</li>
</ul>
<p>Bref, ensemble, sortons de la galère, gagnons du temps et mettons fin au gaspillage. Avec CookPotes, reprends enfin le contrôle de ta cuisine ! </p>
        """,
        unsafe_allow_html=True,
    )

    # Injection CSS pour centrer les boutons Streamlit dans leurs conteneurs
    st.markdown(
        """
        <style>
        div.stButton > button {
            display: block;
            margin-0 auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2,gap="medium",border=False)
    with col1:
        if common.icon_button("Je veux savoir comment ça marche", "comment_ca_marche.png", "❓", key="home-btn-comment"):
            st.switch_page("pages/Comment_ca_marche.py")
    with col2:
        if common.icon_button("C'est parti, je veux composer mon menu", "generer_mon_menu.png", "📋", key="home-btn-generer"):
            st.switch_page("pages/2_Composer_mon_menu.py")
        
    recipes = db.get_all_recipes()

    st.markdown(
        f"Il y a déjà {len(recipes)} recettes prêtes à être ajoutées à ton menu !",
        unsafe_allow_html=True,
    )

    recent = db.get_recent_recipes(limit=5)
    if recent:
        st.caption("Dernières recettes ajoutées")
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
comment_page = st.Page("pages/Comment_ca_marche.py", title="Comment ça marche ?")
generer_page = st.Page("pages/2_Composer_mon_menu.py", title="Composer mon menu")
ajouter_page = st.Page("pages/1_Ajouter_une_recette.py", title="Ajouter une recette")
mes_menus_page = st.Page("pages/5_Mes_menus.py", title="Mes menus")


# (page, fichier d'icône dans images/icons/, emoji de secours si le fichier
# n'existe pas encore — le menu reste donc toujours fonctionnel même avant
# d'avoir déposé vos propres images).
NAV_ITEMS = [
    (home_page_obj, "accueil.png", "🏠"),
    (comment_page, "comment_ca_marche.png", "🏠"),
    (generer_page, "generer_mon_menu.png", "🛒"),
    (ajouter_page, "ajouter_une_recette.png", "🍳"),
    (mes_menus_page, "mes_menus.png", "📋"),
]
pages = [home_page_obj, comment_page, generer_page, ajouter_page, mes_menus_page]

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


# --- CONVERSION DU LOGO ---
logo_b64 = get_image_base64("images/CookPotes_logo_transparent.png")

# --- SIDEBAR ---
with st.sidebar:
    st.space(2)
    
    # Injection du logo en HTML/Base64 (100% natif, centré, sans overlay Streamlit)
    st.markdown(
        f"""
        <div style="display: flex; justify-content: center; align-items: center; width: 100%;">
            <img src="data:image/png;base64,{logo_b64}" style="width: 60%; max-width: 160px; height: auto;">
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.space(1)
    st.divider()

    # Reste de votre navigation
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
