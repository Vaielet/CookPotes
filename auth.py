"""
auth.py — Authentification légère basée sur la base de données (db.py).

Limitations à connaître :
- La session est stockée dans st.session_state, propre à chaque onglet /
  session de navigateur Streamlit. Un rechargement complet de la page ou
  une nouvelle session de navigateur déconnecte l'utilisateur (Streamlit
  n'offre pas nativement de cookie de session persistant sans bibliothèque
  tierce). C'est suffisant pour un usage interne à une famille / petite
  équipe, mais pas pour une authentification "entreprise".
- Les mots de passe sont hachés (PBKDF2-SHA256 salé) avant stockage, jamais
  conservés en clair.
"""

from __future__ import annotations

import streamlit as st

import db


# ---------------------------------------------------------------------------
# État de connexion
# ---------------------------------------------------------------------------

def is_logged_in() -> bool:
    return st.session_state.get("auth_user") is not None


def is_editor() -> bool:
    return bool(st.session_state.get("auth_is_editor"))


def is_admin() -> bool:
    return bool(st.session_state.get("auth_is_admin"))


def current_username() -> str | None:
    return st.session_state.get("auth_user")


def login(username: str, password: str) -> bool:
    user = db.verify_credentials(username, password)
    if user is None:
        return False
    st.session_state["auth_user"] = user["username"]
    st.session_state["auth_user_id"] = user["id"]
    st.session_state["auth_is_editor"] = user["is_editor"]
    st.session_state["auth_is_admin"] = user["is_admin"]
    return True


def logout() -> None:
    for key in ("auth_user", "auth_user_id", "auth_is_editor", "auth_is_admin"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Widgets d'interface
# ---------------------------------------------------------------------------

def render_sidebar_auth() -> None:
    """Affiche le statut de connexion, et le formulaire de connexion/déconnexion, dans la sidebar."""
    with st.sidebar:
        st.markdown("### 👤 Compte")
        if is_logged_in():
            if is_admin():
                role_label = "Administrateur·rice"
            elif is_editor():
                role_label = "Éditeur·rice de recettes"
            else:
                role_label = "Lecteur·rice"
            st.success(f"Connecté : **{current_username()}**  \nRôle : {role_label}")
            if st.button("Se déconnecter", key="_auth_logout_btn", use_container_width=True):
                logout()
                st.rerun()
        else:
            with st.form("_auth_login_form", clear_on_submit=True):
                username = st.text_input("Utilisateur·rice")
                password = st.text_input("Mot de passe", type="password")
                submitted = st.form_submit_button("Se connecter", use_container_width=True)
            if submitted:
                if login(username, password):
                    st.rerun()
                else:
                    st.error("Identifiant ou mot de passe incorrect.")


def require_editor(
    message: str = "🔒 Connectez-vous avec un compte éditeur (menu de gauche) pour accéder à cette page.",
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
    message: str = "🔒 Cette page est réservée aux administrateurs.",
) -> None:
    """À appeler tout en haut d'une page réservée aux administrateurs."""
    render_sidebar_auth()
    if not (is_logged_in() and is_admin()):
        st.warning(message)
        st.stop()
