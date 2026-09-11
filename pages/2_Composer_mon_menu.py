"""
Page 2 — Composer mon menu.

L'utilisateur choisit des recettes parmi celles enregistrées en base
(avec recherche, filtre par catégorie et par auteur·rice), le nombre de
personnes pour chacune via un bouton « Ajouter au panier » façon e-shop
(un menu panier en haut à droite récapitule la sélection), puis génère :
  - la liste de courses agrégée et regroupée par rayon
    (téléchargement .txt, copie dans le presse-papiers, ou partage natif
    vers n'importe quelle appli — Notes, WhatsApp, Mail... — sur mobile
    comme sur desktop)
  - un carnet de recettes en PDF (téléchargement)
"""

import html
import json
from fractions import Fraction

import streamlit as st
import streamlit.components.v1 as components

import auth
import db
import common
from common import RecipeChoice

db.init_db()

#common.header_logo()

auth.render_sidebar_auth()  # affichage informatif ; cette page reste accessible sans connexion

recipes = db.get_all_recipes()

if not recipes:
    st.warning(
        "Aucune recette n'est enregistrée pour l'instant. "
        "Rends-toi sur la page « 🍳 Ajouter une recette » pour commencer."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Panier — état persistant (style e-shop)
# ---------------------------------------------------------------------------
# Un set d'ids de recettes ajoutées au panier. On l'indexe par id (et non
# par nom filtré affiché à l'écran) pour que le panier reste cohérent même
# si l'utilisateur·rice change la recherche/les filtres entre-temps : une
# recette ajoutée au panier y reste, qu'elle soit visible ou non dans la
# grille à un instant donné.
if "cart" not in st.session_state:
    st.session_state["cart"] = set()

recipes_by_id = {r["id"]: (name, r) for name, r in recipes.items()}

# Filet de sécurité : si une recette du panier a été supprimée entre-temps.
st.session_state["cart"] &= set(recipes_by_id.keys())
cart_ids: set[int] = st.session_state["cart"]


def _people_key(recipe_id: int, widget: str) -> str:
    """Nom de la clé session_state pour le sélecteur de personnes d'une recette,
    selon l'endroit où il est affiché (`card` = grille de recettes, `cart` = menu panier)."""
    return f"people_{widget}_{recipe_id}"


def _people_for(recipe_id: int, default: int) -> int:
    """
    Nombre de personnes actuellement choisi pour une recette, quel que soit
    le widget (carte ou panier) qui a été utilisé en dernier pour le régler.
    """
    for widget in ("card", "cart"):
        key = _people_key(recipe_id, widget)
        if key in st.session_state:
            return int(st.session_state[key])
    return int(default)


def _sync_people(recipe_id: int, changed_widget: str) -> None:
    """
    Callback appelé quand le nombre de personnes est modifié depuis la
    carte OU depuis le panier : reporte la nouvelle valeur sur l'autre
    widget (même clé sous-jacente impossible car deux number_input
    distincts affichent la même quantité à deux endroits de l'écran).
    """
    other_widget = "cart" if changed_widget == "card" else "card"
    changed_key = _people_key(recipe_id, changed_widget)
    other_key = _people_key(recipe_id, other_widget)
    st.session_state[other_key] = st.session_state[changed_key]


# Construit la sélection à partir du panier (persistant), pas seulement des
# recettes actuellement visibles à l'écran — une recette ajoutée au panier
# reste sélectionnée même si elle sort de la recherche/du filtre actif.
# Calculé ici (avant l'affichage du panier) car le bouton « Générer » du
# menu panier en a besoin, en plus de celui tout en bas de la page.
selected_choices: list[RecipeChoice] = [
    RecipeChoice(recipes_by_id[rid][0], _people_for(rid, recipes_by_id[rid][1]["portions_base"]))
    for rid in cart_ids
]

# Le champ « Référence » existe à deux endroits (menu panier + bas de page) ;
# les deux widgets sont synchronisés comme le nombre de personnes ci-dessus.
REFERENCE_MAIN_KEY = "reference_main"
REFERENCE_CART_KEY = "reference_cart"


def _current_reference() -> str:
    for key in (REFERENCE_CART_KEY, REFERENCE_MAIN_KEY):
        if key in st.session_state:
            return st.session_state[key]
    return ""


def _sync_reference(changed_key: str, other_key: str) -> None:
    st.session_state[other_key] = st.session_state[changed_key]


def _generate_shopping_list() -> None:
    """Callback partagé par le bouton du panier et celui tout en bas de page."""
    st.session_state["choices"] = selected_choices
    st.session_state["reference"] = _current_reference().strip() or "Mon menu"
    st.session_state["page_view"] = "results"


# ---------------------------------------------------------------------------
# Navigation entre la page de sélection des recettes et la page de résultats
# ---------------------------------------------------------------------------
if "page_view" not in st.session_state:
    st.session_state["page_view"] = "selection"

view = st.session_state["page_view"]
# Filet de sécurité : pas de résultats valides (ex. app relancée) → retour à la sélection.
if view == "results" and not st.session_state.get("choices"):
    st.session_state["page_view"] = "selection"
    view = "selection"

if view == "results":
    top_col, back_col = st.columns([5, 2],vertical_alignment="center")
    with top_col:
        common.icon_title("Composer mon menu", "generer_mon_menu.png", "🛒")
    with back_col:
        if st.button("⬅️ Retour à la sélection", key="back_to_selection", use_container_width=True):
          st.session_state["page_view"] = "selection"
          st.rerun()
          
    st.header(st.session_state["reference"])
    choices = st.session_state.get("choices") or []
    choices = [c for c in choices if c.name in recipes]
    if not choices:
        st.warning("Les recettes sélectionnées ne sont plus disponibles. Merci de refaire votre sélection.")
        st.stop()

    reference = st.session_state.get("reference", "")

    shopping = common.build_shopping_list(choices, recipes)
    grouped = shopping.as_grouped_lines()

    shopping_title = reference or "Liste de courses de la semaine"
    shopping_text = common.build_shopping_text(shopping_title, grouped)
    booklet_title = f"Carnet de recettes — {reference}" if reference else "Carnet de recettes de la semaine"

    list_col, booklet_col = st.columns(2, gap="large")

    # --- Bloc liste de courses ---
    with list_col:
        with st.container(border=True):
            st.subheader("🧾 Liste de courses")
            st.download_button(
                "📄 Télécharger (.txt)",
                data=shopping_text,
                file_name="liste_de_courses.txt",
                mime="text/plain",
                use_container_width=True,
            )
            #st.caption("Ou copie/partage-la directement, où que tu sois (PC, mobile, tablette) :")
            common.render_share_widget(shopping_text)

    # --- Bloc carnet de recettes ---
    with booklet_col:
        with st.container(border=True):
            st.subheader("📕 Carnet de recettes")
            with st.spinner("Génération du carnet de recettes..."):
                pdf_bytes = common.build_recipe_booklet_pdf(choices, recipes, title=booklet_title)
            st.download_button(
                "📕 Télécharger le PDF",
                data=pdf_bytes,
                file_name="carnet_de_recettes.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

    st.divider()

    # --- Enregistrement sur le compte (concerne les deux blocs ci-dessus) ---
    if auth.is_logged_in():
        if st.button("💾 Enregistrer ce menu dans mon compte", type="primary", use_container_width=True):
            try:
                db.save_shopping_list(
                    user_id=auth.current_user_id(),
                    reference=reference,
                    recipe_choices=[(c.name, c.people) for c in choices],
                    grouped_items=grouped,
                )
            except db.SavedListLimitReached as exc:
                st.error(str(exc))
                st.page_link("pages/5_Mes_menus.py", label="📋 Aller à Mes menus", icon="📋")
            else:
                st.success(
                    "Menu enregistré ! Retrouve-le, coche les articles au fur "
                    "et à mesure de tes courses, et affiche tes recettes sur la page « 📋 Mes menus »."
                )
                st.page_link("pages/5_Mes_menus.py", label="📋 Aller à Mes menus", icon="📋")
    else:
        st.caption(
            "🔒 Connecte-toi (menu de gauche) pour enregistrer ce menu "
            "sur ton compte, cocher les articles au fur et à mesure de tes "
            "courses, et retrouver les recettes."
        )

    st.stop()


# --- Vue sélection des recettes ---

title_col, cart_col = st.columns([5, 2],vertical_alignment="center")
with title_col:
    common.icon_title("Composer mon menu", "generer_mon_menu.png", "🛒")
with cart_col:
    st.write("")
    with st.popover(f"Mon menu ({len(cart_ids)})", use_container_width=True):
        st.markdown("#### Mon menu")
        if not cart_ids:
            st.caption("Ton menu est vide pour l'instant — ajoute des recettes ci-dessous.")
        else:
            for rid in sorted(cart_ids, key=lambda i: recipes_by_id[i][0].lower()):
                name, recipe = recipes_by_id[rid]
                name_col, qty_col, remove_col = st.columns([3, 2, 1])
                name_col.markdown(f"**{name}**")
                qty_col.number_input(
                    "Personnes",
                    min_value=1,
                    value=_people_for(rid, recipe["portions_base"]),
                    step=1,
                    key=_people_key(rid, "cart"),
                    on_change=_sync_people,
                    args=(rid, "cart"),
                    label_visibility="collapsed",
                )
                if remove_col.button("✕", key=f"cart_popover_remove_{rid}", help="Retirer du panier"):
                    cart_ids.discard(rid)
                    st.rerun()
            st.divider()
            if st.button("🗑️ Vider le menu", key="cart_clear_all", use_container_width=True):
                cart_ids.clear()
                st.rerun()

            st.divider()
            st.text_input(
                "📝 Référence (optionnel)",
                placeholder="ex. : Repas de la semaine du 10 mai",
                value=_current_reference(),
                key=REFERENCE_CART_KEY,
                on_change=_sync_reference,
                args=(REFERENCE_CART_KEY, REFERENCE_MAIN_KEY),
            )
            if st.button(
                "🧾 Générer la liste de courses et le carnet de recette",
                key="cart_generate",
                type="primary",
                use_container_width=True,
            ):
                _generate_shopping_list()
                st.rerun()

all_tags = db.get_all_tags()
all_authors = db.get_all_authors()

search_query = st.text_input(
    "🔎 Rechercher une recette (titre ou ingrédient)",
    placeholder="ex. : poulet, courgette, curry...",
).strip().lower()

filter_cols = st.columns(2)
tag_filter = []
if all_tags:
    tag_filter = filter_cols[0].multiselect(
        "🏷️ Filtrer par catégorie (optionnel)",
        options=all_tags,
        help="Affiche uniquement les recettes ayant au moins une des catégories sélectionnées.",
    )

author_filter = []
if all_authors:
    author_filter = filter_cols[1].multiselect(
        "👤 Filtrer par auteur·rice (optionnel)",
        options=all_authors,
        help="Affiche uniquement les recettes ajoutées par les auteurs sélectionnés.",
    )


def _matches_search(recipe_name: str, recipe: dict, query: str) -> bool:
    """Vrai si le terme recherché apparaît dans le titre OU dans le nom d'un ingrédient."""
    if not query:
        return True
    if query in recipe_name.lower():
        return True
    for rows in recipe["ingredients"].values():
        for ingredient_name, _qty, _unit in rows:
            if query in ingredient_name.lower():
                return True
    return False


names = list(recipes.keys())
if search_query:
    names = [name for name in names if _matches_search(name, recipes[name], search_query)]
if tag_filter:
    names = [name for name in names if set(recipes[name].get("tags", [])) & set(tag_filter)]
if author_filter:
    names = [name for name in names if recipes[name].get("created_by") in author_filter]

if (search_query or tag_filter or author_filter) and not names:
    st.info("Aucune recette ne correspond à ta recherche/filtre.")

# ---------------------------------------------------------------------------
# Grille de recettes responsive — cartes à largeur FIXE (jamais étirées ni
# compressées), nombre de colonnes par ligne qui s'adapte à la largeur de
# l'écran (façon e-shop).
# ---------------------------------------------------------------------------
# st.columns() ne permet pas nativement un vrai flux de type CSS grid : les
# colonnes se rétrécissent mais ne repassent jamais à la ligne. On simule ça
# en demandant à chaque fois GRID_COLUMNS colonnes (le maximum voulu sur
# grand écran), puis en forçant en CSS ces colonnes à une largeur fixe et à
# passer à la ligne (flex-wrap) quand elles ne tiennent plus.
#
# `flex: 0 0 CARD_WIDTH_PXpx` (au lieu de `flex: 1 1 ...`) est le point
# important : flex-grow à 0 empêche les cartes de s'ÉTIRER pour remplir la
# ligne (ce qui arrivait avant quand il restait de la place, donnant
# l'impression que la taille "respirait" selon la largeur de fenêtre), et
# flex-shrink à 0 les empêche de se COMPRESSER. Résultat : une taille de
# carte strictement identique quelle que soit la largeur d'écran — seul le
# nombre de cartes par ligne change (calculé par le navigateur via
# flex-wrap, sans JS).
GRID_COLUMNS = 4
CARD_WIDTH_PX = 300  # ordinateur : taille strictement fixe (ne rétrécit jamais)
CARD_MIN_WIDTH_PX = 280  # smartphone : peut rétrécir jusqu'à cette largeur
CARD_MAX_WIDTH_PX = 350  # smartphone : peut grandir jusqu'à cette largeur
DESKTOP_BREAKPOINT_PX = 768  # au-delà : comportement "ordinateur" (taille fixe)
# `!important` sur toutes ces règles : sur grand écran, Streamlit recalcule
# et réapplique ses propres largeurs de colonnes (en style inline) à chaque
# redimensionnement de fenêtre — un style inline gagne toujours face à une
# règle de feuille de style externe, quelle que soit sa précision, sauf à
# forcer avec !important. `display: flex !important` sur le parent est
# nécessaire en plus : sur certaines largeurs, Streamlit fait apparemment
# passer ce conteneur en CSS Grid plutôt qu'en Flexbox — dans ce cas, TOUTES
# les propriétés flex (flex-grow, flex-shrink, flex-basis) deviennent sans
# effet, puisqu'elles ne s'appliquent qu'à l'intérieur d'un conteneur flex.
#
# Sélecteur SANS ">" (enfant direct) entre stHorizontalBlock et stColumn :
# Streamlit imbrique parfois une div supplémentaire entre les deux —
# un sélecteur descendant (juste un espace) fonctionne quelle que soit la
# profondeur d'imbrication.
#
# `data-testid="stColumn"`, PAS `data-testid="column"` : erreur trouvée
# grâce à une recherche Ctrl+F dans l'inspecteur du navigateur (le seul
# résultat trouvé pour "column" était mon PROPRE bloc <style> injecté, pas
# un vrai élément — donc rien ne matchait jamais, silencieusement, depuis
# le début). Tous les attributs internes de Streamlit sont préfixés "st"
# (stElementContainer, stMarkdown, stHorizontalBlock...) — "column" seul
# n'existe pas dans cette version.
#
# Comportement volontairement DIFFÉRENT selon la taille d'écran : taille de
# carte strictement fixe sur ordinateur (jamais de rétrécissement), mais
# souplesse min/max conservée sur smartphone (comme avant ce changement) —
# géré via une media query CSS plutôt qu'une seule règle pour les deux.

st.markdown(
    f"""
    <style>
    .st-key-recipe_grid div[data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-wrap: wrap !important;
        row-gap: 1.5rem;
    }}

    /* Smartphone (par défaut) : la carte peut rétrécir/grandir dans cet intervalle. */
    .st-key-recipe_grid div[data-testid="stColumn"] {{
        display: block !important;
        flex: 1 1 {CARD_MIN_WIDTH_PX}px !important;
        width: {CARD_MIN_WIDTH_PX}px !important;
        min-width: {CARD_MIN_WIDTH_PX}px !important;
        max-width: {CARD_MAX_WIDTH_PX}px !important;
    }}

    /* Ordinateur : taille strictement fixe, ne varie jamais. */
    @media (min-width: {DESKTOP_BREAKPOINT_PX}px) {{
        .st-key-recipe_grid div[data-testid="stColumn"] {{
            flex: 0 0 {CARD_WIDTH_PX}px !important;
            width: {CARD_WIDTH_PX}px !important;
            min-width: {CARD_WIDTH_PX}px !important;
            max-width: {CARD_WIDTH_PX}px !important;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="recipe_grid"):
    columns = []
    for i, name in enumerate(names):
        if i % GRID_COLUMNS == 0:
            columns = st.columns(GRID_COLUMNS, gap="small")
        col = columns[i % GRID_COLUMNS]

        recipe = recipes[name]
        base = recipe["portions_base"]

        with col:
            with st.container(border=True):
                common.render_recipe_image_card(name, recipe["image"])

                tags_html = "".join(
                    f'<span style="background:#f0f2f6; color:#31333F; border-radius:4px; '
                    f'padding:0.1em 0.45em; margin:0 0.3em 0.3em 0; font-size:0.82em; '
                    f'font-family:monospace; display:inline-block;">{html.escape(t)}</span>'
                    for t in recipe.get("tags", [])
                )

                author_html = (
                    f"👤 Ajoutée par {html.escape(recipe['created_by'])}" if recipe.get("created_by") else ""
                )

                meta_bits = []
                prep = common.format_time_minutes(recipe.get("prep_time_minutes"))
                cook = common.format_time_minutes(recipe.get("cook_time_minutes"))
                if prep:
                    meta_bits.append(f"⏱️ Préparation : {html.escape(prep)}<br>")
                if cook:
                    meta_bits.append(f"🔥 Cuisson : {html.escape(cook)}")
                meta_html = "".join(meta_bits)
                st.markdown(
                    f'<div style="overflow:hidden; margin-bottom:0.9em; '
                    f'color:rgb(120,120,120); font-size:0.85rem;">{meta_html}</div>',
                    unsafe_allow_html=True,
                )

                description_html = html.escape(recipe.get("description") or "")
                
                current_people = _people_for(recipe["id"], base)
                with st.expander("📋 Voir les détails"):
                    st.markdown(
                        f'<div style="overflow:hidden; margin-bottom:0.15em; '
                        f'color:rgb(120,120,120); font-size:0.85rem;">{author_html}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="overflow:hidden; margin-bottom:0.4em; '
                        f'color:rgb(120,120,120); font-size:0.85rem; line-height:1.35;"><i>{description_html}</i></div>',
                        unsafe_allow_html=True,
                    )                    
                    st.markdown(
                        f'<div style="overflow:hidden; font-size:0.85rem; margin-bottom:0.3em;">{tags_html}</div>',
                        unsafe_allow_html=True,
                    )
                    if recipe["ingredients"]:
                        meta_ingredients=[]
                        st.markdown(
                            f'<div style="overflow:hidden; margin-bottom:0.4em; '
                            f'color:rgb(120,120,120); font-size:0.85rem; line-height:1.35;"><b>Ingrédients :</b></div>',
                            unsafe_allow_html=True,
                        )
                        seen_ingredients = set()
                        for section_name, rows in recipe["ingredients"].items():
                            for ingredient_name, qty, unit in rows:
                                key = ingredient_name.strip().lower()
                                if key in seen_ingredients:
                                    continue
                                seen_ingredients.add(key)
                                label = ingredient_name.capitalize()
                                meta_ingredients.append(f"{label}")
                        meta_ingredients_html = " • ".join(meta_ingredients)
                        st.markdown(
                            f'<div style="overflow:hidden; margin-bottom:0.4em; '
                            f'color:rgb(120,120,120); font-size:0.85rem; line-height:1.35;">{meta_ingredients_html}</div>',
                            unsafe_allow_html=True,
                        )

                    else:
                        st.markdown(
                            f'<div style="overflow:hidden; margin-bottom:0.4em; '
                            f'color:rgb(120,120,120); font-size:0.85rem; line-height:1.35;">"Aucun ingrédient renseigné pour cette recette."</div>',
                            unsafe_allow_html=True,
                        )

                people = st.number_input(
                    f"Nombre de personnes",
                    min_value=1,
                    value=current_people,
                    step=1,
                    key=_people_key(recipe["id"], "card"),
                    on_change=_sync_people,
                    args=(recipe["id"], "card"),
                )

                in_cart = recipe["id"] in cart_ids
                if in_cart:
                    if st.button(
                        "✅ Au menu — retirer",
                        key=f"cartbtn_{recipe['id']}",
                        use_container_width=True,
                    ):
                        cart_ids.discard(recipe["id"])
                        st.rerun()
                else:
                    if st.button(
                        "Ajouter à mon menu",
                        key=f"cartbtn_{recipe['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        cart_ids.add(recipe["id"])
                        st.rerun()

    # Vignette "Ajouter une recette", à la fin de la grille, avec le même
    # style de carte que les recettes — sur la même ligne que la dernière
    # carte s'il reste de la place, sinon elle démarre une nouvelle ligne
    # (même logique de colonnes que la boucle ci-dessus).
    add_index = len(names)
    if add_index % GRID_COLUMNS == 0:
        columns = st.columns(GRID_COLUMNS, gap="medium")
    add_col = columns[add_index % GRID_COLUMNS]
    with add_col:
        with st.container(border=True):
            st.markdown(
                '<div style="display:flex; align-items:center; justify-content:center; '
                'aspect-ratio:4/3; background:#f0f2f6; border-radius:0.5rem; '
                'margin-bottom:0.9em; font-size:3rem; color:#8a8f98;">➕</div>',
                unsafe_allow_html=True,
            )
            
            st.markdown(
                '<div style="text-align:center; color:rgb(120,120,120); '
                'font-size:0.9rem; margin-bottom:0.9em;">'
                'Tu connais une recette <br> qui mérite sa place ici ?</div>',
                unsafe_allow_html=True,
            )
            if common.icon_button("Ajouter une recette", "ajouter_une_recette.png", "🍳", key="add_recipe_tile_btn"):
              st.switch_page("pages/1_Ajouter_une_recette.py")


st.divider()

reference = st.text_input(
    "📝 Référence (optionnel)",
    placeholder="ex. : Repas de la semaine du 10 mai",
    help="Apparaît en haut de la liste de courses et dans le titre du carnet de recettes.",
    value=_current_reference(),
    key=REFERENCE_MAIN_KEY,
    on_change=_sync_reference,
    args=(REFERENCE_MAIN_KEY, REFERENCE_CART_KEY),
)

if st.button(
    "🧾 Générer la liste de courses et le carnet de recettes",
    type="primary",
    disabled=len(selected_choices) == 0,
):
    _generate_shopping_list()
    st.rerun()

if len(selected_choices) == 0:
    st.info("Sélectionne au moins une recette pour continuer.")
