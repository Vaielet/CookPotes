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

db.init_db()

#common.header_logo()

auth.require_admin()

common.icon_title("Gestion des utilisateur·rices", "gestion_utilisateurs.png", "👤")
st.caption(
    "Crée des comptes et attribue le statut « éditeur·rice » aux personnes "
    "autorisées à ajouter ou modifier des recettes. Seul·es les "
    "administrateur·rices voient cette page."
)

if st.session_state.get("_flash_user_msg"):
    st.success(st.session_state["_flash_user_msg"])
    st.session_state["_flash_user_msg"] = None


# ---------------------------------------------------------------------------
# Liste des utilisateurs existants
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Comptes existants")

users = db.list_users()

for user in users:
    with st.container(border=True):
        st.markdown(f"**{user['username']}**" + ("  ⏳ *En attente de validation*" if not user["is_approved"] else ""))

        # 1re ligne : les cases à cocher (rôles + validation) — un texte
        # entier par case, plus de colonnes trop étroites qui tronquaient
        # les libellés comme "Gestion produits" ou "En attente de validation".
        role_cols = st.columns(4)
        is_editor = role_cols[0].checkbox(
            "Éditeur·rice", value=user["is_editor"], key=f"editor_{user['id']}"
        )
        is_admin = role_cols[1].checkbox(
            "Admin", value=user["is_admin"], key=f"admin_{user['id']}"
        )
        can_manage_products = role_cols[2].checkbox(
            "Gestion produits", value=user["can_manage_products"], key=f"products_{user['id']}"
        )
        is_approved = role_cols[3].checkbox(
            "✅ Validé", value=user["is_approved"], key=f"approved_{user['id']}",
            help="Un compte non validé est bloqué sur toute l'app, sauf "
                 "« Accueil » et « Comment ça marche ? ».",
        )

        role_changed = (
            (is_editor != user["is_editor"])
            or (is_admin != user["is_admin"])
            or (can_manage_products != user["can_manage_products"])
            or (is_approved != user["is_approved"])
        )

        # 2e ligne : les actions — même logique, chacune dans sa propre
        # colonne plus large plutôt que serrées à côté des cases à cocher.
        action_cols = st.columns(3)
        if action_cols[0].button(
            "💾 Appliquer", key=f"apply_{user['id']}", disabled=not role_changed,
            use_container_width=True,
        ):
            if user["is_admin"] and not is_admin and db.count_admins() <= 1:
                st.error("Impossible de retirer le dernier compte administrateur.")
            else:
                db.set_user_role(
                    user["id"], is_editor=is_editor, is_admin=is_admin,
                    can_manage_products=can_manage_products,
                )
                db.set_user_approved(user["id"], is_approved)
                st.session_state["_flash_user_msg"] = f"Rôle de « {user['username']} » mis à jour."
                st.rerun()

        with action_cols[1].popover("🔑 Mot de passe", use_container_width=True):
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
        if action_cols[2].button(
            "🗑️ Supprimer", key=f"deluser_{user['id']}", disabled=delete_disabled,
            use_container_width=True,
        ):
            db.delete_user(user["id"])
            if auth.current_username() == user["username"]:
                auth.logout()
            st.session_state["_flash_user_msg"] = f"Compte « {user['username']} » supprimé."
            st.rerun()
        if delete_disabled:
            action_cols[2].caption("Dernier admin")
