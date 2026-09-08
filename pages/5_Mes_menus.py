"""
Page 5 — Mes listes de courses.

Ouverte à tout compte connecté (pas besoin d'être éditeur·rice ni admin) :
retrouve les listes de courses enregistrées depuis « Générer ma liste »,
permet de cocher les articles au fur et à mesure des courses, et d'afficher
le détail d'une recette de la liste — tout d'un coup, ou étape par étape.
"""

import streamlit as st

import auth
import common
import db

st.set_page_config(page_title="Mes menus", layout="wide")

db.init_db()
#common.header_logo()
auth.require_login()


def _move_step(step_key: str, delta: int, max_index: int) -> None:
    """Callback des boutons Précédent/Suivant : avance/recule d'une étape,
    borné à [0, max_index]. Volontairement appelé via on_click (voir plus
    bas pourquoi), pas via un st.rerun() manuel après le clic."""
    current = st.session_state.get(step_key, 0)
    st.session_state[step_key] = max(0, min(current + delta, max_index))


@st.dialog(" ", width="large")
def _recipe_dialog(name: str, people: int, recipe: dict) -> None:
    """Affiche une recette en grand : vignette, ingrédients à l'échelle (dans
    un expander), et préparation — au choix en une fois, ou étape par étape."""
    st.markdown(f"## {name}")
    st.caption(f"Pour {people} personne(s)")

    # Vignette (pas la photo en pleine largeur) : on réutilise le même rendu
    # à taille fixe que les cartes recette de la page « Générer ma liste ».
    thumb_col, _spacer_col = st.columns([1, 2])
    with thumb_col:
        common.render_recipe_image_card(name, recipe["image"])

    sections = common.scaled_ingredient_sections(recipe, people)
    with st.expander("📋 Ingrédients", expanded=False):
        for section_name, lines in sections.items():
            if len(sections) > 1:
                st.markdown(f"**{section_name}**")
            for line in lines:
                st.markdown(f"- {line}")

    st.markdown("### 👩‍🍳 Préparation")
    instructions = recipe.get("instructions") or []
    if not instructions:
        st.caption("Aucune étape renseignée pour cette recette.")
        return

    mode_key = f"cookmode_{name}_{people}"
    mode = st.radio(
        "Affichage", ["Tout afficher", "Étape par étape"],
        horizontal=True, key=mode_key, label_visibility="collapsed",
    )

    if mode == "Tout afficher":
        for i, step in enumerate(instructions, start=1):
            st.markdown(f"{i}. {step}")
    else:
        step_key = f"cookstep_{name}_{people}"
        idx = max(0, min(st.session_state.get(step_key, 0), len(instructions) - 1))
        st.session_state[step_key] = idx

        st.progress((idx + 1) / len(instructions), text=f"Étape {idx + 1} / {len(instructions)}")
        st.markdown(f"#### {instructions[idx]}")

        # Important : on passe par des callbacks on_click (qui mettent à jour
        # session_state AVANT que le script ne se réexécute) plutôt que par
        # un st.rerun() manuel après le clic — appeler st.rerun() à
        # l'intérieur d'un st.dialog referme la fenêtre au lieu de
        # simplement rafraîchir son contenu. Un clic sur un bouton déclenche
        # de toute façon une réexécution naturelle, qui suffit ici.
        nav_cols = st.columns(2)
        nav_cols[0].button(
            "◀ Précédent", disabled=idx == 0, use_container_width=True,
            key=f"prevstep_{name}_{people}",
            on_click=_move_step, args=(step_key, -1, len(instructions) - 1),
        )
        nav_cols[1].button(
            "Suivant ▶", disabled=idx == len(instructions) - 1, use_container_width=True,
            key=f"nextstep_{name}_{people}",
            on_click=_move_step, args=(step_key, 1, len(instructions) - 1),
        )


def _load_list_detail(list_id: int, user_id: int) -> dict | None:
    """
    Charge le détail d'une liste UNE fois par sélection, puis le garde dans
    st.session_state : les cases cochées ensuite ne redéclenchent plus
    aucun aller-retour réseau vers Supabase pour réafficher la page (voir
    _toggle_item, qui met à jour cette copie directement en mémoire au lieu
    de recharger). Un changement de liste sélectionnée, ou une nouvelle
    session/rechargement de page, repart sur des données fraîches.
    """
    cache_key = "_list_detail_cache"
    cached = st.session_state.get(cache_key)
    if cached is not None and cached["id"] == list_id:
        return cached

    fresh = db.get_saved_list(list_id, user_id)
    if fresh is not None:
        st.session_state[cache_key] = fresh
    return fresh


common.icon_title("Mes menus", "mes_menus.png", "📋")
st.caption(
    "Retrouve ici les menus enregistrées depuis « Composer mon menu ». "
    "Coche les articles au fur et à mesure de tes courses, et ouvre une "
    "recette pour l'avoir sous les yeux en cuisinant."
)

user_id = auth.current_user_id()

if st.session_state.get("_flash_list_msg"):
    st.success(st.session_state["_flash_list_msg"])
    st.session_state["_flash_list_msg"] = None

lists_summary = db.get_saved_lists(user_id)

st.caption(f"{len(lists_summary)} / {db.MAX_SAVED_LISTS_PER_USER} menu(s) enregistré(s).")

if not lists_summary:
    st.info(
        "Aucune liste enregistrée pour l'instant. Va sur « 🛒 Générer ma "
        "liste », choisis tes recettes, génère la liste, puis clique sur "
        "« 💾 Enregistrer dans mon compte »."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Sélecteur de liste
# ---------------------------------------------------------------------------

def _list_label(l: dict) -> str:
    title = l["reference"] or "Liste sans nom"
    date = common.format_datetime(l["created_at"])
    return f"{title} — {date} ({l['checked_items']}/{l['total_items']} cochés)"


options = {_list_label(l): l["id"] for l in lists_summary}
labels = list(options.keys())

if "open_list_id" not in st.session_state or st.session_state["open_list_id"] not in options.values():
    st.session_state["open_list_id"] = lists_summary[0]["id"]

current_label = next(lbl for lbl, i in options.items() if i == st.session_state["open_list_id"])

select_col, delete_col = st.columns([4, 1],vertical_alignment="bottom")
selected_label = select_col.selectbox(
    "Choisis un menu", options=labels, index=labels.index(current_label),
)
selected_id = options[selected_label]
st.session_state["open_list_id"] = selected_id

delete_col.write("")
with delete_col.popover("🗑️ Supprimer ce menu", use_container_width=True):
    st.warning(f"Es-tu sûr·e de vouloir supprimer « {current_label} » ? Cette action est irréversible.")
    if st.button(
        "✅ Oui, supprimer définitivement", key=f"confirm_delete_list_{selected_id}",
        type="primary", use_container_width=True,
    ):
        db.delete_saved_list(selected_id, user_id)
        st.session_state.pop("_list_detail_cache", None)
        st.session_state["open_list_id"] = None
        st.session_state["_flash_list_msg"] = "Liste supprimée."
        st.rerun()

detail = _load_list_detail(selected_id, user_id)
if detail is None:
    st.warning("Cette liste n'existe plus.")
    st.stop()

existing_recipe_names = db.get_recipe_names()

# ---------------------------------------------------------------------------
# Actions sur cette liste : télécharger / ouvrir dans une app, comme sur
# « 🛒 Générer ma liste » — sans rien recalculer, juste exporter les
# articles déjà enregistrés tels quels.
# ---------------------------------------------------------------------------
list_title = detail["reference"] or "Liste de courses"

export_grouped: dict[str, list[str]] = {}
for item in detail["items"]:
    export_grouped.setdefault(item["category"], []).append(item["label"])

# On ne garde que les recettes de la liste qui existent encore — une
# recette supprimée depuis ne peut plus être imprimée dans le carnet.
# (Vérification faite sur les noms seulement — pas besoin de charger les
# photos de toutes les recettes juste pour ça.)
current_choices = [
    common.RecipeChoice(name=r["name"], people=r["people"])
    for r in detail["recipes"] if r["name"] in existing_recipe_names
]
missing_recipes = [r["name"] for r in detail["recipes"] if r["name"] not in existing_recipe_names]


# ---------------------------------------------------------------------------
# Progression + liste de courses à cocher
# ---------------------------------------------------------------------------

with st.expander("🛒 Liste de courses"):

    total_items = len(detail["items"])
    checked_items = sum(1 for it in detail["items"] if it["checked"])

    if total_items:
        st.progress(checked_items / total_items, text=f"{checked_items} / {total_items} article(s) coché(s)")

    by_category: dict[str, list[dict]] = {}
    for item in detail["items"]:
        by_category.setdefault(item["category"], []).append(item)

    def _toggle_item(item_id: int, user_id: int, key: str) -> None:
        """Callback on_change : enregistre la coche AVANT le rerun automatique
        que Streamlit déclenche déjà tout seul après un changement de widget —
        pas besoin d'un st.rerun() manuel en plus (même logique que _move_step
        plus haut).

        Écrit aussi la nouvelle valeur directement dans la copie de la liste
        déjà en mémoire (_load_list_detail) : sans ça, le corps du script
        rechargerait toute la liste depuis Supabase à chaque case cochée, ce
        qui causait le lag observé sur Streamlit Cloud (latence réseau vers la
        base à chaque clic). Le cache partagé est quand même invalidé côté
        db.py, donc un autre onglet ou un rechargement de page repart bien sur
        des données à jour."""
        new_value = st.session_state[key]
        db.set_shopping_item_checked(item_id, user_id, new_value)
    
        cached = st.session_state.get("_list_detail_cache")
        if cached is not None:
            for it in cached["items"]:
                if it["id"] == item_id:
                    it["checked"] = new_value
                    break
    
    
    for category in common._ordered_categories(set(by_category.keys())):
        st.markdown(f"**{category}**")
        for item in by_category[category]:
            item_key = f"item_{item['id']}"
            st.checkbox(
                item["label"], value=item["checked"], key=item_key,
                on_change=_toggle_item, args=(item["id"], user_id, item_key),
            )


# ---------------------------------------------------------------------------
# Recettes de ce menu — affichage détaillé sur demande
# ---------------------------------------------------------------------------

st.subheader("🍽️ Recettes de ce menu")

thumbnails = db.get_recipe_thumbnails(
    tuple(sorted({r["name"] for r in detail["recipes"] if r["name"] in existing_recipe_names}))
)

recipe_cols = st.columns(3)

for i, r in enumerate(detail["recipes"]):
    with recipe_cols[i % 3]:
        with st.container(border=True):
            if r["name"] in existing_recipe_names:
                common.render_recipe_image_card(r["name"], thumbnails.get(r["name"]))
            else:
                st.markdown(f"**{r['name']}**")
            st.caption(f"{r['people']} personne(s)")
            if r["name"] not in existing_recipe_names:
                st.caption("⚠️ Cette recette a été supprimée depuis.")
            elif st.button("👀 Voir la recette", key=f"viewrecipe_{selected_id}_{i}", use_container_width=True):
                # Chargement complet (ingrédients/instructions) volontairement
                # différé jusqu'ici, sur un clic explicite — pas à chaque
                # rerun. La photo, elle, est déjà chargée ci-dessus (vignette).
                _recipe_dialog(r["name"], r["people"], db.get_all_recipes()[r["name"]])

with st.expander("Téléchargement"):

    action_cols = st.columns(2)

    with action_cols[0]:
        with st.container(border=True):
            st.subheader("🧾 Liste de courses")
            st.download_button(
                "⬇️ Télécharger la liste (.txt)",
                data=common.build_shopping_text(list_title, export_grouped),
                file_name=f"{list_title}.txt", mime="text/plain",
                use_container_width=True, disabled=not export_grouped,
            )
            common.render_share_widget(common.build_shopping_text(list_title, export_grouped))


    with action_cols[1]:
        with st.container(border=True):
            st.subheader("📕 Carnet de recettes")
            booklet_key = f"_booklet_pdf_{selected_id}"
            if st.button("📖 Générer le carnet de recettes", use_container_width=True, disabled=not current_choices):
                # Chargement complet (avec photos) volontairement différé jusqu'ici :
                # seule une action explicite et ponctuelle le déclenche, jamais un
                # simple rerun (case cochée, etc.).
                all_recipes = db.get_all_recipes()
                st.session_state[booklet_key] = common.build_recipe_booklet_pdf(
                    current_choices, all_recipes, title=list_title,
                )
            if st.session_state.get(booklet_key):
                st.download_button(
                    "⬇️ Télécharger le PDF", data=st.session_state[booklet_key],
                    file_name=f"carnet_{selected_id}.pdf", mime="application/pdf",
                    use_container_width=True,
                )

    if missing_recipes:
        st.caption(f"⚠️ Recette(s) supprimée(s) depuis, exclue(s) du carnet : {', '.join(missing_recipes)}.")
