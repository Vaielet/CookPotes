"""
Page 1 — Ajouter / modifier une recette.

Réservée aux utilisateurs connectés avec le statut éditeur (ou admin).
Un même formulaire sert à la fois pour créer une nouvelle recette et pour
corriger une recette existante (bouton "✏️ Modifier" dans la liste en bas
de page).

Note technique sur le formulaire dynamique (sections/ingrédients) :
Streamlit interdit de modifier st.session_state[key] APRÈS que le widget
portant cette key a déjà été instancié dans le run en cours. Toute remise à
zéro ou pré-remplissage du formulaire (ajout réussi, passage en mode
édition, annulation) se fait donc via un drapeau traité tout en haut du
script, AVANT la création des widgets.
"""

import uuid
from fractions import Fraction

import streamlit as st

import auth
import db
import common

st.set_page_config(page_title="Ajouter / modifier une recette", page_icon="🍳", layout="wide")

db.init_db()

common.header_logo()

auth.require_editor()

st.title("🍳 Ajoute une recette")
st.caption(
    "Encode une nouvelle recette. Les nouvelles recettes sont enregistrés dans la base "
    "de données et disponibles pour tou·tes les utilisateur·rices"
    " immédiatement sur la page « Générer ma liste »."
)


# ---------------------------------------------------------------------------
# Aides pour la structure du formulaire dynamique
# ---------------------------------------------------------------------------

def _new_row(name="", qty=1.0, unit="g"):
    return {"id": uuid.uuid4().hex, "name": name, "qty": qty, "unit": unit}


def _new_section(name="Plat", rows=None):
    return {"id": uuid.uuid4().hex, "name": name, "rows": rows or [_new_row()]}


def _sections_from_recipe_data(ingredients: dict) -> list:
    sections = []
    for section_name, rows in ingredients.items():
        sections.append(_new_section(
            name=section_name,
            rows=[_new_row(name=n, qty=float(q), unit=u) for n, q, u in rows] or [_new_row()],
        ))
    return sections or [_new_section()]


def _blank_form_state() -> None:
    st.session_state["form_mode"] = "add"
    st.session_state["form_recipe_id"] = None
    st.session_state["form_existing_image"] = None
    st.session_state["form_existing_image_mime"] = None
    st.session_state["form_created_by"] = None
    st.session_state["form_created_at"] = None
    st.session_state.new_recipe_sections = [_new_section()]
    st.session_state.pop("new_recipe_name", None)
    st.session_state.pop("new_recipe_portions", None)
    st.session_state.pop("new_recipe_instructions", None)
    st.session_state.pop("new_recipe_tags_select", None)
    st.session_state.pop("new_recipe_tags_custom", None)
    st.session_state.pop("new_recipe_description", None)
    st.session_state.pop("new_recipe_prep_time", None)
    st.session_state.pop("new_recipe_cook_time", None)
    st.session_state["_uploader_key"] = f"uploader_{uuid.uuid4().hex}"


def _load_edit_form_state(recipe: dict) -> None:
    st.session_state["form_mode"] = "edit"
    st.session_state["form_recipe_id"] = recipe["id"]
    st.session_state["form_existing_image"] = recipe["image"]
    st.session_state["form_existing_image_mime"] = recipe["image_mime"]
    st.session_state["form_created_by"] = recipe.get("created_by")
    st.session_state["form_created_at"] = recipe.get("created_at")
    st.session_state.new_recipe_sections = _sections_from_recipe_data(recipe["ingredients"])
    st.session_state["new_recipe_name"] = recipe["name"]
    st.session_state["new_recipe_portions"] = recipe["portions_base"]
    st.session_state["new_recipe_instructions"] = "\n".join(recipe["instructions"])
    st.session_state["new_recipe_description"] = recipe.get("description", "") or ""
    st.session_state["new_recipe_prep_time"] = recipe.get("prep_time_minutes") or 0
    st.session_state["new_recipe_cook_time"] = recipe.get("cook_time_minutes") or 0

    # Répartit les tags existants entre ceux qui figurent dans la liste
    # suggérée (multiselect) et les tags personnalisés (champ texte libre).
    existing_tags = recipe.get("tags", [])
    known_lower = {t.lower() for t in common.COMMON_TAGS}
    preset_tags = [t for t in existing_tags if t.lower() in known_lower]
    custom_tags = [t for t in existing_tags if t.lower() not in known_lower]
    st.session_state["new_recipe_tags_select"] = preset_tags
    st.session_state["new_recipe_tags_custom"] = ", ".join(custom_tags)

    st.session_state["_uploader_key"] = f"uploader_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Traitement des drapeaux de (ré)initialisation — AVANT tout widget
# ---------------------------------------------------------------------------

if "form_mode" not in st.session_state:
    _blank_form_state()

if st.session_state.get("_pending_reset"):
    _blank_form_state()
    st.session_state["_pending_reset"] = False

if st.session_state.get("_pending_edit_id") is not None:
    if auth.is_admin():
        recipe_to_edit = db.get_recipe_by_id(st.session_state["_pending_edit_id"])
        if recipe_to_edit is not None:
            _load_edit_form_state(recipe_to_edit)
    st.session_state["_pending_edit_id"] = None

# Garde-fou : si le mode édition est actif mais que l'utilisateur n'est
# (plus) admin — par exemple si son rôle a changé en cours de session — on
# revient silencieusement au formulaire d'ajout vierge.
if st.session_state.get("form_mode") == "edit" and not auth.is_admin():
    _blank_form_state()

if st.session_state.get("_pending_cancel_edit"):
    _blank_form_state()
    st.session_state["_pending_cancel_edit"] = False

if st.session_state.get("_flash_success"):
    st.success(st.session_state["_flash_success"])
    st.session_state["_flash_success"] = None


# ---------------------------------------------------------------------------
# En-tête du formulaire (mode ajout / édition)
# ---------------------------------------------------------------------------

editing = st.session_state["form_mode"] == "edit"

if editing:
    st.info("✏️ Vous modifiez actuellement une recette existante.")
    if st.button("↩️ Annuler la modification et revenir à l'ajout"):
        st.session_state["_pending_cancel_edit"] = True
        st.rerun()

st.subheader("Informations générales")

c1, c2 = st.columns([2, 1])
recipe_name = c1.text_input(
    "Nom de la recette", key="new_recipe_name", placeholder="ex : Curry de pois chiches"
)
portions_base = c2.number_input(
    "Nombre de personnes (base)", min_value=1, step=1, key="new_recipe_portions"
)

time_cols = st.columns(2)
prep_time = time_cols[0].number_input(
    "⏱️ Temps de préparation (minutes)", min_value=0, step=5, key="new_recipe_prep_time"
)
cook_time = time_cols[1].number_input(
    "🔥 Temps de cuisson (minutes)", min_value=0, step=5, key="new_recipe_cook_time"
)

description = st.text_area(
    "Un mot sur cette recette — pourquoi vous l'aimez bien (optionnel)",
    key="new_recipe_description",
    max_chars=common.MAX_DESCRIPTION_CHARS,
    height=80,
    placeholder="Le plat réconfortant de mamie, parfait les soirs d'hiver...",
)
st.caption(f"{len(st.session_state.get('new_recipe_description') or '')}/{common.MAX_DESCRIPTION_CHARS} caractères")

st.markdown("**Catégories**")
tag_cols = st.columns([2, 2])
selected_preset_tags = tag_cols[0].multiselect(
    "Catégories suggérées",
    options=common.COMMON_TAGS,
    key="new_recipe_tags_select",
)
custom_tags_text = tag_cols[1].text_input(
    "Autres catégories (séparées par des virgules)",
    key="new_recipe_tags_custom",
    placeholder="ex : Sans œufs, Recette de grand-mère",
)

if st.session_state.get("form_created_by"):
    st.caption(
        f"👤 Ajoutée par **{st.session_state['form_created_by']}** "
        f"le {common.format_datetime(st.session_state.get('form_created_at'))}"
    )

existing_image = st.session_state.get("form_existing_image")
if editing and existing_image:
    st.markdown("**Photo actuelle :**")
    st.image(common.get_recipe_image(recipe_name or "Recette", existing_image), width=250)

image_file = st.file_uploader(
    "Nouvelle photo (optionnel — laissez vide pour "
    + ("conserver la photo actuelle" if editing and existing_image else "générer une image de remplacement automatique"),
    type=["jpg", "jpeg", "png"],
    key=st.session_state["_uploader_key"],
)
if image_file is not None:
    st.image(image_file, width=250)


# ---------------------------------------------------------------------------
# Ingrédients (organisés en sections : Plat, Sauce, Accompagnement, ...)
# ---------------------------------------------------------------------------

st.subheader("Ingrédients")
st.caption(
    "Organisez les ingrédients en sections (ex : Plat, Sauce, "
    "Accompagnement). Les quantités indiquées correspondent au nombre de "
    "personnes de base ci-dessus."
)

for sec in st.session_state.new_recipe_sections:
    with st.container(border=True):
        top_cols = st.columns([4, 1])
        sec["name"] = top_cols[0].text_input(
            "Nom de la section", value=sec["name"], key=f"secname_{sec['id']}"
        )
        if len(st.session_state.new_recipe_sections) > 1:
            if top_cols[1].button("🗑️ Supprimer la section", key=f"delsec_{sec['id']}"):
                st.session_state.new_recipe_sections = [
                    s for s in st.session_state.new_recipe_sections if s["id"] != sec["id"]
                ]
                st.rerun()

        header_cols = st.columns([3, 1.3, 1.3, 0.6])
        header_cols[0].markdown("**Ingrédient**")
        header_cols[1].markdown("**Quantité**")
        header_cols[2].markdown("**Unité**")

        rows_to_delete = None
        for row in sec["rows"]:
            r1, r2, r3, r4 = st.columns([3, 1.3, 1.3, 0.6])
            row["name"] = r1.text_input(
                "Ingrédient", value=row["name"], key=f"iname_{row['id']}",
                label_visibility="collapsed",
            )
            row["qty"] = r2.number_input(
                "Quantité", value=float(row["qty"]), min_value=0.0, step=0.5,
                key=f"iqty_{row['id']}", label_visibility="collapsed",
            )
            row["unit"] = r3.selectbox(
                "Unité",
                options=common.COMMON_UNITS,
                index=common.COMMON_UNITS.index(row["unit"]) if row["unit"] in common.COMMON_UNITS else 0,
                key=f"iunit_{row['id']}", label_visibility="collapsed",
            )
            if r4.button("🗑️", key=f"delrow_{row['id']}"):
                rows_to_delete = row["id"]

        if rows_to_delete is not None:
            sec["rows"] = [r for r in sec["rows"] if r["id"] != rows_to_delete]
            st.rerun()

        if st.button("+ Ajouter un ingrédient", key=f"addrow_{sec['id']}"):
            sec["rows"].append(_new_row())
            st.rerun()

if st.button("+ Ajouter une section (ex : Sauce, Accompagnement)"):
    st.session_state.new_recipe_sections.append(_new_section(""))
    st.rerun()


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

st.subheader("Instructions")
instructions_text = st.text_area(
    "Une étape par ligne, sans numérotation",
    key="new_recipe_instructions",
    height=150,
    placeholder="Épluchez et coupez les légumes...\nFaites revenir dans l'huile d'olive...\n...",
)


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------

st.divider()

save_label = "💾 Enregistrer les modifications" if editing else "💾 Enregistrer la recette"

if st.button(save_label, type="primary"):
    errors = []

    name = recipe_name.strip()
    if not name:
        errors.append("Le nom de la recette est obligatoire.")

    sections = {}
    for sec in st.session_state.new_recipe_sections:
        section_name = sec["name"].strip() or "Plat"
        valid_rows = [
            (row["name"].strip(), row["qty"], row["unit"])
            for row in sec["rows"]
            if row["name"].strip() and row["qty"] > 0
        ]
        if valid_rows:
            sections.setdefault(section_name, []).extend(valid_rows)

    if not sections:
        errors.append("Ajoutez au moins un ingrédient avec un nom et une quantité positive.")

    if editing and not auth.is_admin():
        errors.append("La modification d'une recette est réservée aux administrateurs.")

    instructions = [line.strip() for line in instructions_text.splitlines() if line.strip()]

    custom_tags = [t.strip() for t in custom_tags_text.split(",") if t.strip()]
    tags = list(selected_preset_tags) + custom_tags

    if errors:
        for err in errors:
            st.error(err)
    else:
        if image_file is not None:
            image_bytes = image_file.getvalue()
            image_mime = image_file.type
        elif editing:
            image_bytes = st.session_state.get("form_existing_image")
            image_mime = st.session_state.get("form_existing_image_mime")
        else:
            image_bytes = None
            image_mime = None

        current_user = auth.current_username()

        try:
            if editing:
                db.update_recipe(
                    recipe_id=st.session_state["form_recipe_id"],
                    name=name,
                    portions_base=int(portions_base),
                    image_bytes=image_bytes,
                    image_mime=image_mime,
                    sections=sections,
                    instructions=instructions,
                    tags=tags,
                    description=description,
                    prep_time_minutes=int(prep_time) or None,
                    cook_time_minutes=int(cook_time) or None,
                    updated_by=current_user,
                )
                flash = f"Recette « {name} » mise à jour avec succès !"
            else:
                db.add_recipe(
                    name=name,
                    portions_base=int(portions_base),
                    image_bytes=image_bytes,
                    image_mime=image_mime,
                    sections=sections,
                    instructions=instructions,
                    tags=tags,
                    description=description,
                    prep_time_minutes=int(prep_time) or None,
                    cook_time_minutes=int(cook_time) or None,
                    created_by=current_user,
                )
                flash = f"Recette « {name} » enregistrée avec succès !"
        except db.IntegrityError:
            st.error(f"Une recette nommée « {name} » existe déjà. Choisissez un autre nom.")
        else:
            st.session_state["_flash_success"] = flash
            st.session_state["_pending_reset"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Recettes déjà enregistrées (consultation / modification / suppression)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Recettes déjà enregistrées")

existing = db.get_all_recipes()

if not existing:
    st.info("Aucune recette enregistrée pour l'instant.")
else:
    for name, data in existing.items():
        with st.expander(f"{name} — base : {data['portions_base']} personne(s)"):
            cols = st.columns([1, 2])
            with cols[0]:
                img = common.get_recipe_image(name, data["image"])
                st.image(img, use_container_width=True)
            with cols[1]:
                if data.get("tags"):
                    st.markdown(" ".join(f"`{t}`" for t in data["tags"]))

                meta_bits = []
                prep = common.format_time_minutes(data.get("prep_time_minutes"))
                cook = common.format_time_minutes(data.get("cook_time_minutes"))
                if prep:
                    meta_bits.append(f"⏱️ Préparation : {prep}")
                if cook:
                    meta_bits.append(f"🔥 Cuisson : {cook}")
                if meta_bits:
                    st.caption(" · ".join(meta_bits))

                if data.get("description"):
                    st.markdown(f"*{data['description']}*")

                if data.get("created_by"):
                    author_line = f"👤 Ajoutée par **{data['created_by']}** le {common.format_datetime(data.get('created_at'))}"
                    if data.get("updated_by") and data.get("updated_at") != data.get("created_at"):
                        author_line += f"  \n✏️ Dernière modification par **{data['updated_by']}** le {common.format_datetime(data.get('updated_at'))}"
                    st.caption(author_line)

                for section_name, rows in data["ingredients"].items():
                    st.markdown(f"**{section_name}**")
                    for ingredient_name, qty, unit in rows:
                        qty_str = common.format_quantity(Fraction(str(qty)).limit_denominator(100))
                        st.markdown(f"- {qty_str} {unit} de {ingredient_name}")
                if data["instructions"]:
                    st.markdown("**Préparation**")
                    for i, step in enumerate(data["instructions"], start=1):
                        st.markdown(f"{i}. {step}")

            if auth.is_admin():
                btn_cols = st.columns(2)
                if btn_cols[0].button("✏️ Modifier", key=f"editrecipe_{data['id']}", use_container_width=True):
                    st.session_state["_pending_edit_id"] = data["id"]
                    st.rerun()
                if btn_cols[1].button("🗑️ Supprimer", key=f"delrecipe_{data['id']}", use_container_width=True):
                    db.delete_recipe(data["id"])
                    st.session_state["_flash_success"] = f"Recette « {name} » supprimée."
                    st.rerun()
            else:
                st.caption("🔒 La modification et la suppression sont réservées aux administrateurs.")
