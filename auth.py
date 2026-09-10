"""
auth.py — Authentification légère basée sur la base de données (db.py).

Limitations à connaître :
- La session est stockée dans st.session_state, propre à chaque onglet /
  session de navigateur Streamlit. Sans mesure particulière, un
  rechargement complet de la page — ou même juste une reconnexion du
  WebSocket sous-jacent après quelques minutes d'inactivité (téléphone
  verrouillé, onglet en arrière-plan...), un cas très fréquent sur
  Streamlit Cloud — démarre une NOUVELLE session Streamlit et vide
  st.session_state, déconnectant la personne malgré elle.
- Pour éviter ça, on pose un cookie navigateur "garde-moi connecté·e"
  (voir REMEMBER_COOKIE_NAME plus bas, via streamlit-cookies-controller) :
  un jeton longue durée (30 jours), dont seul le hash est stocké côté
  serveur (db.remember_tokens). À chaque page vue où la session semble
  perdue, on vérifie ce cookie et on restaure la connexion silencieusement
  si le jeton est valide — voir _restore_session_from_cookie(). Le jeton
  est révoqué (et le cookie supprimé) uniquement à la déconnexion
  explicite, ou à expiration naturelle (30 jours).
- Les mots de passe sont hachés (PBKDF2-SHA256 salé) avant stockage, jamais
  conservés en clair.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_cookies_controller import CookieController

import db

import common

REMEMBER_COOKIE_NAME = "cookpotes_remember_token"


def _get_cookie_controller() -> CookieController:
    """
    Une nouvelle instance à chaque appel, comme dans tous les exemples de
    la bibliothèque : ce n'est pas une ressource serveur à partager entre
    utilisateur·rices (contrairement à @st.cache_resource ailleurs dans
    l'appli), juste un pont vers les cookies du navigateur de LA session
    Streamlit en cours.
    """
    return CookieController()


# ---------------------------------------------------------------------------
# État de connexion
# ---------------------------------------------------------------------------

def is_logged_in() -> bool:
    return st.session_state.get("auth_user") is not None


def is_editor() -> bool:
    return bool(st.session_state.get("auth_is_editor"))


def is_admin() -> bool:
    return bool(st.session_state.get("auth_is_admin"))


def can_manage_products() -> bool:
    """Droit de classer/corriger la base de produits d'épicerie (voir page « Produits »)."""
    return bool(st.session_state.get("auth_can_manage_products")) or is_admin()


def current_username() -> str | None:
    return st.session_state.get("auth_user")


def current_user_id() -> int | None:
    return st.session_state.get("auth_user_id")


def _apply_session(user: dict) -> None:
    """Pose dans st.session_state les clés auth_* à partir d'un dict utilisateur (verify_credentials ou verify_remember_token)."""
    st.session_state["auth_user"] = user["username"]
    st.session_state["auth_user_id"] = user["id"]
    st.session_state["auth_is_editor"] = user["is_editor"]
    st.session_state["auth_is_admin"] = user["is_admin"]
    st.session_state["auth_can_manage_products"] = user["can_manage_products"]


def _clear_session_state() -> None:
    """
    Vide TOUT st.session_state, pas seulement les clés auth_* — utilisé à
    la connexion et à la déconnexion.

    Pourquoi : certaines pages gardent en cache, dans st.session_state, des
    données propres à la personne connectée (ex : « Mes menus » garde le
    détail de la liste ouverte, y compris si elle en est propriétaire).
    Sans ce nettoyage, se déconnecter puis se reconnecter avec un AUTRE
    compte dans le même onglet de navigateur pouvait laisser resurgir des
    données de l'ancien compte (st.session_state persiste tant que l'onglet
    reste ouvert, un changement de compte ne le réinitialise pas tout
    seul). Un widget qui perd son état reprend simplement sa valeur par
    défaut au prochain rerun — sans conséquence, contrairement à une fuite
    de données entre deux comptes.
    """
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _restore_session_from_cookie() -> None:
    """
    Si la session en mémoire a été perdue (voir docstring du module) mais
    qu'un cookie "garde-moi connecté·e" valide est toujours présent dans le
    navigateur, restaure silencieusement la connexion — sans redemander
    l'identifiant/mot de passe. Ne fait rien si déjà connecté·e, ou si
    aucun cookie valide n'est présent.

    Limite connue : juste après l'ouverture d'un tout nouvel onglet/
    fenêtre (pas juste une reconnexion en cours de session), le composant
    cookie peut avoir besoin d'un aller-retour avant que Python ne "voie"
    le cookie existant — dans ce cas précis, un premier rerun peut encore
    montrer l'écran de connexion avant que la restauration silencieuse ne
    s'applique. Sans conséquence dans le cas visé ici (perte de session en
    cours d'usage), qui est le problème réellement rencontré.
    """
    if is_logged_in():
        return

    token = _get_cookie_controller().get(REMEMBER_COOKIE_NAME)
    if not token:
        return

    user = db.verify_remember_token(token)
    if user is None:
        # Jeton expiré ou révoqué : on nettoie le cookie périmé côté navigateur.
        _get_cookie_controller().remove(REMEMBER_COOKIE_NAME)
        return

    _apply_session(user)


def login(username: str, password: str) -> bool:
    user = db.verify_credentials(username, password)
    if user is None:
        return False
    _clear_session_state()
    _apply_session(user)

    # Pose le cookie "garde-moi connecté·e" — voir docstring du module.
    token = db.create_remember_token(user["id"])
    _get_cookie_controller().set(
        REMEMBER_COOKIE_NAME, token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=db.REMEMBER_TOKEN_DAYS),
    )
    return True


def logout() -> None:
    """Déconnexion EXPLICITE : révoque le jeton persistant (ce navigateur ne se reconnectera plus tout seul) et vide la session."""
    token = _get_cookie_controller().get(REMEMBER_COOKIE_NAME)
    if token:
        db.revoke_remember_token(token)
    _get_cookie_controller().remove(REMEMBER_COOKIE_NAME)
    _clear_session_state()


# ---------------------------------------------------------------------------
# Widgets d'interface
# ---------------------------------------------------------------------------

def render_sidebar_auth() -> None:
    """Affiche le statut de connexion, et le formulaire de connexion/déconnexion, dans la sidebar."""
    _restore_session_from_cookie()
    with st.sidebar:
        if is_logged_in():
            if is_admin():
                role_label = "Administrateur·rice"
            elif is_editor():
                role_label = "Éditeur·rice de recettes"
            else:
                role_label = "Lecteur·rice"
            if can_manage_products() and not is_admin():
                role_label += " · Gestion des produits"
            st.success(f"Connecté : **{current_username()}**  \nRôle : {role_label}")
            if st.button("Se déconnecter", key="_auth_logout_btn", use_container_width=True):
                logout()
                st.rerun()
        else:
            login_tab, signup_tab = st.tabs(["Se connecter", "Créer un compte"])

            with login_tab:
                with st.form("_auth_login_form", clear_on_submit=True):
                    username = st.text_input("Utilisateur·rice")
                    password = st.text_input("Mot de passe", type="password")
                    submitted = st.form_submit_button("Se connecter", use_container_width=True)
                if submitted:
                    if login(username, password):
                        st.rerun()
                    else:
                        st.error("Identifiant ou mot de passe incorrect.")

            with signup_tab:
                st.caption(
                    "Créer un compte "
                    "te permettra d'ajouter des recettes et de sauvegarder les menus "
                    "que tu as composés."
                )
                with st.form("_auth_signup_form", clear_on_submit=True):
                    new_username = st.text_input("Choisis un identifiant")
                    new_password = st.text_input(
                        "Choisis un mot de passe", type="password",
                        help="6 caractères minimum.",
                    )
                    new_password_confirm = st.text_input(
                        "Confirme le mot de passe", type="password",
                    )
                    signup_submitted = st.form_submit_button(
                        "Créer mon compte", use_container_width=True,
                    )
                if signup_submitted:
                    username_clean = new_username.strip()
                    if not username_clean or not new_password:
                        st.error("L'identifiant et le mot de passe sont obligatoires.")
                    elif len(new_password) < 6:
                        st.error("Le mot de passe doit contenir au moins 6 caractères.")
                    elif new_password != new_password_confirm:
                        st.error("Les deux mots de passe ne correspondent pas.")
                    else:
                        try:
                            db.create_user(
                                username_clean, new_password,
                                is_editor=True, is_admin=False,
                            )
                        except db.IntegrityError:
                            st.error(f"L'identifiant « {username_clean} » est déjà utilisé.")
                        else:
                            login(username_clean, new_password)
                            st.rerun()


def require_editor(
    message: str = "🔒 Connecte-toi  ou crée un compte (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
) -> None:
    """
    À appeler tout en haut d'une page réservée aux éditeurs de recettes.
    Affiche la sidebar de connexion, et arrête l'exécution de la page si
    l'utilisateur n'est pas connecté avec le statut éditeur (ou admin).
    """
    render_sidebar_auth()
    if not (is_logged_in() and (is_editor() or is_admin())):
        st.warning(message)
        st.stop()


def require_admin(
    message: str = "🔒 Cette page est réservée aux administrateur·rices.",
) -> None:
    """À appeler tout en haut d'une page réservée aux administrateurs."""
    render_sidebar_auth()
    if not (is_logged_in() and is_admin()):
        st.warning(message)
        st.stop()


def require_product_curator(
    message: str = "🔒 Cette page est réservée aux comptes ayant le droit de gérer la base de produits.",
) -> None:
    """À appeler tout en haut d'une page réservée à la gestion de la base de produits."""
    render_sidebar_auth()
    if not (is_logged_in() and can_manage_products()):
        st.warning(message)
        st.stop()


def require_login(
    message: str = "🔒 Connecte-toi  ou crée un compte (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
) -> None:
    """
    À appeler tout en haut d'une page réservée aux personnes connectées,
    sans exigence de rôle particulier (éditeur/admin) — ex: « Mes listes »,
    une fonctionnalité ouverte à tout compte, y compris les lecteur·rices.
    """
    render_sidebar_auth()
    if not is_logged_in():
        st.warning(message)
        st.stop()
