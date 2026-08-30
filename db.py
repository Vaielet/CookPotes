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
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

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
MAX_DESCRIPTION_CHARS = 300

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
    get_all_tags.clear()
    get_all_authors.clear()
    get_recent_recipes.clear()


def _clear_user_caches() -> None:
    """À appeler après toute écriture qui change les comptes utilisateur·rices."""
    list_users.clear()


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


def init_db() -> None:
    """Crée les tables si nécessaire, migre le schéma, et pré-remplit la base si elle est vide."""
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
                is_admin       BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
    _migrate_schema()
    _seed_default_recipes_if_empty()
    _seed_default_admin_if_empty()


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
) -> int:
    """Crée un nouvel utilisateur."""

    digest_hex, salt_hex = _hash_password(password)

    with get_conn() as conn:
        new_id = conn.execute(
            text("""
                INSERT INTO users
                (username, password_hash, salt, is_editor, is_admin)
                VALUES
                (:username, :password_hash, :salt, :is_editor, :is_admin)
                RETURNING id
            """),
            {
                "username": username.strip(),
                "password_hash": digest_hex,
                "salt": salt_hex,
                "is_editor": bool(is_editor),
                "is_admin": bool(is_admin),
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
    }


@st.cache_data(show_spinner=False, ttl=_READ_CACHE_TTL)
def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            text("SELECT id, username, is_editor, is_admin FROM users ORDER BY LOWER(username)")
        ).mappings().all()
    return [
        {"id": r["id"], "username": r["username"], "is_editor": bool(r["is_editor"]), "is_admin": bool(r["is_admin"])}
        for r in rows
    ]


def set_user_role(user_id: int, is_editor: bool, is_admin: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            text("UPDATE users SET is_editor = :is_editor, is_admin = :is_admin WHERE id = :id"),
            {"is_editor": bool(is_editor), "is_admin": bool(is_admin), "id": user_id},
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
