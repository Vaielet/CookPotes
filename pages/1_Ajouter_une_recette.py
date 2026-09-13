"""
Page 1 — Ajouter / modifier une recette.

Réservée aux utilisateurs connectés avec le statut éditeur (ou admin).
Un même formulaire sert à la fois pour créer une nouvelle recette et pour
corriger une recette existante (bouton "✏️ Modifier" dans la liste en bas
de page).

Note technique sur le formulaire dynamique (sections/ingrédients) :
Streamlit interdit de modifier st.session_state[key] APRÈS que le widget
portant cette key a déjà été instancié dans le run en cours. Toute remise à
zéro ou pré-remplissage du formulaire (ajout RÉUSSI, modification RÉUSSIE,
passage en mode édition, annulation) se fait donc via un drapeau traité
tout en haut du script, AVANT la création des widgets.
"""

import uuid
from fractions import Fraction

import streamlit as st

import auth
import db
import common

st.set_page_config(page_title="Ajouter une recette", layout="wide")

db.init_db()

#common.header_logo()

auth.require_editor()

common.icon_title("Ajouter une recette", "ajouter_une_recette.png", "🍳")
st.caption(
    "Encode une nouvelle recette. Les nouvelles recettes sont enregistrés dans la base "
    "de données et disponibles pour tou·tes les CookPotes"
    " immédiatement sur la page « Composer mon menu »."
)
st.badge("Rappelle-toi, tu es le contrôle qualité : ne partage "
    "que des recettes que tu as testées et approuvées.", color="green")


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


def _gkey(base: str) -> str:
    """
    Clé de widget suffixée par la "génération" courante du formulaire (voir
    _blank_form_state/_load_edit_form_state) — plutôt que de compter sur le
    simple retrait d'une clé FIXE de session_state pour qu'un widget se
    réaffiche vide. Les deux approches sont documentées comme valides côté
    Streamlit, mais en pratique, sur cette appli, seule la clé-qui-change
    s'est révélée fiable (déjà utilisée pour les lignes d'ingrédients et la
    photo — les seuls champs qui se réinitialisaient vraiment) : les champs
    à clé fixe (nom, portions, description...) restaient remplis après un
    simple .pop(), malgré un traitement du drapeau de réinitialisation bien
    placé avant tout widget. On généralise donc ici la technique qui
    fonctionne déjà, à tous les champs.
    """
    return f"{base}_{st.session_state['_form_generation']}"


def _blank_form_state() -> None:
    old_generation = st.session_state.get("_form_generation")

    # Purge les clés de lignes/sections de l'ancien formulaire (un uuid par
    # ligne/section, indépendant de la génération — voir _new_row/_new_section).
    prefixes = ("secname_", "iname_", "iqty_", "iunit_")
    for key in list(st.session_state.keys()):
        if key.startswith(prefixes):
            del st.session_state[key]

    # Purge les clés des champs généraux (nom, portions, description...) de
    # l'ANCIENNE génération — voir _gkey(). Sans ça, ces clés s'accumulent
    # indéfiniment dans session_state au fil des ajouts successifs pendant
    # une même session (fuite de mémoire mineure, sans autre conséquence
    # puisqu'une nouvelle génération ne les regarde jamais).
    if old_generation:
        old_suffix = f"_{old_generation}"
        for key in list(st.session_state.keys()):
            if key.endswith(old_suffix):
                del st.session_state[key]

    st.session_state["_form_generation"] = uuid.uuid4().hex
    st.session_state["form_mode"] = "add"
    st.session_state["form_recipe_id"] = None
    st.session_state["form_existing_image"] = None
    st.session_state["form_existing_image_mime"] = None
    st.session_state["form_created_by"] = None
    st.session_state["form_created_at"] = None
    st.session_state.new_recipe_sections = [_new_section()]
    st.session_state["_uploader_key"] = f"uploader_{uuid.uuid4().hex}"
    st.session_state["_pending_confirm_save"] = False


def _load_edit_form_state(recipe: dict) -> None:
    st.session_state["_form_generation"] = uuid.uuid4().hex  # voir _gkey : jamais d'ancienne valeur qui traîne
    st.session_state["form_mode"] = "edit"
    st.session_state["form_recipe_id"] = recipe["id"]
    st.session_state["form_existing_image"] = recipe["image"]
    st.session_state["form_existing_image_mime"] = recipe["image_mime"]
    st.session_state["form_created_by"] = recipe.get("created_by")
    st.session_state["form_created_at"] = recipe.get("created_at")
    st.session_state.new_recipe_sections = _sections_from_recipe_data(recipe["ingredients"])
    st.session_state[_gkey("new_recipe_name")] = recipe["name"]
    st.session_state[_gkey("new_recipe_portions")] = recipe["portions_base"]
    st.session_state[_gkey("new_recipe_instructions")] = "\n".join(recipe["instructions"])
    st.session_state[_gkey("new_recipe_description")] = recipe.get("description", "") or ""
    st.session_state[_gkey("new_recipe_prep_time")] = recipe.get("prep_time_minutes") or 0
    st.session_state[_gkey("new_recipe_cook_time")] = recipe.get("cook_time_minutes") or 0

    # Répartit les tags existants entre ceux qui figurent dans la liste
    # suggérée (multiselect) et les tags personnalisés (champ texte libre).
    existing_tags = recipe.get("tags", [])
    known_lower = {t.lower() for t in common.COMMON_TAGS}
    preset_tags = [t for t in existing_tags if t.lower() in known_lower]
    custom_tags = [t for t in existing_tags if t.lower() not in known_lower]
    st.session_state[_gkey("new_recipe_tags_select")] = preset_tags
    st.session_state[_gkey("new_recipe_tags_custom")] = ", ".join(custom_tags)

    st.session_state["_uploader_key"] = f"uploader_{uuid.uuid4().hex}"
    st.session_state["_pending_confirm_save"] = False


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
    "Nom de la recette", key=_gkey("new_recipe_name"), placeholder="ex : Curry de pois chiches",
    max_chars=common.MAX_TITLE_CHARS
)
portions_base = c2.number_input(
    "Nombre de personnes (base)", min_value=1, step=1, key=_gkey("new_recipe_portions")
)

time_cols = st.columns(2)
prep_time = time_cols[0].number_input(
    "⏱️ Temps de préparation (minutes)", min_value=0, step=5, key=_gkey("new_recipe_prep_time")
)
cook_time = time_cols[1].number_input(
    "🔥 Temps de cuisson (minutes)", min_value=0, step=5, key=_gkey("new_recipe_cook_time")
)

description = st.text_area(
    "Un mot sur cette recette — pourquoi vous l'aimez bien (optionnel)",
    key=_gkey("new_recipe_description"),
    max_chars=common.MAX_DESCRIPTION_CHARS,
    height=80,
    placeholder="Le plat réconfortant de mamie, parfait les soirs d'hiver...",
)
st.caption(f"{len(st.session_state.get(_gkey('new_recipe_description')) or '')}/{common.MAX_DESCRIPTION_CHARS} caractères")

st.markdown("**Catégories**")
tag_cols = st.columns([2, 2])
selected_preset_tags = tag_cols[0].multiselect(
    "Catégories suggérées",
    options=common.COMMON_TAGS,
    key=_gkey("new_recipe_tags_select"),
)
custom_tags_text = tag_cols[1].text_input(
    "Autres catégories (séparées par des virgules)",
    key=_gkey("new_recipe_tags_custom"),
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
    + ("Modifier la photo actuelle" if editing and existing_image else "Ajouter une photo")
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

sorted_units = sorted(common.COMMON_UNITS)  # avant la boucle
OTHER_OPTION = "Autre (préciser)…"
options_with_other = sorted_units + [OTHER_OPTION]

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
            current_selection = row["unit"] if row["unit"] in sorted_units else OTHER_OPTION

            selection = r3.selectbox(
                "Unité",
                options=options_with_other,
                index=options_with_other.index(current_selection),
                key=f"iunit_select_{row['id']}", label_visibility="collapsed",
            )
            
            if selection == OTHER_OPTION:
                row["unit"] = r3.text_input(
                    "Unité personnalisée",
                    value=row["unit"] if row["unit"] not in sorted_units else "",
                    key=f"iunit_custom_{row['id']}", label_visibility="collapsed",
                    placeholder="Nouvelle unité",
                )
            else:
                row["unit"] = selection
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
    key=_gkey("new_recipe_instructions"),
    height=150,
    placeholder="Épluchez et coupez les légumes...\nFaites revenir dans l'huile d'olive...\n...",
)


# ---------------------------------------------------------------------------
# Produits pas encore répertoriés — classement facultatif à la volée
# ---------------------------------------------------------------------------
#
# Calculé à partir des ingrédients tapés ci-dessus (avant harmonisation),
# pour chaque nom qui ne correspond à aucun produit connu, ou correspond à
# un produit existant mais sans rayon assigné (ex: importé depuis Open
# Food Facts sans classement). Entièrement facultatif : la recette
# s'enregistre normalement même si rien n'est renseigné ici — voir le
# traitement à l'enregistrement plus bas, qui enregistre quand même
# chaque produit (avec ou sans rayon) pour qu'il ne soit plus jamais
# proposé comme "nouveau" une fois tapé une première fois.

def _typed_ingredient_names() -> list[str]:
    names, seen = [], set()
    for sec in st.session_state.new_recipe_sections:
        for row in sec["rows"]:
            raw = row["name"].strip()
            if raw and raw.lower() not in seen:
                seen.add(raw.lower())
                names.append(raw)
    return names


NEW_CATEGORY_PLACEHOLDER = "— à définir plus tard —"

to_classify = [
    (raw, common.find_product(raw))
    for raw in _typed_ingredient_names()
]
to_classify = [(raw, product) for raw, product in to_classify if common.is_unclassified(product)]

if to_classify:
    st.subheader("🏷️ Nouveaux produits détectés")
    st.caption(
        "Ces ingrédients ne sont pas encore répertoriés dans la base de "
        "produits (ils n'ont pas encore de rayon ou de synonymes). Classe-les dans un des rayons prédéfinis "
        "et ajoute leurs synonymes")  
    st.badge("Le classement des ingrédients permet de générer une liste de courses "
             "mieux organisée, gain de temps pour tout le monde !", color="green")

    header_cols = st.columns([2, 2, 3])
    header_cols[0].markdown("**Ingrédient**")
    header_cols[1].markdown("**Rayon**")
    header_cols[2].markdown("**Synonymes**")
    for raw, product in to_classify:
        raw_key = raw.strip().lower()
        row_cols = st.columns([2, 2, 3])
        row_cols[0].markdown(raw)
        row_cols[1].selectbox(
            "Rayon", options=[NEW_CATEGORY_PLACEHOLDER] + common.CATEGORY_ORDER,
            key=f"newprod_cat_{raw_key}", label_visibility="collapsed",
        )
        row_cols[2].text_input(
            "Synonymes", value=", ".join(product["synonyms"]) if product else "",
            key=f"newprod_syn_{raw_key}", label_visibility="collapsed",
            placeholder="ex : courgette, courgettes vertes",
        )


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------

st.divider()

save_label = "💾 Enregistrer les modifications" if editing else "💾 Enregistrer la recette"

if st.button(save_label, type="primary"):
    st.session_state["_pending_confirm_save"] = True

# Cette partie (validation, puis confirmation, puis enregistrement réel)
# est traitée en dehors du `if` du bouton ci-dessus, à partir d'un
# drapeau dans session_state : sinon, le bouton "✅ Oui, tout est
# correct" ci-dessous — cliqué lors d'un rerun SÉPARÉ de celui où
# "Enregistrer" a été cliqué — ne serait jamais rendu (même piège que
# celui déjà documenté plus haut pour le formulaire dynamique). La
# validation est refaite à chaque passage ici (pas seulement au premier
# clic) pour toujours refléter la dernière version des champs, y compris
# si la personne corrige quelque chose entre le clic sur "Enregistrer" et
# la confirmation.
if st.session_state.get("_pending_confirm_save"):
    errors = []

    name = recipe_name.strip()
    if not name:
        errors.append("Le nom de la recette est obligatoire.")

    sections = {}
    for sec in st.session_state.new_recipe_sections:
        section_name = sec["name"].strip() or "Plat"
        valid_rows = []
        for row in sec["rows"]:
            raw_name = row["name"].strip()
            if raw_name and row["qty"] > 0:
                # Harmonise le nom tapé librement avec la base de produits
                # (voir common.PRODUCTS) : "courgettes vertes" devient
                # "Courgette", etc. Un produit non reconnu est simplement
                # conservé tel quel (juste remis en forme).
                canonical_name, _category = common.match_product(raw_name)
                valid_rows.append((canonical_name, row["qty"], row["unit"]))
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
        # Erreurs à corriger : on annule la confirmation en cours plutôt
        # que de la laisser réapparaître sur un formulaire invalide tant
        # que rien n'a changé.
        st.session_state["_pending_confirm_save"] = False
    else:
        # Un seul st.warning() (pas plusieurs st.markdown séparés) : c'est
        # le seul moyen que tout — explication ET liste d'ingrédients —
        # apparaisse DANS le même rectangle jaune. La liste d'ingrédients
        # est formatée comme une vraie liste à puces Markdown (pas des
        # lignes séparées par des sauts de paragraphe) : c'est ce qui lui
        # donne un interligne compact, sans espace superflu entre chaque
        # ingrédient.
        warning_lines = [
            "⚠️ **As-tu bien vérifié les quantités et les unités de chaque ingrédient ?**",
            "",
            "*Elles servent à générer automatiquement la liste de courses de "
            "tou·tes les CookPotes qui composeront un menu avec cette recette : "
            "une quantité ou une unité incorrecte fausse toute la liste, et la "
            "personne qui fait les courses n'achètera pas la bonne quantité.*",
            "",
            f"**La liste d'ingrédients pour {int(portions_base)} personne(s) est :**",
        ]
        for section_name, rows in sections.items():
            if len(sections) > 1:
                warning_lines.append(f"**{section_name}**")
            for ingredient_name, qty, unit in rows:
                qty_str = common.format_quantity(Fraction(str(qty)).limit_denominator(100))
                unit_str = f" {unit}" if unit and unit != "unité" else ""
                warning_lines.append(f"* {ingredient_name} : {qty_str}{unit_str}")

        st.warning("\n".join(warning_lines))

        confirm_cols = st.columns(2)
        if confirm_cols[0].button(
            "✅ Oui, tout est correct — enregistrer", type="primary", use_container_width=True,
        ):
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
                st.session_state["_pending_confirm_save"] = False
            else:
                # Enregistre/complète chaque produit détecté ci-dessus, qu'il
                # ait été classé ou laissé "à définir plus tard" — dans les
                # deux cas, il est reconnu la prochaine fois qu'il est tapé,
                # au lieu de redemander sans cesse la même chose.
                for raw, product in to_classify:
                    raw_key = raw.strip().lower()
                    category_choice = st.session_state.get(f"newprod_cat_{raw_key}", NEW_CATEGORY_PLACEHOLDER)
                    category_value = None if category_choice == NEW_CATEGORY_PLACEHOLDER else category_choice
                    synonyms_text = st.session_state.get(f"newprod_syn_{raw_key}", "")
                    synonyms_list = [s.strip() for s in synonyms_text.split(",") if s.strip()]
                    if raw.strip().lower() not in [s.lower() for s in synonyms_list]:
                        synonyms_list.append(raw.strip())
                    canonical_name = product["canonical"] if product else raw.strip().capitalize()
                    db.upsert_product(canonical_name, category_value, synonyms_list)
                    st.session_state.pop(f"newprod_cat_{raw_key}", None)
                    st.session_state.pop(f"newprod_syn_{raw_key}", None)

                st.session_state["_flash_success"] = flash
                st.session_state["_pending_reset"] = True
                st.session_state["_pending_confirm_save"] = False
                st.rerun()

        if confirm_cols[1].button("Annuler", use_container_width=True):
            st.session_state["_pending_confirm_save"] = False
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

                delete_confirm_key = f"confirm_delete_{data['id']}"
                if btn_cols[1].button("🗑️ Supprimer", key=f"delrecipe_{data['id']}", use_container_width=True):
                    st.session_state[delete_confirm_key] = True
                    st.rerun()

                if st.session_state.get(delete_confirm_key):
                    st.warning(f"Es-tu sûr·e de vouloir supprimer « {name} » ? Cette action est irréversible.")
                    confirm_cols = st.columns(2)
                    if confirm_cols[0].button(
                        "✅ Oui, supprimer définitivement", key=f"confirmdel_{data['id']}",
                        type="primary", use_container_width=True,
                    ):
                        db.delete_recipe(data["id"])
                        st.session_state.pop(delete_confirm_key, None)
                        st.session_state["_flash_success"] = f"Recette « {name} » supprimée."
                        st.rerun()
                    if confirm_cols[1].button(
                        "Annuler", key=f"canceldel_{data['id']}", use_container_width=True,
                    ):
                        st.session_state.pop(delete_confirm_key, None)
                        st.rerun()
            else:
                st.caption("🔒 La modification et la suppression sont réservées aux administrateurs.")
