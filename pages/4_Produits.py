"""
Page 4 — Gestion de la base de produits d'épicerie.

Réservée aux comptes ayant le droit "Gestion des produits" (ou aux
administrateur·rices). Permet de :
  - classer les produits qui n'ont pas encore de rayon et/ou de synonymes
    (typiquement enregistrés "à la volée" depuis la page « Ajouter une
    recette » quand un ingrédient inconnu est tapé, ou importés depuis
    Open Food Facts sans classement) ;
  - corriger le nom canonique, le rayon ou les synonymes de n'importe quel
    produit existant ;
  - ajouter manuellement un nouveau produit.
"""

from __future__ import annotations

import streamlit as st

import auth
import common
import db

st.set_page_config(page_title="Gestion des produits", page_icon="🧺", layout="wide")

db.init_db()

#common.header_logo()

auth.require_product_curator()

common.icon_title("Gestion des produits", "gestion_produits.png", "🧺")

st.caption(
    "Harmonise les noms d'ingrédients (synonymes) et leur rayon, utilisés "
    "pour regrouper la liste de courses. Les modifications sont "
    "immédiatement prises en compte dans toute l'application."
)

if st.session_state.get("_flash_product_msg"):
    st.success(st.session_state["_flash_product_msg"])
    st.session_state["_flash_product_msg"] = None

refresh_col, _spacer = st.columns([1, 4])
if refresh_col.button(
    "🔄 Rafraîchir les données", use_container_width=True,
    help="À utiliser si tu viens de modifier la base par un autre moyen "
         "que cette page (ex. un script d'import) — l'appli ne peut pas "
         "s'en apercevoir toute seule.",
):
    db.get_all_products.clear()
    st.rerun()

NEW_CATEGORY_PLACEHOLDER = "— non classé —"


def _category_options(current_category: str | None = None) -> list[str]:
    """
    Options du menu déroulant « Rayon ». Inclut toujours `current_category`
    s'il est renseigné, MÊME s'il ne fait pas partie des rayons standard de
    l'appli (ex. une catégorie venant d'un import externe, différente de
    celles listées dans common.CATEGORY_ORDER) — sinon le menu ne le
    trouve pas dans ses options et retombe silencieusement sur « — non
    classé — », ce qui donne l'impression trompeuse que le produit n'est
    pas classé alors qu'il l'est, juste avec un rayon "hors liste".
    """
    options = [NEW_CATEGORY_PLACEHOLDER] + common.CATEGORY_ORDER
    if current_category and current_category not in options:
        options.append(current_category)
    return options


def _clean_synonyms(synonyms: list[str]) -> list[str]:
    """Synonymes réellement utilisables : non vides, espaces superflus retirés."""
    return [s.strip() for s in synonyms if s and s.strip()]


def _is_classified(product: dict) -> bool:
    """
    Un produit est considéré classé s'il a un rayon qui fait partie de la
    liste standard de l'appli (common.CATEGORY_ORDER) ET au moins un vrai
    synonyme. Un rayon "hors liste" (ex. venant d'un import externe avec sa
    propre nomenclature) ne compte PAS comme classé : il doit être remappé
    vers un rayon habituel, donc reste dans "à classer" plutôt que de
    passer inaperçu comme si tout allait bien.

    Passe par `_clean_synonyms`/`.strip()` plutôt qu'un simple
    `not product["synonyms"]` : une liste contenant uniquement des chaînes
    vides ou des espaces (ex. `['']`, parfois produite par un import
    externe mal formé) est vide en pratique, même si elle n'est pas vide
    au sens Python.
    """
    category = (product["category"] or "").strip()
    category_ok = category in common.CATEGORY_ORDER
    synonyms_ok = bool(_clean_synonyms(product["synonyms"]))
    return category_ok and synonyms_ok


def _render_product_row(product: dict, key_prefix: str) -> None:
    """
    Une ligne éditable (nom canonique / rayon / synonymes) + boutons
    Enregistrer / Supprimer.

    `key_prefix` distingue l'onglet d'où la ligne est affichée ("todo" ou
    "all") : st.tabs() exécute le contenu de TOUS les onglets à chaque run
    (seul l'affichage est masqué/affiché côté navigateur), donc un même
    produit apparaissant à la fois dans "à classer" et "tous les produits"
    génère sinon deux widgets avec exactement la même clé — Streamlit lève
    alors StreamlitDuplicateElementKey.
    """
    with st.container(border=True):
        cols = st.columns([2.2, 1.6, 2.6, 1, 1])

        canonical = cols[0].text_input(
            "Nom canonique", value=product["canonical"],
            key=f"prod_canonical_{key_prefix}_{product['id']}", label_visibility="collapsed",
        )

        clean_synonyms = _clean_synonyms(product["synonyms"])
        raw_category = (product["category"] or "").strip()
        current_category = raw_category or NEW_CATEGORY_PLACEHOLDER
        options = _category_options(raw_category)
        category_choice = cols[1].selectbox(
            "Rayon", options=options,
            index=options.index(current_category) if current_category in options else 0,
            key=f"prod_category_{key_prefix}_{product['id']}", label_visibility="collapsed",
        )

        synonyms_text = cols[2].text_input(
            "Synonymes (séparés par des virgules)", value=", ".join(clean_synonyms),
            key=f"prod_synonyms_{key_prefix}_{product['id']}", label_visibility="collapsed",
            placeholder="ex : courgette, courgettes vertes",
        )

        changed = (
            canonical.strip() != product["canonical"]
            or category_choice != current_category
            or synonyms_text.strip() != ", ".join(clean_synonyms)
        )
        if cols[3].button("💾 Enregistrer", key=f"prod_save_{key_prefix}_{product['id']}", disabled=not changed, use_container_width=True):
            new_category = None if category_choice == NEW_CATEGORY_PLACEHOLDER else category_choice
            new_synonyms = _clean_synonyms(synonyms_text.split(","))
            try:
                db.update_product(product["id"], canonical, new_category, new_synonyms)
            except db.IntegrityError:
                st.error(f"Un autre produit s'appelle déjà « {canonical.strip()} ».")
            else:
                st.session_state["_flash_product_msg"] = f"« {canonical.strip()} » mis à jour."
                st.rerun()

        if cols[4].button("🗑️", key=f"prod_delete_{key_prefix}_{product['id']}", help="Supprimer ce produit", use_container_width=True):
            db.delete_product(product["id"])
            st.session_state["_flash_product_msg"] = f"« {product['canonical']} » supprimé."
            st.rerun()

        category_value = (product["category"] or "").strip()
        category_missing = not category_value
        category_nonstandard = bool(category_value) and category_value not in common.CATEGORY_ORDER
        synonyms_missing = not clean_synonyms

        if category_missing and synonyms_missing:
            cols[0].caption("⚠️ Pas encore de rayon ni de synonyme")
        elif category_missing:
            cols[0].caption("⚠️ Pas encore de rayon")
        elif category_nonstandard and synonyms_missing:
            cols[0].caption(f"⚠️ Rayon « {category_value} » non standard — à remapper, et pas encore de synonyme")
        elif category_nonstandard:
            cols[0].caption(f"⚠️ Rayon « {category_value} » non standard — à remapper vers un rayon habituel")
        elif synonyms_missing:
            cols[0].caption("⚠️ Pas encore de synonyme")


all_products = db.get_all_products()
unclassified = [p for p in all_products if not _is_classified(p)]

tab_todo, tab_all, tab_add = st.tabs([
    f"🔎 À classer ({len(unclassified)})",
    f"📋 Tous les produits ({len(all_products)})",
    "➕ Ajouter un produit",
])

MAX_DISPLAYED = 100

with tab_todo:
    if not unclassified:
        st.success("Tous les produits sont classés, avec au moins un synonyme chacun.")
    else:
        search_todo = st.text_input(
            "🔎 Filtrer par nom", key="search_todo", placeholder="ex : courgette",
        ).strip().lower()
        filtered = [p for p in unclassified if search_todo in p["canonical"].lower()] if search_todo else unclassified
        if len(filtered) > MAX_DISPLAYED:
            st.caption(f"{len(filtered)} produits à classer — affiche les {MAX_DISPLAYED} premiers. Affine ta recherche pour voir les autres.")
        for product in filtered[:MAX_DISPLAYED]:
            _render_product_row(product, key_prefix="todo")

with tab_all:
    search_all = st.text_input(
        "🔎 Filtrer par nom", key="search_all", placeholder="ex : courgette",
    ).strip().lower()
    filtered_all = [p for p in all_products if search_all in p["canonical"].lower()] if search_all else all_products
    if not search_all:
        st.caption(f"{len(all_products)} produits au total — utilise la recherche pour affiner.")
    if len(filtered_all) > MAX_DISPLAYED:
        st.caption(f"{len(filtered_all)} résultats — affiche les {MAX_DISPLAYED} premiers. Affine ta recherche pour voir les autres.")
    for product in filtered_all[:MAX_DISPLAYED]:
        _render_product_row(product, key_prefix="all")

with tab_add:
    st.caption("Pour ajouter un produit qui n'existe pas encore dans la base.")
    with st.form("_add_product_form", clear_on_submit=True):
        new_canonical = st.text_input("Nom canonique", placeholder="ex : Courgette")
        new_category = st.selectbox("Rayon (optionnel)", options=_category_options())
        new_synonyms = st.text_input(
            "Synonymes (optionnel, séparés par des virgules)",
            placeholder="ex : courgette, courgettes, courgette verte",
        )
        submitted = st.form_submit_button("➕ Ajouter le produit", type="primary")
    if submitted:
        if not new_canonical.strip():
            st.error("Le nom canonique est obligatoire.")
        else:
            category_value = None if new_category == NEW_CATEGORY_PLACEHOLDER else new_category
            synonyms_list = _clean_synonyms(new_synonyms.split(","))
            db.upsert_product(new_canonical, category_value, synonyms_list)
            st.session_state["_flash_product_msg"] = f"« {new_canonical.strip()} » ajouté."
            st.rerun()
