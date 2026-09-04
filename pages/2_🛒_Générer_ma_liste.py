"""
Page 2 — Générer ma liste.

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


def render_share_widget(text: str, height: int = 90) -> None:
    """
    Affiche deux boutons — « Copier » et « Partager » — basés sur des API
    standard du navigateur, qui fonctionnent quel que soit l'appareil
    (Windows, macOS, Linux, iOS, Android) :

    - Copier : copie le texte dans le presse-papiers (navigator.clipboard,
      avec un repli via document.execCommand pour les navigateurs plus
      restrictifs). L'utilisateur colle ensuite où il veut (Notes, Google
      Keep, WhatsApp, un mail...).
    - Partager : ouvre le sélecteur de partage natif du système
      (navigator.share) quand le navigateur le supporte — très répandu sur
      mobile (iOS/Android), et de plus en plus sur desktop. Le bouton reste
      caché s'il n'est pas supporté.
    """
    safe_text = json.dumps(text)

    components.html(
        f"""
        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
          <button id="copy-btn" style="
              padding:0.5em 1em; border-radius:8px; border:1px solid #ccc;
              background:#f0f0f0; cursor:pointer; font-size:0.95em;">
            📋 Copier
          </button>
          <button id="share-btn" style="
              padding:0.5em 1em; border-radius:8px; border:1px solid #ccc;
              background:#f0f0f0; cursor:pointer; font-size:0.95em; display:none;">
            📤 Partager...
          </button>
          <span id="copy-status" style="font-size:0.9em; color:green;"></span>
        </div>
        <script>
          const text = {safe_text};

          const copyBtn = document.getElementById("copy-btn");
          const status = document.getElementById("copy-status");
          copyBtn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText(text);
              status.textContent = "Copié !";
            }} catch (err) {{
              const ta = document.createElement("textarea");
              ta.value = text;
              ta.style.position = "fixed";
              ta.style.opacity = "0";
              document.body.appendChild(ta);
              ta.focus();
              ta.select();
              try {{
                document.execCommand("copy");
                status.textContent = "Copié !";
              }} catch (err2) {{
                status.textContent = "Copie auto impossible, sélectionne le texte à la main.";
              }}
              document.body.removeChild(ta);
            }}
            setTimeout(() => {{ status.textContent = ""; }}, 2500);
          }});

          const shareBtn = document.getElementById("share-btn");
          if (navigator.share) {{
            shareBtn.style.display = "inline-block";
            shareBtn.addEventListener("click", async () => {{
              try {{
                await navigator.share({{ text: text, title: "Liste de courses" }});
              }} catch (err) {{
                // Annulé par l'utilisateur, ou non supporté : rien à faire.
              }}
            }});
          }}
        </script>
        """,
        height=height,
    )

st.set_page_config(page_title="Générer ma liste", page_icon="🛒", layout="wide")

db.init_db()

common.header_logo()

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
    st.session_state["reference"] = _current_reference().strip()
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
    st.title("🧾 Ta liste de courses")
    if st.button("⬅️ Retour à la sélection des recettes", key="back_to_selection"):
        st.session_state["page_view"] = "selection"
        st.rerun()

    choices = st.session_state.get("choices") or []
    choices = [c for c in choices if c.name in recipes]
    if not choices:
        st.warning("Les recettes sélectionnées ne sont plus disponibles. Merci de refaire votre sélection.")
        st.stop()

    reference = st.session_state.get("reference", "")

    # --- Liste de courses ---
    st.header("Liste de courses")

    shopping = common.build_shopping_list(choices, recipes)
    grouped = shopping.as_grouped_lines()

    shopping_title = reference or "Liste de courses de la semaine"
    shopping_text = common.build_shopping_text(shopping_title, grouped)

    st.download_button(
        "📄 Télécharger la liste de courses (.txt)",
        data=shopping_text,
        file_name="liste_de_courses.txt",
        mime="text/plain",
    )

    st.caption("Ou copie/partage-la directement, où que tu sois (PC, mobile, tablette) :")
    render_share_widget(shopping_text)

    # --- Carnet de recettes PDF ---
    st.header("Carnet de recettes")
    booklet_title = f"Carnet de recettes — {reference}" if reference else "Carnet de recettes de la semaine"
    with st.spinner("Génération du carnet de recettes..."):
        pdf_bytes = common.build_recipe_booklet_pdf(choices, recipes, title=booklet_title)

    st.download_button(
        "📕 Télécharger le carnet de recettes (PDF)",
        data=pdf_bytes,
        file_name="carnet_de_recettes.pdf",
        mime="application/pdf",
    )

    st.stop()

# --- Vue sélection des recettes ---

title_col, cart_col = st.columns([5, 2])
with title_col:
    st.title("🛒 Générer ma liste")
with cart_col:
    st.write("")
    with st.popover(f"🛒 Mon panier ({len(cart_ids)})", use_container_width=True):
        st.markdown("#### 🛒 Mon panier")
        if not cart_ids:
            st.caption("Ton panier est vide pour l'instant — ajoute des recettes ci-dessous.")
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
            if st.button("🗑️ Vider le panier", key="cart_clear_all", use_container_width=True):
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
                "🧾 Générer la liste de courses",
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
# Grille de recettes responsive — cartes à largeur fixe, nombre de colonnes
# qui s'adapte à la largeur de l'écran (façon e-shop).
# ---------------------------------------------------------------------------
# st.columns() ne permet pas nativement un vrai flux de type CSS grid : les
# colonnes se rétrécissent mais ne repassent jamais à la ligne. On simule ça
# en demandant à chaque fois GRID_COLUMNS colonnes (le maximum voulu sur
# grand écran), puis en forçant en CSS ces colonnes à une largeur fixe et à
# passer à la ligne (flex-wrap) quand elles ne tiennent plus — le
# navigateur affiche alors automatiquement 1 carte par ligne sur mobile, 2
# sur tablette, jusqu'à GRID_COLUMNS sur grand écran, sans aucun JS.
GRID_COLUMNS = 4
CARD_MIN_WIDTH_PX = 260
CARD_MAX_WIDTH_PX = 320

st.markdown(
    f"""
    <style>
    .st-key-recipe_grid div[data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap;
        row-gap: 1.5rem;
    }}
    .st-key-recipe_grid div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
        flex: 1 1 {CARD_MIN_WIDTH_PX}px;
        min-width: {CARD_MIN_WIDTH_PX}px;
        max-width: {CARD_MAX_WIDTH_PX}px;
        width: {CARD_MIN_WIDTH_PX}px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="recipe_grid"):
    columns = []
    for i, name in enumerate(names):
        if i % GRID_COLUMNS == 0:
            columns = st.columns(GRID_COLUMNS, gap="medium")
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
                        for section_name, rows in recipe["ingredients"].items():
                            for ingredient_name, qty, unit in rows:
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
                        "✅ Dans le panier — retirer",
                        key=f"cartbtn_{recipe['id']}",
                        use_container_width=True,
                    ):
                        cart_ids.discard(recipe["id"])
                        st.rerun()
                else:
                    if st.button(
                        "Ajouter au panier",
                        key=f"cartbtn_{recipe['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        cart_ids.add(recipe["id"])
                        st.rerun()

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
