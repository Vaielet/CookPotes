"""
Page 2 — Générer ma liste.

L'utilisateur choisit des recettes parmi celles enregistrées en base
(avec un filtre optionnel par catégorie), le nombre de personnes pour
chacune, puis génère :
  - la liste de courses agrégée et regroupée par rayon
    (téléchargement .txt, copie dans le presse-papiers, ou partage natif
    vers n'importe quelle appli — Notes, WhatsApp, Mail... — sur mobile
    comme sur desktop)
  - un carnet de recettes en PDF (téléchargement)
"""

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

st.title("🛒 Ta liste de courses")
st.caption(
    "Choisis tes recettes et le nombre de personnes que tu vas régaler pour chaque recette. "
    "Ensuite, clique sur le bouton tout en bas pour générer la liste de courses et le carnet de recettes."
)

recipes = db.get_all_recipes()

if not recipes:
    st.warning(
        "Aucune recette n'est enregistrée pour l'instant. "
        "Rends-toi sur la page « 🍳 Ajouter une recette » pour commencer."
    )
    st.stop()

st.header("Qu'est-ce qu'on mange ?")

all_tags = db.get_all_tags()
all_authors = db.get_all_authors()

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
        "👤 Filtrer par auteur (optionnel)",
        options=all_authors,
        help="Affiche uniquement les recettes ajoutées par les auteurs sélectionnés.",
    )

names = list(recipes.keys())
if tag_filter:
    names = [name for name in names if set(recipes[name].get("tags", [])) & set(tag_filter)]
if author_filter:
    names = [name for name in names if recipes[name].get("created_by") in author_filter]

if (tag_filter or author_filter) and not names:
    st.info("Aucune recette ne correspond à ce filtre.")

columns = st.columns(2)
selected_choices: list[RecipeChoice] = []

for i, name in enumerate(names):
    recipe = recipes[name]
    base = recipe["portions_base"]
    col = columns[i % 2]

    with col:
        with st.container(border=True):
            image = common.get_recipe_image(name, recipe["image"])
            common.render_recipe_image_card(name, image)

            if recipe.get("tags"):
                st.markdown(" ".join(f"`{t}`" for t in recipe["tags"]))

            if recipe.get("created_by"):
                st.caption(f"👤 Ajoutée par {recipe['created_by']}")

            meta_bits = []
            prep = common.format_time_minutes(recipe.get("prep_time_minutes"))
            cook = common.format_time_minutes(recipe.get("cook_time_minutes"))
            if prep:
                meta_bits.append(f"⏱️ Préparation : {prep}")
            if cook:
                meta_bits.append(f"🔥 Cuisson : {cook}")
            if meta_bits:
                st.caption(" · ".join(meta_bits))
            if recipe.get("description"):
                st.caption(recipe["description"])

            checked = st.checkbox("Ajouter à ma liste", key=f"chk_{recipe['id']}")
            people = st.number_input(
                f"Nombre de personnes (base : {base})",
                min_value=1,
                value=base,
                step=1,
                key=f"people_{recipe['id']}",
                disabled=not checked,
            )

            if checked:
                selected_choices.append(RecipeChoice(name, int(people)))

            if recipe["ingredients"]:
                with st.expander("📋 Voir les ingrédients"):
                    ratio = Fraction(int(people), base)
                    st.caption(f"Quantités pour {int(people)} personne(s)")
                    for section_name, rows in recipe["ingredients"].items():
                        if len(recipe["ingredients"]) > 1:
                            st.markdown(f"**{section_name}**")
                        for ingredient_name, qty, unit in rows:
                            scaled = Fraction(str(qty)).limit_denominator(100) * ratio
                            qty_str = common.format_quantity(scaled)
                            label = ingredient_name.capitalize()
                            if unit and unit != "unité":
                                st.markdown(f"- {qty_str} {unit} de {label}")
                            else:
                                st.markdown(f"- {qty_str} x {label}")

st.divider()

reference = st.text_input(
    "📝 Référence (optionnel)",
    placeholder="ex. : Repas de la semaine du 10 mai",
    help="Apparaît en haut de la liste de courses et dans le titre du carnet de recettes.",
)

generate = st.button(
    "🧾 Générer la liste de courses et le carnet de recettes",
    type="primary",
    disabled=len(selected_choices) == 0,
)

if len(selected_choices) == 0:
    st.info("Sélectionne au moins une recette pour continuer.")

if generate:
    st.session_state["choices"] = selected_choices
    st.session_state["reference"] = reference.strip()

choices = st.session_state.get("choices")
if not choices:
    st.stop()

# Ignore les choix qui référenceraient une recette entre-temps supprimée
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
