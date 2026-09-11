"""
auth.py — Authentification via Auth0 (OpenID Connect), rôles gérés dans
notre propre base (db.py, table users).

Pourquoi ce changement (par rapport à l'ancien système identifiant/mot de
passe maison avec cookie "garde-moi connecté·e" posé en JavaScript) :

Ce cookie ne survivait pas de façon fiable à la fermeture du navigateur
sur Safari. Cause identifiée : la politique ITP (Intelligent Tracking
Prevention) d'Apple plafonne à 7 jours maximum — voire bloque totalement
selon le contexte — tout cookie posé via `document.cookie` en JavaScript,
quelle que soit la bibliothèque ou la technique utilisée pour l'écrire.
C'est une politique anti-tracking délibérée d'Apple, pas un bug
contournable côté code.

st.login() / st.user / st.logout() posent un cookie via un vrai en-tête
HTTP Set-Cookie envoyé par le SERVEUR Streamlit — jamais via JavaScript —
donc non soumis à cette limitation. C'est la seule méthode
d'authentification persistante que Streamlit supporte et maintient
nativement à ce jour (voir streamlit/streamlit#9421 : poser un cookie
depuis Python en dehors de ce mécanisme n'est toujours pas possible).

Le fournisseur OIDC utilisé est Auth0 — pas Google/Microsoft — avec sa
connexion "base de données" (email + mot de passe géré par Auth0), pour
rester indépendant des géants du numérique tout en profitant d'un vrai
cookie serveur, gratuit jusqu'à 25 000 utilisateur·rices actif·ves/mois.

Configuration requise (fichier .streamlit/secrets.toml en local, ou
section "Secrets" des réglages de l'app sur Streamlit Community Cloud) :

    [auth]
    redirect_uri = "https://votre-app.streamlit.app/oauth2callback"
    cookie_secret = "une longue chaîne aléatoire, générée une fois"
    client_id = "le Client ID de votre application Auth0"
    client_secret = "le Client Secret de votre application Auth0"
    server_metadata_url = "https://VOTRE-DOMAINE.auth0.com/.well-known/openid-configuration"

Compatibilité avec le reste de l'appli : TOUTES les fonctions publiques
ci-dessous gardent le même nom et le même comportement que dans l'ancienne
version (is_logged_in, is_admin, is_editor, can_manage_products,
current_username, current_user_id, render_sidebar_auth, require_editor,
require_admin, require_product_curator, require_login) — aucune autre
page de l'appli n'a besoin d'être modifiée suite à ce changement.

Vie privée — pseudo vs email : l'email Auth0 (st.user.email) sert
UNIQUEMENT à retrouver/créer le compte en base (db.get_or_create_user_by_
email), il n'est jamais affiché ni stocké comme identifiant public. Le
compte a un "pseudo" séparé (colonne `username` de la table users, dérivé
automatiquement de l'email à la création puis modifiable via l'interface
"✏️ Changer mon pseudo") — c'est ce pseudo, jamais l'email, qui apparaît
partout dans l'appli (sidebar, partage de menus, "ajouté par" sur les
recettes...). current_username() renvoie ce pseudo.
Déconnexion fédérée (Auth0) : st.logout() ne déconnecte que CookPotes —
Auth0 garde sa propre session active de son côté (deux sessions
distinctes). Sans traitement particulier, recliquer sur "Se connecter"
saute directement à l'écran de consentement Auth0 au lieu du vrai écran
de connexion/inscription. _auth0_logout_url() construit un lien qui
déconnecte D'ABORD Auth0 (son endpoint /v2/logout), qui redirige ENSUITE
vers CookPotes avec ?do_logout=1 — d'où Accueil.py appelle st.logout()
pour terminer la déconnexion côté CookPotes. Un seul clic, les deux
sessions sont bien terminées, dans le bon ordre.
"""

from __future__ import annotations

from urllib.parse import quote

import streamlit as st

import db


# ---------------------------------------------------------------------------
# État de connexion
# ---------------------------------------------------------------------------

def is_logged_in() -> bool:
    return bool(getattr(st.user, "is_logged_in", False))


def _current_role_info() -> dict:
    """
    Va chercher (ou crée, au tout premier login) le compte associé à
    l'email Auth0 courant dans notre base — voir
    db.get_or_create_user_by_email(). Le résultat est gardé en cache dans
    st.session_state pour la durée de la session : sans ça, chaque re-rendu
    de la sidebar (donc chaque interaction) referait un aller-retour vers
    Supabase juste pour connaître le rôle de la personne déjà connectée.
    """
    if not is_logged_in():
        return {}

    cache_key = "_auth_role_cache"
    cached = st.session_state.get(cache_key)
    if cached is not None and cached.get("_for_email") == st.user.email:
        return cached

    user = db.get_or_create_user_by_email(st.user.email)
    user = dict(user, _for_email=st.user.email)
    st.session_state[cache_key] = user
    return user


def is_editor() -> bool:
    return bool(_current_role_info().get("is_editor"))


def is_admin() -> bool:
    return bool(_current_role_info().get("is_admin"))


def can_manage_products() -> bool:
    """Droit de classer/corriger la base de produits d'épicerie (voir page « Produits »)."""
    return bool(_current_role_info().get("can_manage_products")) or is_admin()


def current_username() -> str | None:
    """
    Garde ce nom de fonction pour compatibilité avec le reste de l'appli,
    même si ça renvoie désormais l'email Auth0 — utilisé comme "username"
    partout où c'était déjà le cas (partage de menus, "ajouté par"...).
    """
    return _current_role_info().get("username")


def current_user_id() -> int | None:
    return _current_role_info().get("id")


def logout() -> None:
    """Déconnexion EXPLICITE : st.logout() supprime le cookie d'identité côté serveur et démarre une nouvelle session."""
    st.session_state.pop("_auth_role_cache", None)
    st.logout()


def _auth0_logout_url() -> str | None:
    """
    Construit l'URL de déconnexion fédérée Auth0 (/v2/logout) — voir
    docstring du module. Renvoie None si les secrets [auth] ne sont pas
    lisibles pour une raison quelconque (repli sur une simple déconnexion
    CookPotes dans ce cas, voir render_sidebar_auth).

    Important : l'URL de retour (returnTo) doit être ajoutée dans la liste
    "Allowed Logout URLs" des réglages de votre application, côté tableau
    de bord Auth0 — sinon Auth0 refuse la redirection.
    """
    try:
        auth_secrets = st.secrets["auth"]
        metadata_url = auth_secrets["server_metadata_url"]
        client_id = auth_secrets["client_id"]
        redirect_uri = auth_secrets["redirect_uri"]
    except Exception:
        return None

    # server_metadata_url ressemble à "https://VOTRE-DOMAINE.auth0.com/.well-known/openid-configuration"
    domain = metadata_url.split("://", 1)[-1].split("/", 1)[0]
    # redirect_uri ressemble à "https://votre-app.streamlit.app/oauth2callback"
    app_base_url = redirect_uri.rsplit("/oauth2callback", 1)[0]
    return_to = f"{app_base_url}/?do_logout=1"

    return (
        f"https://{domain}/v2/logout"
        f"?client_id={client_id}"
        f"&returnTo={quote(return_to, safe='')}"
    )


# ---------------------------------------------------------------------------
# Widgets d'interface
# ---------------------------------------------------------------------------

def render_sidebar_auth() -> None:
    """Affiche le statut de connexion, et le bouton de connexion/déconnexion, dans la sidebar."""
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

            # Priorité au pseudo (jamais l'email) — voir docstring du
            # module : l'attribut "name" fourni par Auth0 pour un compte
            # créé via la connexion base de données est souvent l'email
            # lui-même, donc à ne jamais utiliser en premier ici.
            display_name = current_username() or getattr(st.user, "name", None)
            st.success(f"Connecté : **{display_name}**  \nRôle : {role_label}")

            with st.popover("✏️ Changer mon pseudo", use_container_width=True):
                new_nickname = st.text_input(
                    "Nouveau pseudo", value=current_username() or "",
                    key="_auth_nickname_input",
                )
                if st.button("Enregistrer", key="_auth_nickname_save"):
                    if not new_nickname.strip():
                        st.error("Le pseudo ne peut pas être vide.")
                    else:
                        try:
                            db.update_username(current_user_id(), new_nickname)
                        except db.IntegrityError:
                            st.error(f"Le pseudo « {new_nickname.strip()} » est déjà pris.")
                        else:
                            st.session_state.pop("_auth_role_cache", None)
                            st.rerun()

            logout_url = _auth0_logout_url()
            if logout_url:
                # st.link_button() ouvre systématiquement un nouvel onglet
                # (non configurable) — inadapté ici : on veut au contraire
                # que tout l'enchaînement (Auth0 -> retour vers CookPotes,
                # voir docstring du module) se passe dans le MÊME onglet.
                # D'où un vrai lien HTML, stylé pour ressembler à un bouton
                # Streamlit, avec target="_self" explicite.
                st.markdown(
                    f"""
                    <a href="{logout_url}" target="_self" style="
                        display: block; text-align: center; text-decoration: none;
                        padding: 0.5em 1em; border-radius: 0.5em;
                        border: 1px solid rgba(49, 51, 63, 0.2);
                        background-color: rgb(255, 255, 255); color: rgb(49, 51, 63);
                        font-size: 1em; font-weight: 400; width: 100%;
                        box-sizing: border-box;">
                        Se déconnecter
                    </a>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                # Repli si les secrets [auth] ne sont pas lisibles : au
                # moins déconnecter côté CookPotes plutôt que de bloquer.
                if st.button("Se déconnecter", key="_auth_logout_btn", use_container_width=True):
                    logout()
        else:
            st.caption(
                "Connecte-toi pour ajouter des recettes et sauvegarder les "
                "menus que tu as composés."
            )
            if st.button(
                "Se connecter / créer un compte", key="_auth_login_btn",
                use_container_width=True, type="primary",
            ):
                st.login()


def require_editor(
    message: str = "🔒 Connecte-toi (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
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
    message: str = "🔒 Connecte-toi (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
) -> None:
    """
    À appeler tout en haut d'une page réservée aux personnes connectées,
    sans exigence de rôle particulier (éditeur/admin) — ex: « Mes menus »,
    une fonctionnalité ouverte à tout compte, y compris les lecteur·rices.
    """
    render_sidebar_auth()
    if not is_logged_in():
        st.warning(message)
        st.stop()
