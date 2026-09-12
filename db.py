"""
db.py — Couche d'accès à la base de données (PostgreSQL / Supabase, via SQLAlchemy).

Schéma :
- recipes      : une ligne par recette (nom, portions de base, photo,
                  description, temps de préparation/cuisson, auteur, dates)
- ingredients  : une ligne par ingrédient, rattaché à une recette et à une
                  section (ex: "Plat", "Sauce", "Accompagnement")
- instructions : une ligne par étape de préparation, rattachée à une recette
- recipe_tags  : catégories/tags d'une recette (ex: "Végétarien", "Sans gluten")
- users        : comptes utilisateurs (authentification + rôle éditeur/admin)

Pourquoi PostgreSQL/Supabase et pas SQLite ?
---------------------------------------------
Streamlit Community Cloud a un système de fichiers ÉPHÉMÈRE : tout fichier
écrit sur disque pendant l'exécution (comme l'était l'ancien "recettes.db")
disparaît à chaque redémarrage du conteneur (mise en veille après
inactivité, redéploiement, maintenance). Une base PostgreSQL hébergée sur
Supabase persiste réellement, que l'app tourne en local ou sur Streamlit
Cloud.

Configuration requise (fichier .streamlit/secrets.toml en local, ou
section "Secrets" des réglages de l'app sur Streamlit Cloud) :

    DATABASE_URL = "postgresql://postgres:motdepasse@host:5432/postgres"

C'est exactement l'URL de connexion fournie par Supabase (Project Settings
→ Database → Connection string), la même que celle utilisée dans le script
de test qui a validé cette connexion.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import streamlit as st
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

import common

# Exposé pour que les pages puissent faire `except db.IntegrityError` sans
# avoir à importer sqlalchemy elles-mêmes (garde l'abstraction dans ce module).
__all_exceptions__ = ["IntegrityError"]

# Identifiants du compte administrateur créé automatiquement s'il n'existe
# encore aucun utilisateur. À changer dès le premier lancement !
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

# Longueur maximale du petit texte de présentation d'une recette
# ("pourquoi on l'aime bien"). Doit correspondre à common.MAX_DESCRIPTION_CHARS.
MAX_DESCRIPTION_CHARS =  common.MAX_DESCRIPTION_CHARS

# ---------------------------------------------------------------------------
# Cache des lectures
# ---------------------------------------------------------------------------
#
# Streamlit ré-exécute TOUT le script à chaque interaction (case cochée,
# nombre de personnes modifié, clic sur un bouton...). Sans cache, ça
# signifie une nouvelle série de requêtes vers la base Postgres distante
# (Supabase) à chaque frappe/clic, ce qui domine largement le temps de
# réponse ressenti. @st.cache_data mémorise le résultat en mémoire process
# et ne refait la requête que si les données ont changé (invalidation
# explicite ci-dessous) ou après `ttl` secondes (filet de sécurité en cas
# de modification faite hors de l'appli, ex. directement dans Supabase).
_READ_CACHE_TTL = 600  # secondes


def _clear_recipe_caches() -> None:
    """À appeler après toute écriture qui change le contenu des recettes."""
    get_all_recipes.clear()
    get_recipe_names.clear()
    get_recipe_thumbnails.clear()
    get_all_tags.clear()
    get_all_authors.clear()
    get_recent_recipes.clear()


def _clear_user_caches() -> None:
    """À appeler après toute écriture qui change les comptes utilisateur·rices."""
    list_users.clear()


def _clear_product_caches() -> None:
    """À appeler après toute écriture sur la base de produits d'épicerie."""
    get_all_products.clear()


def _clear_saved_list_caches() -> None:
    """À appeler après toute écriture sur les listes de courses enregistrées."""
    get_saved_lists.clear()
    get_saved_list.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@st.cache_resource(show_spinner=False)
def _get_engine() -> Engine:
    """
    Crée (une seule fois, mise en cache par Streamlit) le moteur SQLAlchemy
    connecté à Supabase. pool_pre_ping=True évite les erreurs de connexion
    "cassée" après une période d'inactivité (comportement typique des bases
    cloud qui referment les connexions inactives).
    """
    try:
        database_url = st.secrets["DATABASE_URL"]
    except Exception:
        st.error(
            "🔌 Aucune base de données configurée. Ajoutez une clé "
            "`DATABASE_URL` dans `.streamlit/secrets.toml` (en local) ou "
            "dans les Secrets de l'app sur Streamlit Community Cloud, avec "
            "l'URL de connexion Postgres fournie par Supabase."
        )
        st.stop()
    return create_engine(database_url, pool_pre_ping=True)


@contextmanager
def get_conn():
    """
    Ouvre une connexion transactionnelle : commit automatique à la sortie
    du bloc `with`, rollback automatique en cas d'exception. Les lignes
    renvoyées par `.mappings()` sont accessibles comme des dicts (row["col"]).
    """
    with _get_engine().begin() as conn:
        yield conn


def get_backend_label() -> str:
    """Petit libellé lisible pour l'UI (ex: 'PostgreSQL — db.xxxx.supabase.co'), sans exposer les identifiants."""
    try:
        url = st.secrets["DATABASE_URL"]
        host = url.split("@")[-1].split("/")[0].split(":")[0]
        return f"PostgreSQL — {host}"
    except Exception:
        return "PostgreSQL"


@st.cache_resource(show_spinner=False)
def init_db() -> None:
    """
    Crée les tables si nécessaire, migre le schéma, et pré-remplit la base
    si elle est vide.

    Mise en cache avec @st.cache_resource : cette fonction est appelée en
    tête de CHAQUE page, donc à CHAQUE interaction (Streamlit relance tout
    le script à chaque clic). Sans ce cache, ses ~15 requêtes (CREATE
    TABLE, ALTER TABLE, SELECT COUNT...) partaient vers Supabase à chaque
    case cochée ou changement de nombre de personnes — c'est ce qui rendait
    l'appli lente au moindre clic. @st.cache_resource garantit qu'elle ne
    s'exécute réellement qu'une seule fois par démarrage du serveur
    (partagé entre tou·tes les utilisateur·rices, ce qui est le bon
    comportement : la création/migration du schéma n'a rien de propre à
    une session).
    """
    with get_conn() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS recipes (
                id             SERIAL PRIMARY KEY,
                name           TEXT UNIQUE NOT NULL,
                portions_base  INTEGER NOT NULL DEFAULT 1,
                image          BYTEA,
                image_mime     TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ingredients (
                id               SERIAL PRIMARY KEY,
                recipe_id        INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                section_name     TEXT NOT NULL DEFAULT 'Plat',
                ingredient_name  TEXT NOT NULL,
                quantity         REAL NOT NULL,
                unit             TEXT NOT NULL,
                position         INTEGER NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS instructions (
                id           SERIAL PRIMARY KEY,
                recipe_id    INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                step_number  INTEGER NOT NULL,
                text         TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS recipe_tags (
                id         SERIAL PRIMARY KEY,
                recipe_id  INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                tag        TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id             SERIAL PRIMARY KEY,
                username       TEXT UNIQUE NOT NULL,
                password_hash  TEXT NOT NULL,
                salt           TEXT NOT NULL,
                is_editor      BOOLEAN NOT NULL DEFAULT FALSE,
                is_admin       BOOLEAN NOT NULL DEFAULT FALSE,
                is_approved    BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS products (
                id         SERIAL PRIMARY KEY,
                canonical  TEXT UNIQUE NOT NULL,
                category   TEXT,
                synonyms   TEXT[] NOT NULL DEFAULT '{}'
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_shopping_lists (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                reference   TEXT,
                created_at  TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_shopping_list_recipes (
                id                     SERIAL PRIMARY KEY,
                list_id                INTEGER NOT NULL REFERENCES saved_shopping_lists(id) ON DELETE CASCADE,
                recipe_name            TEXT NOT NULL,
                people                 INTEGER NOT NULL,
                position               INTEGER NOT NULL DEFAULT 0,
                recipe_id              INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
                recipe_updated_at      TEXT,
                ingredients_snapshot   TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_shopping_list_items (
                id        SERIAL PRIMARY KEY,
                list_id   INTEGER NOT NULL REFERENCES saved_shopping_lists(id) ON DELETE CASCADE,
                category  TEXT NOT NULL,
                label     TEXT NOT NULL,
                checked   BOOLEAN NOT NULL DEFAULT FALSE,
                position  INTEGER NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_shopping_list_shares (
                id          SERIAL PRIMARY KEY,
                list_id     INTEGER NOT NULL REFERENCES saved_shopping_lists(id) ON DELETE CASCADE,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at  TEXT NOT NULL,
                UNIQUE (list_id, user_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS remember_tokens (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash  TEXT UNIQUE NOT NULL,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL
            )
        """))
    _migrate_schema()
    _seed_default_recipes_if_empty()
    _seed_default_admin_if_empty()
    _seed_default_products_if_empty()


def _derive_unique_nickname(conn, base: str) -> str:
    """
    Dérive un pseudo à partir d'une base (ex: la partie avant @ d'un
    email), en ne gardant que des caractères simples, et en garantissant
    l'unicité (insensible à la casse) face aux pseudos déjà pris — en
    ajoutant un suffixe numérique si besoin.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", base or "").strip("_-") or "cuisinier"
    candidate = cleaned
    suffix = 1
    while conn.execute(
        text("SELECT 1 FROM users WHERE LOWER(username) = LOWER(:u)"), {"u": candidate}
    ).first() is not None:
        suffix += 1
        candidate = f"{cleaned}{suffix}"
    return candidate


# Alphabet volontairement restreint aux caractères non ambigus à l'oreille
# ou à l'écrit (pas de 0/O, 1/I/L) — cet identifiant est fait pour être lu
# à voix haute ou recopié à la main pour le partage d'un menu.
_PUBLIC_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_PUBLIC_ID_LENGTH = 8


def _generate_unique_public_id(conn) -> str:
    """
    Identifiant unique et STABLE (jamais modifié une fois créé) pour un
    compte — voir auth.current_public_id() et db.get_user_by_public_id().
    Contrairement au pseudo (librement modifiable), c'est cet identifiant
    qu'on communique à quelqu'un pour qu'iel partage un menu avec vous :
    un pseudo qui change casserait silencieusement un partage basé dessus.

    8 caractères tirés d'un alphabet de 32 symboles nont-ambigus : plus de
    1000 milliards de combinaisons, collision avec un compte existant
    astronomiquement improbable — la boucle ci-dessous n'est qu'un filet
    de sécurité, pas un mécanisme réellement sollicité en pratique.
    """
    while True:
        candidate = "".join(secrets.choice(_PUBLIC_ID_ALPHABET) for _ in range(_PUBLIC_ID_LENGTH))
        exists = conn.execute(
            text("SELECT 1 FROM users WHERE public_id = :pid"), {"pid": candidate}
        ).first()
        if exists is None:
            return candidate


def _migrate_schema() -> None:
    """Ajoute les colonnes introduites après la version initiale, si absentes."""
    with get_conn() as conn:
        for column, sql_type in {
            "description": "TEXT",
            "prep_time_minutes": "INTEGER",
            "cook_time_minutes": "INTEGER",
            "created_by": "TEXT",
            "created_at": "TEXT",
            "updated_by": "TEXT",
            "updated_at": "TEXT",
        }.items():
            conn.execute(text(f"ALTER TABLE recipes ADD COLUMN IF NOT EXISTS {column} {sql_type}"))

        # Les recettes déjà présentes (créées avant cette migration) n'ont
        # pas de date de création : on leur en attribue une pour qu'elles
        # apparaissent correctement triées dans "dernières recettes ajoutées".
        conn.execute(
            text("UPDATE recipes SET created_at = :now WHERE created_at IS NULL"),
            {"now": _now_iso()},
        )

        # Nouveau rôle "gestion des produits" (voir set_user_role / auth.py) :
        # peut classer/corriger la base de produits d'épicerie, sans avoir
        # besoin d'être administrateur·rice.
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_manage_products BOOLEAN NOT NULL DEFAULT FALSE"
        ))

        # La table `products` exigeait initialement un rayon (category) non
        # nul. On l'assouplit : un produit peut désormais exister "en
        # attente de classement" (category NULL), typiquement enregistré à
        # la volée depuis la page "Ajouter une recette" quand un ingrédient
        # inconnu est tapé. Pas d'effet si déjà migré (IF EXISTS-like via
        # un DO simple, silencieux si la contrainte n'existe plus).
        conn.execute(text("ALTER TABLE products ALTER COLUMN category DROP NOT NULL"))

        # Passage à Auth0 (st.login()) : `username` servait jusqu'ici à la
        # fois d'identifiant technique (= l'email Auth0) ET de nom affiché
        # partout dans l'appli (partage de menus, "ajouté par"...). On
        # sépare les deux : `email` devient la clé technique interne, JAMAIS
        # affichée, et `username` redevient un pseudo librement choisi.
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT"))
        conn.execute(
            text("UPDATE users SET email = username WHERE email IS NULL")
        )
        # Unicité insensible à la casse sur l'email (comme pour username),
        # via un index plutôt qu'une contrainte : CREATE ... IF NOT EXISTS
        # est idempotent nativement en PostgreSQL, contrairement à ADD
        # CONSTRAINT qui n'a pas d'équivalent "IF NOT EXISTS" propre.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique_idx
            ON users (LOWER(email)) WHERE email IS NOT NULL
        """))

        # Comptes créés AVANT cette migration : leur pseudo est encore leur
        # email en clair (comportement de l'ancien système). On leur
        # attribue automatiquement un pseudo dérivé, pour que l'email cesse
        # d'apparaître dans l'appli dès cette migration, sans action requise
        # de leur part (ils pourront toujours le personnaliser ensuite).
        stale_rows = conn.execute(
            text("SELECT id, username FROM users WHERE username = email")
        ).mappings().all()
        for row in stale_rows:
            base = row["username"].split("@")[0] if "@" in row["username"] else row["username"]
            nickname = _derive_unique_nickname(conn, base)
            conn.execute(
                text("UPDATE users SET username = :nickname WHERE id = :id"),
                {"nickname": nickname, "id": row["id"]},
            )

        # Unicité insensible à la casse sur `username` lui-même : la
        # contrainte d'origine (colonne UNIQUE, voir CREATE TABLE plus haut)
        # est sensible à la casse, alors que TOUTE la logique applicative
        # (recherche de compte pour le partage, dérivation automatique de
        # pseudo ci-dessus, etc.) raisonne de façon insensible à la casse.
        # Sans cet index, rien n'empêchait au niveau base deux comptes
        # "Bob" et "bob" de coexister, ce qui aurait pu semer la confusion
        # au partage d'un menu ou dans l'attribution des recettes.
        #
        # Si cette création échoue avec une erreur de type "duplicated key"
        # (UniqueViolation), c'est qu'un tel doublon existe déjà en base :
        # même correctif que pour users_email_unique_idx plus haut — une
        # requête SELECT id, username FROM users WHERE LOWER(username) =
        # LOWER('le-pseudo-en-double') pour identifier les deux comptes,
        # puis DELETE FROM users WHERE id = <celui à retirer>.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS users_username_ci_unique_idx
            ON users (LOWER(username))
        """))

        # Accès restreint à des comptes validés manuellement : chaque
        # nouveau compte auto-créé via Auth0 (get_or_create_user_by_email)
        # démarre désormais "non validé" (is_approved = FALSE), et reste
        # bloqué partout sauf "Accueil"/"Comment ça marche" tant qu'un·e
        # admin ne l'a pas validé depuis "Gestion des utilisateur·rices".
        #
        # ATTENTION à l'ordre des deux instructions ci-dessous : on vérifie
        # D'ABORD si la colonne existe déjà, puis on ne fait le rattrapage
        # "tout le monde déjà présent est considéré validé" QUE si elle
        # vient tout juste d'être créée (première fois que cette migration
        # tourne). Sans cette précaution, exécuter le rattrapage à CHAQUE
        # démarrage aurait validé automatiquement n'importe quel compte
        # réellement en attente au prochain redémarrage/redéploiement de
        # l'app — annulant complètement l'intérêt de cette fonctionnalité.
        column_already_existed = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'is_approved'"
        )).first() is not None

        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT FALSE"
        ))

        if not column_already_existed:
            # Première fois : tous les comptes déjà présents utilisaient
            # l'app avant l'introduction de cette validation manuelle — on
            # les considère donc déjà validés, pour ne pas se retrouver
            # bloqué·e hors de sa propre app (y compris le compte admin).
            conn.execute(text("UPDATE users SET is_approved = TRUE"))

        # Détection "recette modifiée depuis l'enregistrement d'un menu"
        # (plutôt que faussement "supprimée") : chaque recette d'un menu
        # enregistré garde désormais un lien vers son id réel, la date de
        # dernière modification de la recette au moment de la sauvegarde,
        # et un instantané JSON de ses ingrédients (déjà mis à l'échelle,
        # au format canonique — voir common.scaled_ingredient_rows).
        conn.execute(text(
            "ALTER TABLE saved_shopping_list_recipes ADD COLUMN IF NOT EXISTS recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL"
        ))
        conn.execute(text(
            "ALTER TABLE saved_shopping_list_recipes ADD COLUMN IF NOT EXISTS recipe_updated_at TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE saved_shopping_list_recipes ADD COLUMN IF NOT EXISTS ingredients_snapshot TEXT"
        ))

        # Rattrapage pour les menus déjà enregistrés avant cette migration :
        # on retrouve recipe_id par correspondance de NOM (la seule info
        # qu'on avait à l'époque). Si le nom a depuis changé, ce
        # rattrapage ne peut rien pour cette ligne précise (recipe_id
        # reste NULL, donc traitée comme "supprimée" jusqu'à ce que le
        # menu soit régénéré) — mais toute recette pas encore renommée
        # au moment de cette migration retrouve son lien stable. Pas
        # d'instantané d'ingrédients possible rétroactivement (on ne sait
        # plus quels ingrédients existaient à l'époque) : ces menus ne
        # pourront pas afficher le détail "qu'est-ce qui a changé",
        # seulement l'état actuel une fois le lien recipe_id retrouvé.
        conn.execute(text("""
            UPDATE saved_shopping_list_recipes AS sslr
            SET recipe_id = r.id
            FROM recipes r
            WHERE sslr.recipe_id IS NULL AND sslr.recipe_name = r.name
        """))

        # Identifiant unique et stable par compte (voir _generate_unique_
        # public_id, auth.current_public_id, get_user_by_public_id) — sert
        # de base fiable pour le partage d'un menu, indépendante du pseudo
        # (librement modifiable). Colonne nullable dans un premier temps
        # (impossible de mettre UNIQUE NOT NULL directement sur une colonne
        # qu'on vient d'ajouter à une table déjà peuplée), remplie ligne
        # par ligne juste après, puis vraiment contrainte "NOT NULL".
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS public_id TEXT"))

        rows_without_public_id = conn.execute(
            text("SELECT id FROM users WHERE public_id IS NULL")
        ).mappings().all()
        for row in rows_without_public_id:
            new_public_id = _generate_unique_public_id(conn)
            conn.execute(
                text("UPDATE users SET public_id = :pid WHERE id = :id"),
                {"pid": new_public_id, "id": row["id"]},
            )

        conn.execute(text("ALTER TABLE users ALTER COLUMN public_id SET NOT NULL"))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS users_public_id_unique_idx
            ON users (public_id)
        """))


def _seed_default_recipes_if_empty() -> None:
    with get_conn() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM recipes")).scalar()
    if count > 0:
        return

    seed = {
        "Spaghettis à la crème de courgette": {
            "portions_base": 1,
            "ingredients": {
                "Plat": [
                    ("spaghetti", 60, "g"),
                    ("courgette", 125, "g"),
                    ("huile d'olive", 1, "cac"),
                    ("ail", 0.5, "gousse"),
                    ("crème de soja", 3, "cas"),
                    ("basilic frais", 4, "feuilles"),
                    ("fromage de chèvre frais", 50, "g"),
                    ("jambon", 80, "g"),
                    ("olives vertes", 20, "g"),
                ]
            },
            "instructions": [
                "Épluchez la courgette et coupez-la en cubes. Faites cuire dans une poêle avec l'huile d'olive et l'ail émincé.",
                "Dans un mixeur, placez la courgette, l'ail, la crème, du sel, du poivre et le basilic. Mixez jusqu'à l'obtention d'une texture homogène.",
                "Faites cuire les spaghettis dans une casserole d'eau bouillante salée, selon les indications du paquet.",
                "Dans une assiette, placez les spaghettis cuits avec la crème de courgette, le fromage de chèvre, le jambon et les olives. Bon appétit !",
            ],
        },
        "Bouchées au saumon": {
            "portions_base": 3,
            "ingredients": {
                "Plat": [
                    ("saumon", 250, "g"),
                    ("chapelure", 30, "g"),
                    ("ail en poudre", 2, "cac"),
                    ("herbes italiennes sèchées", 2, "cac"),
                    ("paprika doux", 1, "cas"),
                    ("sel", 2, "cac"),
                    ("huile d'olive", 1, "cas"),
                    ("sauce piquante", 1, "cas"),
                    ("miel", 50, "ml"),
                ],
                "Sauce": [
                    ("yaourt grec nature", 125, "ml"),
                    ("mayonnaise allégée", 4, "cas"),
                    ("piment", 1, "pièce"),
                    ("ail", 1, "gousse"),
                    ("citron vert", 1, "pièce"),
                    ("huile d'olive", 1, "cas"),
                    ("miel", 1, "cas"),
                ],
                "Accompagnement": [
                    ("poireaux", 250, "g"),
                    ("champignons", 150, "g"),
                    ("oignon", 40, "g"),
                    ("huile d'olive", 1, "cac"),
                    ("riz à risotto", 100, "g"),
                    ("bouillon de légumes", 1, "cube"),
                    ("parmesan", 20, "g"),
                    ("persil", 4, "brins"),
                ],
            },
            "instructions": [
                "Dans un récipient hermétique, mélangez la chapelure avec les épices. Coupez le saumon en morceaux puis ajoutez-le dans le récipient. Fermez et secouez afin que chaque morceau soit bien recouvert de chapelure assaisonnée.",
                "Au four, faites cuire à 220 °C (th. 7-8) pendant 10 à 15 minutes.",
                "Dans un bol, mélangez le miel et la sauce piquante. Ajoutez les bouchées de saumon encore chaudes et mélangez délicatement pour bien les enrober.",
            ],
        },
    }

    for name, data in seed.items():
        add_recipe(
            name=name,
            portions_base=data["portions_base"],
            image_bytes=None,
            image_mime=None,
            sections=data["ingredients"],
            instructions=data["instructions"],
            tags=data.get("tags", []),
            description=data.get("description", ""),
            prep_time_minutes=data.get("prep_time_minutes"),
            cook_time_minutes=data.get("cook_time_minutes"),
            created_by="admin",
        )


def _seed_default_products_if_empty() -> None:
    """
    Copie la petite liste `common.PRODUCTS` dans la table `products` au
    tout premier lancement (table vide). Ensuite, c'est cette table sur
    Supabase qui fait foi — voir `scripts/add_products.py` pour continuer
    à l'alimenter.
    """
    with get_conn() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
    if count > 0:
        return

    with get_conn() as conn:
        for product in common.PRODUCTS:
            conn.execute(
                text("""
                    INSERT INTO products (canonical, category, synonyms)
                    VALUES (:canonical, :category, :synonyms)
                    ON CONFLICT (canonical) DO NOTHING
                """),
                {
                    "canonical": product["canonical"],
                    "category": product["category"],
                    "synonyms": product["synonyms"],
                },
            )


def add_recipe(
    name: str,
    portions_base: int,
    image_bytes: bytes | None,
    image_mime: str | None,
    sections: dict[str, list[tuple[str, float, str]]],
    instructions: list[str],
    tags: list[str] | None = None,
    description: str = "",
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    created_by: str | None = None,
) -> int:
    """Ajoute une nouvelle recette. Lève db.IntegrityError si le nom existe déjà."""
    now = _now_iso()
    description = (description or "")[:MAX_DESCRIPTION_CHARS]
    if image_bytes:
        try:
            image_bytes, image_mime = common.prepare_image_for_storage(image_bytes)
        except Exception:
            pass  # Photo illisible : on la stocke telle quelle plutôt que de bloquer l'ajout.
    with get_conn() as conn:
        recipe_id = conn.execute(
            text("""
                INSERT INTO recipes
                   (name, portions_base, image, image_mime, description,
                    prep_time_minutes, cook_time_minutes, created_by, created_at,
                    updated_by, updated_at)
                VALUES (:name, :portions_base, :image, :image_mime, :description,
                        :prep_time_minutes, :cook_time_minutes, :created_by, :now,
                        :created_by, :now)
                RETURNING id
            """),
            {
                "name": name, "portions_base": portions_base, "image": image_bytes,
                "image_mime": image_mime, "description": description,
                "prep_time_minutes": prep_time_minutes, "cook_time_minutes": cook_time_minutes,
                "created_by": created_by, "now": now,
            },
        ).scalar()

        position = 0
        for section_name, rows in sections.items():
            for ingredient_name, qty, unit in rows:
                conn.execute(
                    text("""
                        INSERT INTO ingredients
                           (recipe_id, section_name, ingredient_name, quantity, unit, position)
                        VALUES (:recipe_id, :section_name, :ingredient_name, :quantity, :unit, :position)
                    """),
                    {
                        "recipe_id": recipe_id, "section_name": section_name,
                        "ingredient_name": ingredient_name, "quantity": float(qty),
                        "unit": unit, "position": position,
                    },
                )
                position += 1

        for step_number, step_text in enumerate(instructions, start=1):
            conn.execute(
                text("INSERT INTO instructions (recipe_id, step_number, text) VALUES (:recipe_id, :step_number, :text)"),
                {"recipe_id": recipe_id, "step_number": step_number, "text": step_text},
            )

        for tag in _dedupe_tags(tags):
            conn.execute(
                text("INSERT INTO recipe_tags (recipe_id, tag) VALUES (:recipe_id, :tag)"),
                {"recipe_id": recipe_id, "tag": tag},
            )

    _clear_recipe_caches()
    return recipe_id


def delete_recipe(recipe_id: int) -> None:
    with get_conn() as conn:
        conn.execute(text("DELETE FROM recipes WHERE id = :id"), {"id": recipe_id})
    _clear_recipe_caches()


def update_recipe(
    recipe_id: int,
    name: str,
    portions_base: int,
    image_bytes: bytes | None,
    image_mime: str | None,
    sections: dict[str, list[tuple[str, float, str]]],
    instructions: list[str],
    tags: list[str] | None = None,
    description: str = "",
    prep_time_minutes: int | None = None,
    cook_time_minutes: int | None = None,
    updated_by: str | None = None,
) -> None:
    """
    Remplace le contenu d'une recette existante (nom, portions, photo,
    ingrédients, instructions, catégories, description, temps). Le créateur
    et la date de création d'origine sont conservés ; seuls updated_by /
    updated_at sont rafraîchis. Lève db.IntegrityError si le nouveau nom
    est déjà utilisé par une AUTRE recette.
    """
    description = (description or "")[:MAX_DESCRIPTION_CHARS]
    if image_bytes:
        try:
            image_bytes, image_mime = common.prepare_image_for_storage(image_bytes)
        except Exception:
            pass  # Photo illisible : on la stocke telle quelle plutôt que de bloquer la modification.
    with get_conn() as conn:
        conn.execute(
            text("""
                UPDATE recipes
                SET name = :name, portions_base = :portions_base, image = :image,
                    image_mime = :image_mime, description = :description,
                    prep_time_minutes = :prep_time_minutes, cook_time_minutes = :cook_time_minutes,
                    updated_by = :updated_by, updated_at = :updated_at
                WHERE id = :id
            """),
            {
                "name": name, "portions_base": portions_base, "image": image_bytes,
                "image_mime": image_mime, "description": description,
                "prep_time_minutes": prep_time_minutes, "cook_time_minutes": cook_time_minutes,
                "updated_by": updated_by, "updated_at": _now_iso(), "id": recipe_id,
            },
        )
        conn.execute(text("DELETE FROM ingredients WHERE recipe_id = :id"), {"id": recipe_id})
        conn.execute(text("DELETE FROM instructions WHERE recipe_id = :id"), {"id": recipe_id})
        conn.execute(text("DELETE FROM recipe_tags WHERE recipe_id = :id"), {"id": recipe_id})

        position = 0
        for section_name, rows in sections.items():
            for ingredient_name, qty, unit in rows:
                conn.execute(
                    text("""
                        INSERT INTO ingredients
                           (recipe_id, section_name, ingredient_name, quantity, unit, position)
                        VALUES (:recipe_id, :section_name, :ingredient_name, :quantity, :unit, :position)
                    """),
                    {
                        "recipe_id": recipe_id, "section_name": section_name,
                        "ingredient_name": ingredient_name, "quantity": float(qty),
                        "unit": unit, "position": position,
                    },
                )
                position += 1

        for step_number, step_text in enumerate(instructions, start=1):
            conn.execute(
                text("INSERT INTO instructions (recipe_id, step_number, text) VALUES (:recipe_id, :step_number, :text)"),
                {"recipe_id": recipe_id, "step_number": step_number, "text": step_text},
            )

        for tag in _dedupe_tags(tags):
            conn.execute(
                text("INSERT INTO recipe_tags (recipe_id, tag) VALUES (:recipe_id, :tag)"),
                {"recipe_id": recipe_id, "tag": tag},
            )

    _clear_recipe_caches()


def _dedupe_tags(tags: list[str] | None) -> list[str]:
    """Nettoie et déduplique une liste de tags en conservant l'ordre."""
    seen = set()
    result = []
    for tag in (tags or []):
        cleaned = tag.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _image_bytes(value) -> bytes | None:
    """Convertit une valeur BYTEA renvoyée par le driver (souvent un memoryview) en bytes classiques, ou None."""
    if value is None:
        return None
    return bytes(value)


def get_recipe_by_id(recipe_id: int) -> dict | None:
    """Retourne une recette unique (même structure que les valeurs de get_all_recipes()), ou None."""
    with get_conn() as conn:
        r = conn.execute(
            text("SELECT * FROM recipes WHERE id = :id"), {"id": recipe_id}
        ).mappings().first()
        if r is None:
            return None

        ingredient_rows = conn.execute(
            text("SELECT * FROM ingredients WHERE recipe_id = :id ORDER BY position"),
            {"id": recipe_id},
        ).mappings().all()
        sections: dict[str, list[tuple[str, float, str]]] = {}
        for row in ingredient_rows:
            sections.setdefault(row["section_name"], []).append(
                (row["ingredient_name"], row["quantity"], row["unit"])
            )

        instruction_rows = conn.execute(
            text("SELECT text FROM instructions WHERE recipe_id = :id ORDER BY step_number"),
            {"id": recipe_id},
        ).mappings().all()
        instructions = [row["text"] for row in instruction_rows]

        tag_rows = conn.execute(
            text("SELECT tag FROM recipe_tags WHERE recipe_id = :id ORDER BY id"),
            {"id": recipe_id},
        ).mappings().all()
        tags = [row["tag"] for row in tag_rows]

        return {
            "id": r["id"],
            "name": r["name"],
            "portions_base": r["portions_base"],
            "image": _image_bytes(r["image"]),
            "image_mime": r["image_mime"],
            "ingredients": sections,
            "instructions": instructions,
            "tags": tags,
            "description": r["description"] or "",
            "prep_time_minutes": r["prep_time_minutes"],
            "cook_time_minutes": r["cook_time_minutes"],
            "created_by": r["created_by"],
            "created_at": r["created_at"],
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"],
        }


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_all_tags() -> list[str]:
    """Retourne la liste triée de toutes les catégories utilisées par au moins une recette."""
    with get_conn() as conn:
        rows = conn.execute(text("""
            SELECT tag FROM (SELECT DISTINCT tag FROM recipe_tags) AS t
            ORDER BY LOWER(tag)
        """)).mappings().all()
        return [row["tag"] for row in rows]


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_all_authors() -> list[str]:
    """Retourne la liste triée des auteurs (created_by) ayant au moins une recette à leur nom."""
    with get_conn() as conn:
        rows = conn.execute(text("""
            SELECT created_by FROM (
                SELECT DISTINCT created_by FROM recipes
                WHERE created_by IS NOT NULL AND created_by != ''
            ) AS a
            ORDER BY LOWER(created_by)
        """)).mappings().all()
        return [row["created_by"] for row in rows]


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_recipe_thumbnails(names: tuple[str, ...]) -> dict[str, bytes | None]:
    """
    Charge uniquement les photos (pas les ingrédients, pas les
    instructions) des recettes dont le nom figure dans `names`. À utiliser
    à la place de `get_all_recipes()` quand on veut juste afficher des
    vignettes pour un petit sous-ensemble de recettes (ex : les recettes
    d'une liste de courses) — `get_all_recipes()` chargerait en comparaison
    TOUT le contenu de TOUTES les recettes de l'appli.
    """
    if not names:
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            text("SELECT name, image FROM recipes WHERE name IN :names")
            .bindparams(bindparam("names", expanding=True)),
            {"names": list(names)},
        ).mappings().all()
    return {row["name"]: _image_bytes(row["image"]) for row in rows}


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_recipe_names() -> set[str]:
    """
    Juste l'ensemble des noms de recettes existantes — ni photos, ni
    ingrédients. À utiliser à la place de `get_all_recipes()` quand on a
    seulement besoin de savoir si une recette existe encore (ex : page
    « Mes listes », qui réexécute tout le script à chaque case cochée —
    charger toutes les photos à chaque fois y créait un ralentissement
    perceptible pour rien).
    """
    with get_conn() as conn:
        rows = conn.execute(text("SELECT name FROM recipes")).mappings().all()
        return {row["name"] for row in rows}


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_all_recipes() -> dict:
    """
    Retourne un dict {nom_recette: {...}} avec pour chaque recette :
    id, portions_base, image (bytes ou None), image_mime, ingredients
    (dict {section: [(nom, qty, unité), ...]}), instructions (liste de str),
    tags (liste de str), description, prep_time_minutes, cook_time_minutes,
    created_by, created_at, updated_by, updated_at.

    Résultat mis en cache (voir `_clear_recipe_caches`) : sans ça, cette
    fonction faisait 1 + 3×N requêtes (N = nombre de recettes) à chaque
    rechargement de page — un aller-retour réseau par recette. Elle ne fait
    maintenant que 4 requêtes au total, quel que soit le nombre de recettes,
    en récupérant tous les ingrédients / instructions / tags en une seule
    fois puis en les répartissant en mémoire.
    """
    result: dict = {}
    with get_conn() as conn:
        recipe_rows = conn.execute(text("SELECT * FROM recipes ORDER BY LOWER(name)")).mappings().all()
        if not recipe_rows:
            return result

        recipe_ids = [r["id"] for r in recipe_rows]

        ingredients_stmt = text(
            "SELECT * FROM ingredients WHERE recipe_id IN :ids ORDER BY recipe_id, position"
        ).bindparams(bindparam("ids", expanding=True))
        instructions_stmt = text(
            "SELECT * FROM instructions WHERE recipe_id IN :ids ORDER BY recipe_id, step_number"
        ).bindparams(bindparam("ids", expanding=True))
        tags_stmt = text(
            "SELECT * FROM recipe_tags WHERE recipe_id IN :ids ORDER BY recipe_id, id"
        ).bindparams(bindparam("ids", expanding=True))

        ingredient_rows = conn.execute(ingredients_stmt, {"ids": recipe_ids}).mappings().all()
        instruction_rows = conn.execute(instructions_stmt, {"ids": recipe_ids}).mappings().all()
        tag_rows = conn.execute(tags_stmt, {"ids": recipe_ids}).mappings().all()

        sections_by_recipe: dict[int, dict[str, list[tuple[str, float, str]]]] = {}
        for row in ingredient_rows:
            sections = sections_by_recipe.setdefault(row["recipe_id"], {})
            sections.setdefault(row["section_name"], []).append(
                (row["ingredient_name"], row["quantity"], row["unit"])
            )

        instructions_by_recipe: dict[int, list[str]] = {}
        for row in instruction_rows:
            instructions_by_recipe.setdefault(row["recipe_id"], []).append(row["text"])

        tags_by_recipe: dict[int, list[str]] = {}
        for row in tag_rows:
            tags_by_recipe.setdefault(row["recipe_id"], []).append(row["tag"])

        for r in recipe_rows:
            result[r["name"]] = {
                "id": r["id"],
                "portions_base": r["portions_base"],
                "image": _image_bytes(r["image"]),
                "image_mime": r["image_mime"],
                "ingredients": sections_by_recipe.get(r["id"], {}),
                "instructions": instructions_by_recipe.get(r["id"], []),
                "tags": tags_by_recipe.get(r["id"], []),
                "description": r["description"] or "",
                "prep_time_minutes": r["prep_time_minutes"],
                "cook_time_minutes": r["cook_time_minutes"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
                "updated_by": r["updated_by"],
                "updated_at": r["updated_at"],
            }

    return result


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_recent_recipes(limit: int = 5) -> list[dict]:
    """
    Retourne les `limit` recettes les plus récemment créées (par created_at
    décroissant), sous forme de liste de dicts légers — pratique pour un
    aperçu "dernières recettes ajoutées" sans charger tous les ingrédients.
    """
    with get_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id, name, portions_base, image, created_by, created_at
                FROM recipes
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "portions_base": row["portions_base"],
            "image": _image_bytes(row["image"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Utilisateurs / authentification
# ---------------------------------------------------------------------------
#
# Les mots de passe ne sont jamais stockés en clair : on garde uniquement un
# hash PBKDF2-HMAC-SHA256 salé. Ce n'est pas un système d'authentification
# de niveau entreprise (pas de verrouillage anti brute-force, pas de
# rotation de session persistante entre rechargements complets du
# navigateur — limitation propre à Streamlit), mais c'est raisonnable pour
# une application interne à usage restreint.

_PBKDF2_ITERATIONS = 100_000


def _hash_password(
    password: str,
    salt: bytes | None = None
) -> tuple[str, str]:

    if salt is None:
        salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )

    return digest.hex(), salt.hex()


def _seed_default_admin_if_empty() -> None:
    with get_conn() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if count > 0:
        return
    create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, is_editor=True, is_admin=True)


def create_user(
    username: str,
    password: str,
    is_editor: bool = False,
    is_admin: bool = False,
    can_manage_products: bool = False,
    is_approved: bool = True,
) -> int:
    """
    Crée un nouvel utilisateur. `is_approved=True` par défaut ici : un
    compte créé directement par un·e admin depuis "Gestion des
    utilisateur·rices" est par nature déjà validé par cet acte (contexte
    différent de get_or_create_user_by_email, où l'auto-inscription via
    Auth0 démarre elle NON validée).
    """

    digest_hex, salt_hex = _hash_password(password)

    with get_conn() as conn:
        public_id = _generate_unique_public_id(conn)
        new_id = conn.execute(
            text("""
                INSERT INTO users
                (username, password_hash, salt, is_editor, is_admin, can_manage_products, is_approved, public_id)
                VALUES
                (:username, :password_hash, :salt, :is_editor, :is_admin, :can_manage_products, :is_approved, :public_id)
                RETURNING id
            """),
            {
                "username": username.strip(),
                "password_hash": digest_hex,
                "salt": salt_hex,
                "is_editor": bool(is_editor),
                "is_admin": bool(is_admin),
                "can_manage_products": bool(can_manage_products),
                "is_approved": bool(is_approved),
                "public_id": public_id,
            },
        ).scalar()
    _clear_user_caches()
    return new_id


def verify_credentials(
    username: str,
    password: str
) -> dict | None:
    """Vérifie un couple identifiant/mot de passe."""

    with get_conn() as conn:
        row = conn.execute(
            text("""
                SELECT *
                FROM users
                WHERE username = :username
            """),
            {"username": username.strip()},
        ).mappings().first()

    if row is None:
        return None

    salt_bytes = bytes.fromhex(row["salt"])

    candidate_hash, _ = _hash_password(
        password,
        salt_bytes
    )

    if not secrets.compare_digest(
        candidate_hash,
        row["password_hash"]
    ):
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "is_editor": bool(row["is_editor"]),
        "is_admin": bool(row["is_admin"]),
        "can_manage_products": bool(row["can_manage_products"]),
        "is_approved": bool(row["is_approved"]),
        "public_id": row["public_id"],
    }


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            text("SELECT id, username, is_editor, is_admin, can_manage_products, is_approved, public_id FROM users ORDER BY LOWER(username)")
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "username": r["username"],
            "is_editor": bool(r["is_editor"]),
            "is_admin": bool(r["is_admin"]),
            "can_manage_products": bool(r["can_manage_products"]),
            "is_approved": bool(r["is_approved"]),
            "public_id": r["public_id"],
        }
        for r in rows
    ]


def get_user_by_username(username: str) -> dict | None:
    """
    Recherche insensible à la casse (pratique pour le partage : on ne veut
    pas qu'une différence de majuscule empêche de retrouver un compte).
    Renvoie None si aucun compte ne correspond.
    """
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT id, username FROM users WHERE LOWER(username) = LOWER(:username)"),
            {"username": (username or "").strip()},
        ).mappings().first()
    return {"id": row["id"], "username": row["username"]} if row else None


def get_user_by_public_id(public_id: str) -> dict | None:
    """
    Retrouve un compte par son identifiant unique et stable (voir
    _generate_unique_public_id) — c'est celui-ci qui sert de base fiable
    au partage d'un menu, contrairement au pseudo (librement modifiable).
    Insensible à la casse et aux espaces superflus, par tolérance à la
    recopie manuelle (l'identifiant est généré en majuscules, mais autant
    ne pas bloquer si la casse ne correspond pas exactement).
    """
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT id, username, public_id FROM users WHERE UPPER(public_id) = UPPER(:pid)"),
            {"pid": (public_id or "").strip()},
        ).mappings().first()
    return {"id": row["id"], "username": row["username"], "public_id": row["public_id"]} if row else None


def get_or_create_user_by_email(email: str) -> dict:
    """
    Authentification via Auth0 (st.login(), voir auth.py) : retrouve le
    compte associé à cet email (colonne `email`, interne — jamais
    affichée) ou en crée un nouveau à la volée au tout premier login.

    `is_approved=FALSE` pour tout nouveau compte : l'app est restreinte
    aux comptes validés manuellement (voir auth.is_approved, et la page
    "Gestion des utilisateur·rices" pour valider un compte) — un compte
    tout juste auto-créé reste bloqué partout, sauf "Accueil" et "Comment
    ça marche", jusqu'à validation.

    Au premier login, un pseudo est dérivé automatiquement de la partie
    avant @ de l'email (ex: "jean.dupont@exemple.com" -> "jeandupont"),
    modifiable ensuite via update_username(). C'est ce pseudo — jamais
    l'email — qui est affiché partout dans l'appli (sidebar, "ajouté
    par"...). Pour le PARTAGE d'un menu en revanche, voir public_id :
    un identifiant généré une fois pour toutes et jamais modifiable
    ensuite, contrairement au pseudo (add_list_share cherche par
    public_id, pas par username, précisément pour cette raison).
    """
    email = (email or "").strip()
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE LOWER(email) = LOWER(:email)"),
            {"email": email},
        ).mappings().first()

        if row is not None:
            return {
                "id": row["id"],
                "username": row["username"],
                "is_editor": bool(row["is_editor"]),
                "is_admin": bool(row["is_admin"]),
                "can_manage_products": bool(row["can_manage_products"]),
                "is_approved": bool(row["is_approved"]),
                "public_id": row["public_id"],
            }

        base = email.split("@")[0] if "@" in email else email
        nickname = _derive_unique_nickname(conn, base)
        public_id = _generate_unique_public_id(conn)

        # La colonne password_hash/salt reste NOT NULL en base pour ne pas
        # casser le schéma existant, mais n'est plus jamais consultée pour
        # ces comptes — l'authentification passe désormais par Auth0, pas
        # par verify_credentials(). On y met donc un jeton aléatoire à
        # haute entropie, jamais communiqué à personne (ne sert à rien de
        # le "casser", il ne débloque rien).
        digest_hex, salt_hex = _hash_password(secrets.token_urlsafe(32))
        new_id = conn.execute(
            text("""
                INSERT INTO users
                (username, email, password_hash, salt, is_editor, is_admin, can_manage_products, is_approved, public_id)
                VALUES
                (:username, :email, :password_hash, :salt, TRUE, FALSE, FALSE, FALSE, :public_id)
                RETURNING id
            """),
            {
                "username": nickname, "email": email, "password_hash": digest_hex,
                "salt": salt_hex, "public_id": public_id,
            },
        ).scalar()

    _clear_user_caches()
    return {
        "id": new_id, "username": nickname,
        "is_editor": True, "is_admin": False, "can_manage_products": False,
        "is_approved": False, "public_id": public_id,
    }


def update_username(user_id: int, new_username: str) -> None:
    """
    Change le pseudo affiché d'un compte (jamais l'email, qui reste fixe
    et invisible). Lève db.IntegrityError si ce pseudo est déjà pris par
    un autre compte (contrainte d'unicité déjà existante sur `username`).

    `recipes.created_by`/`updated_by` sont des SNAPSHOTS texte (pas une
    référence vers users.id) : sans ce traitement, changer de pseudo
    laisserait les recettes déjà créées afficher l'ancien pseudo pour
    toujours. On les met donc à jour ici, dans la MÊME transaction que le
    changement de pseudo — soit les deux réussissent, soit aucun (jamais
    un pseudo mis à jour dans `users` mais pas dans `recipes`, ce qui
    romprait la cohérence de l'attribution des recettes).
    """
    new_username = (new_username or "").strip()
    if not new_username:
        raise ValueError("Le pseudo ne peut pas être vide.")
    with get_conn() as conn:
        old_row = conn.execute(
            text("SELECT username FROM users WHERE id = :id"), {"id": user_id}
        ).mappings().first()
        old_username = old_row["username"] if old_row else None

        conn.execute(
            text("UPDATE users SET username = :username WHERE id = :id"),
            {"username": new_username, "id": user_id},
        )

        if old_username and old_username != new_username:
            conn.execute(
                text("UPDATE recipes SET created_by = :new WHERE created_by = :old"),
                {"new": new_username, "old": old_username},
            )
            conn.execute(
                text("UPDATE recipes SET updated_by = :new WHERE updated_by = :old"),
                {"new": new_username, "old": old_username},
            )

    _clear_user_caches()
    _clear_recipe_caches()


def set_user_role(user_id: int, is_editor: bool, is_admin: bool, can_manage_products: bool | None = None) -> None:
    """
    Met à jour les rôles d'un compte. `can_manage_products` est optionnel :
    laissé à None, la valeur existante n'est pas modifiée (permet à un
    appelant qui ne connaît pas encore ce rôle de continuer à fonctionner
    sans l'écraser par erreur).
    """
    with get_conn() as conn:
        if can_manage_products is None:
            conn.execute(
                text("UPDATE users SET is_editor = :is_editor, is_admin = :is_admin WHERE id = :id"),
                {"is_editor": bool(is_editor), "is_admin": bool(is_admin), "id": user_id},
            )
        else:
            conn.execute(
                text("""
                    UPDATE users
                    SET is_editor = :is_editor, is_admin = :is_admin, can_manage_products = :can_manage_products
                    WHERE id = :id
                """),
                {
                    "is_editor": bool(is_editor), "is_admin": bool(is_admin),
                    "can_manage_products": bool(can_manage_products), "id": user_id,
                },
            )
    _clear_user_caches()


def set_user_approved(user_id: int, is_approved: bool) -> None:
    """
    Valide (ou révoque la validation d')un compte — voir auth.is_approved,
    qui bloque l'accès à toute l'app (sauf "Accueil"/"Comment ça marche")
    tant qu'un compte n'est pas validé.
    """
    with get_conn() as conn:
        conn.execute(
            text("UPDATE users SET is_approved = :is_approved WHERE id = :id"),
            {"is_approved": bool(is_approved), "id": user_id},
        )
    _clear_user_caches()


def set_user_password(user_id: int, new_password: str) -> None:
    digest, salt = _hash_password(new_password)
    with get_conn() as conn:
        conn.execute(
            text("UPDATE users SET password_hash = :password_hash, salt = :salt WHERE id = :id"),
            {"password_hash": digest, "salt": salt, "id": user_id},
        )
    _clear_user_caches()


def delete_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    _clear_user_caches()


def count_admins() -> int:
    with get_conn() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")).scalar()


# ---------------------------------------------------------------------------
# Base de produits d'épicerie (harmonisation nom/synonymes + rayon)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_all_products() -> list[dict]:
    """Retourne tous les produits connus : [{id, canonical, category, synonyms}, ...]."""
    with get_conn() as conn:
        rows = conn.execute(text("SELECT * FROM products ORDER BY LOWER(canonical)")).mappings().all()
    return [
        {
            "id": r["id"],
            "canonical": r["canonical"],
            "category": r["category"],
            "synonyms": list(r["synonyms"] or []),
        }
        for r in rows
    ]


def upsert_product(canonical: str, category: str | None, synonyms: list[str]) -> None:
    """
    Crée un produit, ou met à jour son rayon/ses synonymes s'il existe déjà
    (identifié par son nom canonique). Le "upsert" (plutôt qu'un simple
    insert) permet de relancer un script de peuplement autant de fois que
    voulu sans créer de doublons.

    `category=None` enregistre le produit comme "en attente de
    classement" — utilisé quand un ingrédient inconnu est tapé dans une
    recette : le produit existe (donc reconnu la prochaine fois), mais
    reste visible dans la file d'attente de la page de gestion des
    produits jusqu'à ce que quelqu'un lui attribue un rayon.
    """
    canonical = canonical.strip()
    category = category.strip() if category and category.strip() else None
    synonyms = [s.strip() for s in synonyms if s.strip()]
    with get_conn() as conn:
        conn.execute(
            text("""
                INSERT INTO products (canonical, category, synonyms)
                VALUES (:canonical, :category, :synonyms)
                ON CONFLICT (canonical) DO UPDATE
                SET category = EXCLUDED.category, synonyms = EXCLUDED.synonyms
            """),
            {"canonical": canonical, "category": category, "synonyms": synonyms},
        )
    _clear_product_caches()


def update_product(product_id: int, canonical: str, category: str | None, synonyms: list[str]) -> None:
    """
    Met à jour un produit existant PAR SON ID (contrairement à
    `upsert_product`, qui identifie par le nom canonique). Nécessaire pour
    pouvoir corriger/renommer le nom canonique lui-même depuis la page de
    gestion des produits, sans risquer de créer un doublon.
    """
    canonical = canonical.strip()
    category = category.strip() if category and category.strip() else None
    synonyms = [s.strip() for s in synonyms if s.strip()]
    with get_conn() as conn:
        conn.execute(
            text("""
                UPDATE products
                SET canonical = :canonical, category = :category, synonyms = :synonyms
                WHERE id = :id
            """),
            {"canonical": canonical, "category": category, "synonyms": synonyms, "id": product_id},
        )
    _clear_product_caches()


def delete_product(product_id: int) -> None:
    with get_conn() as conn:
        conn.execute(text("DELETE FROM products WHERE id = :id"), {"id": product_id})
    _clear_product_caches()


# ---------------------------------------------------------------------------
# Listes de courses enregistrées sur le compte (recettes + progression)
# ---------------------------------------------------------------------------
#
# Une liste enregistrée fige un INSTANTANÉ (recettes+personnes, et le texte
# déjà formaté de chaque article) au moment de la sauvegarde : si la base de
# produits change ensuite (nouveaux synonymes, rayon corrigé...), les
# listes déjà enregistrées ne bougent pas rétroactivement — les cases
# cochées restent valables pour EXACTEMENT les articles qui existaient au
# moment de la sauvegarde.

# Nombre maximum de listes qu'un·e même utilisateur·rice peut garder
# enregistrées en même temps (évite d'accumuler indéfiniment des lignes en
# base — chaque liste entraîne aussi ses lignes d'articles et de recettes
# associées).
MAX_SAVED_LISTS_PER_USER = 5


class SavedListLimitReached(Exception):
    """
    Levée par save_shopping_list quand le compte a déjà atteint
    MAX_SAVED_LISTS_PER_USER listes enregistrées. Le message (str(exc)) est
    déjà rédigé pour être affiché tel quel à l'utilisateur·rice, par
    exemple :

        try:
            db.save_shopping_list(user_id, reference, choices, grouped)
        except db.SavedListLimitReached as exc:
            st.error(str(exc))
    """


def count_saved_lists(user_id: int) -> int:
    """Nombre de listes actuellement enregistrées par ce compte."""
    with get_conn() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM saved_shopping_lists WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalar()


def save_shopping_list(
    user_id: int,
    reference: str,
    recipe_choices: list[tuple[str, int]],
    grouped_items: dict[str, list[str]],
    recipes: dict | None = None,
) -> int:
    """
    Enregistre une liste de courses sur le compte d'un·e utilisateur·rice.
    `recipe_choices` : [(nom_recette, nb_personnes), ...].
    `grouped_items` : {rayon: [ligne formatée, ...], ...} (voir
    ShoppingList.as_grouped_lines côté common.py).

    `recipes` : le dict complet renvoyé par get_all_recipes() (la page
    appelante l'a déjà en mémoire). Sert à enregistrer, pour chaque
    recette, un INSTANTANÉ au moment de la sauvegarde — son id réel, sa
    date de dernière modification, et ses ingrédients mis à l'échelle sous
    forme structurée. Ça permet plus tard de détecter qu'une recette a été
    MODIFIÉE depuis (pas juste "supprimée" si son nom a changé), et
    d'afficher précisément ce qui a changé — voir get_saved_list() et
    common.diff_recipe_ingredients(). Optionnel pour compatibilité
    ascendante : si omis, ces instantanés restent vides pour ce menu (pas
    de détection de modification possible, comportement inchangé sinon).

    Lève SavedListLimitReached (sans rien enregistrer) si ce compte a déjà
    MAX_SAVED_LISTS_PER_USER listes enregistrées.
    """
    with get_conn() as conn:
        existing = conn.execute(
            text("SELECT COUNT(*) FROM saved_shopping_lists WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalar()
        if existing >= MAX_SAVED_LISTS_PER_USER:
            raise SavedListLimitReached(
                f"Vous avez déjà {existing} liste(s) enregistrée(s), soit le maximum autorisé "
                f"({MAX_SAVED_LISTS_PER_USER}). Supprimez-en une depuis « 📋 Mes listes » avant "
                "d'en enregistrer une nouvelle."
            )

        list_id = conn.execute(
            text("""
                INSERT INTO saved_shopping_lists (user_id, reference, created_at)
                VALUES (:user_id, :reference, :created_at)
                RETURNING id
            """),
            {"user_id": user_id, "reference": (reference or "").strip(), "created_at": _now_iso()},
        ).scalar()

        for position, (recipe_name, people) in enumerate(recipe_choices):
            recipe = (recipes or {}).get(recipe_name)
            recipe_id = recipe["id"] if recipe else None
            recipe_updated_at = recipe.get("updated_at") if recipe else None
            ingredients_snapshot = None
            if recipe is not None:
                rows = common.scaled_ingredient_rows(recipe, int(people))
                # Fraction n'est pas sérialisable en JSON tel quel : on la
                # garde en texte ("3/2") plutôt qu'en float, pour comparer
                # plus tard des valeurs EXACTES (pas d'arrondi flottant qui
                # ferait remonter un faux "changement").
                ingredients_snapshot = json.dumps(
                    [[name, str(qty), unit] for name, qty, unit in rows]
                )

            conn.execute(
                text("""
                    INSERT INTO saved_shopping_list_recipes
                        (list_id, recipe_name, people, position,
                         recipe_id, recipe_updated_at, ingredients_snapshot)
                    VALUES
                        (:list_id, :recipe_name, :people, :position,
                         :recipe_id, :recipe_updated_at, :ingredients_snapshot)
                """),
                {
                    "list_id": list_id, "recipe_name": recipe_name,
                    "people": int(people), "position": position,
                    "recipe_id": recipe_id, "recipe_updated_at": recipe_updated_at,
                    "ingredients_snapshot": ingredients_snapshot,
                },
            )

        position = 0
        for category, lines in grouped_items.items():
            for line in lines:
                conn.execute(
                    text("""
                        INSERT INTO saved_shopping_list_items (list_id, category, label, position)
                        VALUES (:list_id, :category, :label, :position)
                    """),
                    {"list_id": list_id, "category": category, "label": line, "position": position},
                )
                position += 1

    _clear_saved_list_caches()
    return list_id


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_saved_lists(user_id: int) -> list[dict]:
    """
    Résumé des listes accessibles par un·e utilisateur·rice : celles qu'il·elle
    possède, ET celles partagées avec lui·elle par quelqu'un d'autre — plus
    récentes d'abord. Chaque entrée indique `is_owner` (pour savoir si les
    actions de gestion — supprimer, partager — doivent être proposées) et
    `owner_username` (rempli seulement pour les listes partagées, pour
    affichage : "partagé par ...").
    """
    with get_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT l.id, l.reference, l.created_at,
                       COUNT(i.id) AS total_items,
                       COALESCE(SUM(CASE WHEN i.checked THEN 1 ELSE 0 END), 0) AS checked_items,
                       TRUE AS is_owner,
                       NULL::TEXT AS owner_username
                FROM saved_shopping_lists l
                LEFT JOIN saved_shopping_list_items i ON i.list_id = l.id
                WHERE l.user_id = :user_id
                GROUP BY l.id

                UNION ALL

                SELECT l.id, l.reference, l.created_at,
                       COUNT(i.id) AS total_items,
                       COALESCE(SUM(CASE WHEN i.checked THEN 1 ELSE 0 END), 0) AS checked_items,
                       FALSE AS is_owner,
                       u.username AS owner_username
                FROM saved_shopping_lists l
                JOIN saved_shopping_list_shares s ON s.list_id = l.id AND s.user_id = :user_id
                JOIN users u ON u.id = l.user_id
                LEFT JOIN saved_shopping_list_items i ON i.list_id = l.id
                GROUP BY l.id, u.username

                ORDER BY created_at DESC, id DESC
            """),
            {"user_id": user_id},
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "reference": r["reference"],
            "created_at": r["created_at"],
            "total_items": r["total_items"],
            "checked_items": r["checked_items"],
            "is_owner": bool(r["is_owner"]),
            "owner_username": r["owner_username"],
        }
        for r in rows
    ]


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def get_saved_list(list_id: int, user_id: int) -> dict | None:
    """
    Détail complet d'une liste (recettes + articles), accessible si
    `user_id` en est le·la propriétaire OU si la liste a été partagée avec
    lui·elle — vérification d'accès systématique, jamais de confiance
    aveugle en un id reçu. Renvoie None si aucune des deux conditions
    n'est remplie (y compris si la liste n'existe simplement pas).

    Champs utiles côté page : `is_owner` (affichage des actions de gestion
    — supprimer, gérer le partage) et `owner_username` (affichage "partagé
    par ..." quand ce n'est pas le cas).
    """
    with get_conn() as conn:
        list_row = conn.execute(
            text("""
                SELECT l.*, u.username AS owner_username
                FROM saved_shopping_lists l
                JOIN users u ON u.id = l.user_id
                WHERE l.id = :id
                  AND (
                        l.user_id = :user_id
                        OR EXISTS (
                            SELECT 1 FROM saved_shopping_list_shares s
                            WHERE s.list_id = l.id AND s.user_id = :user_id
                        )
                  )
            """),
            {"id": list_id, "user_id": user_id},
        ).mappings().first()
        if list_row is None:
            return None

        recipe_rows = conn.execute(
            text("SELECT * FROM saved_shopping_list_recipes WHERE list_id = :id ORDER BY position"),
            {"id": list_id},
        ).mappings().all()
        item_rows = conn.execute(
            text("SELECT * FROM saved_shopping_list_items WHERE list_id = :id ORDER BY position"),
            {"id": list_id},
        ).mappings().all()

    return {
        "id": list_row["id"],
        "reference": list_row["reference"],
        "created_at": list_row["created_at"],
        "owner_user_id": list_row["user_id"],
        "owner_username": list_row["owner_username"],
        "is_owner": list_row["user_id"] == user_id,
        "recipes": [
            {
                "name": r["recipe_name"],
                "people": r["people"],
                "recipe_id": r["recipe_id"],
                "recipe_updated_at": r["recipe_updated_at"],
                "ingredients_snapshot": (
                    [(name, Fraction(qty), unit) for name, qty, unit in json.loads(r["ingredients_snapshot"])]
                    if r["ingredients_snapshot"] else None
                ),
            }
            for r in recipe_rows
        ],
        "items": [
            {"id": r["id"], "category": r["category"], "label": r["label"], "checked": bool(r["checked"])}
            for r in item_rows
        ],
    }


def set_shopping_item_checked(item_id: int, user_id: int, checked: bool) -> None:
    """
    Coche/décoche un article — autorisé pour le·la propriétaire de la liste
    ET pour toute personne avec qui elle a été partagée (vérifié via une
    sous-requête ; si `user_id` n'a accès ni comme propriétaire ni comme
    partagé·e, la clause WHERE ne matche aucune ligne et rien n'est modifié,
    silencieusement — même logique de sécurité que le reste du module)."""
    with get_conn() as conn:
        conn.execute(
            text("""
                UPDATE saved_shopping_list_items
                SET checked = :checked
                WHERE id = :item_id
                  AND list_id IN (
                        SELECT id FROM saved_shopping_lists WHERE user_id = :user_id
                        UNION
                        SELECT list_id FROM saved_shopping_list_shares WHERE user_id = :user_id
                  )
            """),
            {"checked": bool(checked), "item_id": item_id, "user_id": user_id},
        )
    _clear_saved_list_caches()


def delete_saved_list(list_id: int, user_id: int) -> None:
    """Supprime une liste enregistrée — vérifie que `user_id` en est bien le·la propriétaire.
    Les partages associés disparaissent automatiquement (ON DELETE CASCADE)."""
    with get_conn() as conn:
        conn.execute(
            text("DELETE FROM saved_shopping_lists WHERE id = :id AND user_id = :user_id"),
            {"id": list_id, "user_id": user_id},
        )
    _clear_saved_list_caches()


class ListShareError(Exception):
    """
    Levée par add_list_share quand le partage n'a pas pu être fait. Le
    message (str(exc)) est déjà rédigé pour être affiché tel quel, par
    exemple :

        try:
            db.add_list_share(list_id, owner_user_id, username)
        except db.ListShareError as exc:
            st.error(str(exc))
    """


def get_list_shares(list_id: int, owner_user_id: int) -> list[dict]:
    """
    Liste des comptes avec qui une liste a été partagée — réservé au·à la
    propriétaire (vérifié avant de renvoyer quoi que ce soit ; renvoie une
    liste vide si `owner_user_id` n'est pas le·la propriétaire, plutôt que
    de lever une erreur, pour rester simple à appeler côté page)."""
    with get_conn() as conn:
        owns_it = conn.execute(
            text("SELECT 1 FROM saved_shopping_lists WHERE id = :id AND user_id = :user_id"),
            {"id": list_id, "user_id": owner_user_id},
        ).first()
        if owns_it is None:
            return []
        rows = conn.execute(
            text("""
                SELECT u.id AS user_id, u.username
                FROM saved_shopping_list_shares s
                JOIN users u ON u.id = s.user_id
                WHERE s.list_id = :list_id
                ORDER BY LOWER(u.username)
            """),
            {"list_id": list_id},
        ).mappings().all()
    return [{"user_id": r["user_id"], "username": r["username"]} for r in rows]


def add_list_share(list_id: int, owner_user_id: int, target_public_id: str) -> str:
    """
    Partage une liste avec un compte existant, désigné par son identifiant
    UNIQUE ET STABLE (public_id — voir _generate_unique_public_id), pas
    par son pseudo : un pseudo librement modifiable casserait un partage
    basé dessus si la personne en changeait après coup. Seul·e le·la
    propriétaire peut partager sa propre liste. Renvoie le pseudo du
    compte concerné (pour un message de confirmation lisible) en cas de
    succès.

    Lève ListShareError (message prêt à afficher) si :
    - `owner_user_id` n'est pas le·la propriétaire de la liste ;
    - le compte cible n'existe pas ;
    - le compte cible est le·la propriétaire lui·elle-même ;
    - la liste est déjà partagée avec ce compte.
    """
    with get_conn() as conn:
        owns_it = conn.execute(
            text("SELECT 1 FROM saved_shopping_lists WHERE id = :id AND user_id = :user_id"),
            {"id": list_id, "user_id": owner_user_id},
        ).first()
        if owns_it is None:
            raise ListShareError("Seul·e le·la propriétaire d'un menu peut le partager.")

        target = conn.execute(
            text("SELECT id, username FROM users WHERE UPPER(public_id) = UPPER(:pid)"),
            {"pid": (target_public_id or "").strip()},
        ).mappings().first()
        if target is None:
            raise ListShareError(f"Aucun compte trouvé avec l'identifiant « {target_public_id} ».")
        if target["id"] == owner_user_id:
            raise ListShareError("Impossible de partager un menu avec soi-même.")

        try:
            conn.execute(
                text("""
                    INSERT INTO saved_shopping_list_shares (list_id, user_id, created_at)
                    VALUES (:list_id, :user_id, :created_at)
                """),
                {"list_id": list_id, "user_id": target["id"], "created_at": _now_iso()},
            )
        except IntegrityError:
            raise ListShareError(f"Ce menu est déjà partagé avec « {target['username']} ».")

    _clear_saved_list_caches()
    return target["username"]


def remove_list_share(list_id: int, requesting_user_id: int, target_user_id: int) -> bool:
    """
    Retire l'accès d'un compte à une liste partagée. Autorisé dans deux cas :
    - `requesting_user_id` est le·la propriétaire de la liste (il·elle
      révoque l'accès de quelqu'un d'autre) ;
    - `requesting_user_id == target_user_id` (la personne quitte
      elle-même un menu partagé avec elle).
    Renvoie True si un partage a bien été supprimé, False sinon (aucun des
    deux cas ne s'applique, ou le partage n'existait pas).
    """
    with get_conn() as conn:
        is_owner = conn.execute(
            text("SELECT 1 FROM saved_shopping_lists WHERE id = :id AND user_id = :user_id"),
            {"id": list_id, "user_id": requesting_user_id},
        ).first() is not None

        if not (is_owner or requesting_user_id == target_user_id):
            return False

        result = conn.execute(
            text("DELETE FROM saved_shopping_list_shares WHERE list_id = :list_id AND user_id = :target_user_id"),
            {"list_id": list_id, "target_user_id": target_user_id},
        )
        deleted = result.rowcount > 0

    if deleted:
        _clear_saved_list_caches()
    return deleted


# ---------------------------------------------------------------------------
# Jetons "garde-moi connecté·e" (connexion persistante via cookie navigateur)
# ---------------------------------------------------------------------------
#
# Sans ceci, une personne connectée est déconnectée dès que sa session
# Streamlit redémarre — ce qui arrive après quelques minutes d'inactivité
# (verrouillage du téléphone, changement d'onglet...) : la reconnexion du
# WebSocket sous-jacent démarre une NOUVELLE session Streamlit, qui vide
# st.session_state, même si le navigateur reste ouvert sur la même page.
#
# Le jeton lui-même (une chaîne aléatoire à haute entropie, 32 octets) est
# stocké dans un cookie navigateur longue durée ; seul son HASH est
# conservé ici, jamais le jeton en clair — comme pour un mot de passe, sauf
# qu'un hash rapide (SHA-256) suffit ici : ce n'est pas un secret choisi
# par un humain (donc pas de risque d'attaque par dictionnaire), juste un
# jeton opaque à haute entropie qu'on veut pouvoir vérifier rapidement à
# CHAQUE page vue.

REMEMBER_TOKEN_DAYS = 30


def create_remember_token(user_id: int, days: int = REMEMBER_TOKEN_DAYS) -> str:
    """
    Crée un jeton "garde-moi connecté·e" pour ce compte et le renvoie EN
    CLAIR (à poser dans un cookie navigateur côté appelant — seul son hash
    est conservé en base, le jeton en clair n'est jamais stocké nulle part
    côté serveur).
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = _now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")

    with get_conn() as conn:
        # Petit ménage opportuniste : les jetons déjà expirés de CE compte
        # sont purgés à chaque nouvelle connexion, plutôt que de s'accumuler
        # indéfiniment (ex. cookie effacé manuellement par la personne sans
        # jamais cliquer sur "Se déconnecter").
        conn.execute(
            text("DELETE FROM remember_tokens WHERE user_id = :user_id AND expires_at < :now"),
            {"user_id": user_id, "now": now},
        )
        conn.execute(
            text("""
                INSERT INTO remember_tokens (user_id, token_hash, created_at, expires_at)
                VALUES (:user_id, :token_hash, :created_at, :expires_at)
            """),
            {"user_id": user_id, "token_hash": token_hash, "created_at": now, "expires_at": expires_at},
        )
    return raw_token


def verify_remember_token(raw_token: str) -> dict | None:
    """
    Vérifie un jeton "garde-moi connecté·e" (reçu du cookie navigateur).
    Renvoie les informations du compte (même forme que verify_credentials)
    s'il est valide et non expiré, sinon None. Un jeton expiré est supprimé
    au passage (nettoyage à l'usage, pas besoin de tâche planifiée séparée).
    """
    if not raw_token:
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            text("""
                SELECT rt.id AS token_id, rt.expires_at, u.*
                FROM remember_tokens rt
                JOIN users u ON u.id = rt.user_id
                WHERE rt.token_hash = :token_hash
            """),
            {"token_hash": token_hash},
        ).mappings().first()

        if row is None:
            return None

        if row["expires_at"] < _now_iso():
            conn.execute(text("DELETE FROM remember_tokens WHERE id = :id"), {"id": row["token_id"]})
            return None

    # `u.*` inclut la colonne `id` de l'utilisateur (sans alias) : c'est
    # bien l'id du COMPTE ici, pas celui du jeton (qui est "token_id").
    return {
        "id": row["id"],
        "username": row["username"],
        "is_editor": bool(row["is_editor"]),
        "is_admin": bool(row["is_admin"]),
        "can_manage_products": bool(row["can_manage_products"]),
    }


def revoke_remember_token(raw_token: str) -> None:
    """Invalide un jeton "garde-moi connecté·e" (à la déconnexion) — ce navigateur ne se reconnectera plus tout seul."""
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        conn.execute(text("DELETE FROM remember_tokens WHERE token_hash = :token_hash"), {"token_hash": token_hash})
