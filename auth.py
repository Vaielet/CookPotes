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

import html
from urllib.parse import quote

import streamlit as st

import db

# Lien affiché en bas de la sidebar (voir render_sidebar_auth) — REMPLACEZ
# par l'URL de votre vrai formulaire (Google Forms, Tally, Typeform...).
FEEDBACK_FORM_URL = "https://framaforms.org/cookpotes-beta-test-1789234672"


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


def is_approved() -> bool:
    """
    Compte validé manuellement par un·e admin (voir "Gestion des
    utilisateur·rices"). Les admins sont toujours considéré·es validé·es
    (filet de sécurité — un·e admin ne doit jamais pouvoir se retrouver
    bloqué·e hors de sa propre app).
    """
    return bool(_current_role_info().get("is_approved")) or is_admin()


def current_username() -> str | None:
    """
    Garde ce nom de fonction pour compatibilité avec le reste de l'appli,
    même si ça renvoie désormais l'email Auth0 à l'origine — utilisé comme
    "username" partout où c'était déjà le cas ("ajouté par" sur les
    recettes, affichage dans la sidebar...). Pour le partage de menus,
    voir current_public_id() : un identifiant stable, pas ce pseudo
    librement modifiable.
    """
    return _current_role_info().get("username")


def current_public_id() -> str | None:
    """
    Identifiant unique et STABLE du compte (jamais modifiable, contrairement
    au pseudo) — voir db._generate_unique_public_id. C'est celui-ci qu'on
    communique à quelqu'un pour qu'iel partage un menu avec vous.
    """
    return _current_role_info().get("public_id")


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
            st.success(f"Connecté : **{display_name}**")

            with st.popover("🆔 Mon identifiant & pseudo", use_container_width=True):
                st.caption(
                    "Ton identifiant unique — communique-le à quelqu'un "
                    "pour qu'iel puisse partager un menu avec toi. Il ne "
                    "change jamais, contrairement à ton pseudo."
                )
                st.code(current_public_id() or "", language=None)

                st.divider()
                new_nickname = st.text_input(
                    "Ton pseudo (affiché partout dans l'appli, modifiable)",
                    value=current_username() or "",
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
                # Historique complet des tentatives "même onglet" (toutes
                # échouées, pour des raisons chaque fois différentes et
                # instructives) :
                #   1-2) <a> via st.markdown(), multi-lignes puis 1 ligne
                #        -> a fini par NAVIGUER correctement (donc pas un
                #        bug HTML), mais ouvre quand même un nouvel onglet.
                #   3)   <button onclick=window.top.location...> dans
                #        st.components.v1.html() -> ne fonctionne pas du
                #        tout (l'iframe du composant est sandboxée sans la
                #        permission de navigation du cadre parent).
                #   4)   <meta http-equiv="refresh"> via st.markdown() ->
                #        ne fonctionne pas du tout : un navigateur
                #        n'exécute PAS les balises meta-refresh (ni les
                #        <script>) injectées dynamiquement dans la page
                #        (innerHTML) — protection de sécurité du
                #        navigateur, aucun moyen de la contourner en HTML.
                #
                # Conclusion : le nouvel onglet des tentatives 1-2 n'était
                # pas un bug à corriger, mais très probablement un choix
                # délibéré de Streamlit lui-même — il intercepte les clics
                # sur un lien externe et force target="_blank", pour éviter
                # qu'un clic accidentel ne tue la session WebSocket active
                # en quittant la page. st.link_button fait la même chose,
                # par conception. On s'y tient : c'est fiable, et le
                # nouvel onglet est un choix de sécurité de Streamlit, pas
                # un défaut du code.
                st.link_button(
                    "Se déconnecter", logout_url,
                    use_container_width=True,
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

        # Toujours affiché (connecté·e ou non) : lien vers le formulaire
        # d'évaluation de l'app, tout en bas de la sidebar. Placé ici plutôt
        # que dans Accueil.py (où vit le reste du menu de navigation) : ce
        # bloc s'exécute sur CHAQUE page (render_sidebar_auth est appelée
        # par chaque page), donc c'est le seul endroit qui garantit que ce
        # lien apparaît systématiquement après connexion/déconnexion, peu
        # importe la page active.
        st.divider()
        st.link_button(
            "Donner mon avis sur l'appli", FEEDBACK_FORM_URL,
            use_container_width=True,
        )


APPROVAL_PENDING_MESSAGE = (
    "🔒 Ton compte est en attente de validation. Consulte la page "
    "« Comment ça marche ? » pour savoir comment obtenir un accès."
)


def require_editor(
    message: str = "🔒 Connecte-toi (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
) -> None:
    """
    À appeler tout en haut d'une page réservée aux éditeurs de recettes.
    Affiche la sidebar de connexion, et arrête l'exécution de la page si
    l'utilisateur n'est pas connecté avec le statut éditeur (ou admin), ou
    si son compte n'est pas encore validé.
    """
    render_sidebar_auth()
    if not (is_logged_in() and (is_editor() or is_admin())):
        st.warning(message)
        st.stop()
    if not is_approved():
        st.warning(APPROVAL_PENDING_MESSAGE)
        st.stop()


def require_admin(
    message: str = "🔒 Cette page est réservée aux administrateur·rices.",
) -> None:
    """À appeler tout en haut d'une page réservée aux administrateurs."""
    render_sidebar_auth()
    if not (is_logged_in() and is_admin()):
        st.warning(message)
        st.stop()
    if not is_approved():
        st.warning(APPROVAL_PENDING_MESSAGE)
        st.stop()


def require_product_curator(
    message: str = "🔒 Cette page est réservée aux comptes ayant le droit de gérer la base de produits.",
) -> None:
    """À appeler tout en haut d'une page réservée à la gestion de la base de produits."""
    render_sidebar_auth()
    if not (is_logged_in() and can_manage_products()):
        st.warning(message)
        st.stop()
    if not is_approved():
        st.warning(APPROVAL_PENDING_MESSAGE)
        st.stop()


def require_login(
    message: str = "🔒 Connecte-toi (menu de gauche) pour accéder à cette page — c'est gratuit et ça prend 10 secondes.",
) -> None:
    """
    À appeler tout en haut d'une page réservée aux personnes connectées ET
    validées, sans exigence de rôle particulier (éditeur/admin). Utilisée
    aussi bien pour les pages déjà réservées aux comptes (ex: « Mes
    menus ») que pour fermer une page auparavant ouverte à tout le monde
    sans connexion (ex: « Composer mon menu »), dans le cadre du passage
    en accès restreint à des comptes validés manuellement.
    """
    render_sidebar_auth()
    if not is_logged_in():
        st.warning(message)
        st.stop()
    if not is_approved():
        st.warning(APPROVAL_PENDING_MESSAGE)
        st.stop()
