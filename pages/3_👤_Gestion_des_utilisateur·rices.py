"""
Page 3 — Gestion des utilisateurs.

Réservée aux administrateurs. Permet de créer de nouveaux comptes, de leur
attribuer (ou retirer) le statut éditeur / administrateur, de réinitialiser
un mot de passe, et de supprimer un compte.
"""

import streamlit as st

import auth
import db

import common

st.set_page_config(page_title="Gestion des utilisateur·rices", page_icon="👤", layout="wide")

db.init_db()

common.header_logo()

auth.require_admin()

st.title("👤 Gestion des utilisateur·rices")
st.caption(
    "Crée des comptes et attribue le statut « éditeur·rice » aux personnes "
    "autorisées à ajouter ou modifier des recettes. Seul·es les "
    "administrateur·rices voient cette page."
)

if st.session_state.get("_flash_user_msg"):
    st.success(st.session_state["_flash_user_msg"])
    st.session_state["_flash_user_msg"] = None


# ---------------------------------------------------------------------------
# Création d'un nouvel utilisateur
# ---------------------------------------------------------------------------

st.subheader("Créer un·e utilisateur·rice")

with st.form("_create_user_form", clear_on_submit=True):
    cols = st.columns([2, 2, 1, 1])
    new_username = cols[0].text_input("Identifiant")
    new_password = cols[1].text_input("Mot de passe", type="password")
    new_is_editor = cols[2].checkbox("Éditeur·rice", value=True)
    new_is_admin = cols[3].checkbox("Admin", value=False)
    submitted = st.form_submit_button("➕ Créer le compte", type="primary")

if submitted:
    username = new_username.strip()
    if not username or not new_password:
        st.error("L'identifiant et le mot de passe sont obligatoires.")
    elif len(new_password) < 6:
        st.error("Le mot de passe doit contenir au moins 6 caractères.")
    else:
        try:
            db.create_user(username, new_password, is_editor=new_is_editor, is_admin=new_is_admin)
        except db.IntegrityError:
            st.error(f"L'identifiant « {username} » est déjà utilisé.")
        else:
            st.session_state["_flash_user_msg"] = f"Compte « {username} » créé avec succès."
            st.rerun()


# ---------------------------------------------------------------------------
# Liste des utilisateurs existants
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Comptes existants")

users = db.list_users()

for user in users:
    with st.container(border=True):
        cols = st.columns([2, 1, 1, 1, 1, 1])
        cols[0].markdown(f"**{user['username']}**")

        is_editor = cols[1].checkbox(
            "Éditeur·rice", value=user["is_editor"], key=f"editor_{user['id']}"
        )
        is_admin = cols[2].checkbox(
            "Admin", value=user["is_admin"], key=f"admin_{user['id']}"
        )

        role_changed = (is_editor != user["is_editor"]) or (is_admin != user["is_admin"])
        if cols[3].button("💾 Appliquer", key=f"apply_{user['id']}", disabled=not role_changed):
            if user["is_admin"] and not is_admin and db.count_admins() <= 1:
                st.error("Impossible de retirer le dernier compte administrateur.")
            else:
                db.set_user_role(user["id"], is_editor=is_editor, is_admin=is_admin)
                st.session_state["_flash_user_msg"] = f"Rôle de « {user['username']} » mis à jour."
                st.rerun()

        with cols[4].popover("🔑 Mot de passe"):
            new_pw = st.text_input(
                "Nouveau mot de passe", type="password", key=f"newpw_{user['id']}"
            )
            if st.button("Changer", key=f"changepw_{user['id']}"):
                if len(new_pw) < 6:
                    st.error("Le mot de passe doit contenir au moins 6 caractères.")
                else:
                    db.set_user_password(user["id"], new_pw)
                    st.session_state["_flash_user_msg"] = f"Mot de passe de « {user['username']} » modifié."
                    st.rerun()

        delete_disabled = user["is_admin"] and db.count_admins() <= 1
        if cols[5].button(
            "🗑️ Supprimer", key=f"deluser_{user['id']}", disabled=delete_disabled
        ):
            db.delete_user(user["id"])
            if auth.current_username() == user["username"]:
                auth.logout()
            st.session_state["_flash_user_msg"] = f"Compte « {user['username']} » supprimé."
            st.rerun()
        if delete_disabled:
            cols[5].caption("Dernier admin")
