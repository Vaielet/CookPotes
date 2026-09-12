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

    La vérification inclut aussi `user_id` (pas seulement `list_id`) : sans
    ça, si deux comptes différents se connectent l'un après l'autre dans le
    même onglet (auth.login/logout vident désormais st.session_state pour
    cette raison — voir auth.py), une copie mise en cache pour le premier
    compte pourrait être renvoyée par erreur au second s'ils ouvrent la
    même liste partagée. Double sécurité, peu coûteuse.
    """
    cache_key = "_list_detail_cache"
    cached = st.session_state.get(cache_key)
    if cached is not None and cached["id"] == list_id and cached.get("_cached_for_user_id") == user_id:
        return cached

    fresh = db.get_saved_list(list_id, user_id)
    if fresh is not None:
        fresh["_cached_for_user_id"] = user_id
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

owned_count = sum(1 for l in lists_summary if l["is_owner"])
shared_count = len(lists_summary) - owned_count
counter_caption = f"{owned_count} / {db.MAX_SAVED_LISTS_PER_USER} menu(s) enregistré(s)"
if shared_count:
    counter_caption += f" · {shared_count} partagé(s) avec toi"
st.caption(counter_caption)

if not lists_summary:
    st.info(
        "Aucun menu enregistré pour l'instant. Va sur la page « Composer "
        "mon menu », choisis tes recettes, génère la liste et le carnet de recette, puis clique sur "
        "« 💾 Enregistrer dans mon compte »."
    )

    if st.button(
        "Composer mon menu", key="coposer_menu_btn",
        type="primary", use_container_width=True,
    ):
        st.switch_page("pages/2_Composer_mon_menu.py")
    
    st.stop()


# ---------------------------------------------------------------------------
# Sélecteur de liste
# ---------------------------------------------------------------------------

def _list_label(l: dict) -> str:
    title = l["reference"] or "Liste sans nom"
    date = common.format_datetime(l["created_at"])
    label = f"{title} — créé le {date}"
    if not l["is_owner"]:
        label += f" · partagé par {l['owner_username']}"
    return label


options = {_list_label(l): l["id"] for l in lists_summary}
labels = list(options.keys())

if "open_list_id" not in st.session_state or st.session_state["open_list_id"] not in options.values():
    st.session_state["open_list_id"] = lists_summary[0]["id"]

current_label = next(lbl for lbl, i in options.items() if i == st.session_state["open_list_id"])

summary_by_id = {l["id"]: l for l in lists_summary}

select_col, refresh_col, delete_col = st.columns([4, 1, 1], vertical_alignment="bottom")
selected_label = select_col.selectbox(
    "Choisis un menu", options=labels, index=labels.index(current_label),
)
selected_id = options[selected_label]
st.session_state["open_list_id"] = selected_id
is_owner = summary_by_id[selected_id]["is_owner"]

refresh_col.write("")
if refresh_col.button(
    "🔄 Actualiser", use_container_width=True,
    help="Recharge ce menu depuis le serveur — utile si quelqu'un d'autre a coché un article entre-temps.",
):
    st.session_state.pop("_list_detail_cache", None)
    st.rerun()

delete_col.write("")
delete_confirm_key = f"confirm_delete_list_{selected_id}"
delete_label = "🗑️ Supprimer" if is_owner else "🚪 Quitter"
if delete_col.button(delete_label, use_container_width=True):
    st.session_state[delete_confirm_key] = True
    st.rerun()

if st.session_state.get(delete_confirm_key):
    if is_owner:
        st.warning(f"Es-tu sûr·e de vouloir supprimer « {current_label} » ? Cette action est irréversible.")
    else:
        st.warning(f"Quitter « {current_label} » ? Tu perdras l'accès à ce menu partagé (la personne qui l'a "
                    "partagé avec toi pourra toujours te le repartager plus tard).")
    confirm_cols = st.columns(2)
    if confirm_cols[0].button(
        "✅ Oui, confirmer", key=f"confirm_delete_list_yes_{selected_id}",
        type="primary", use_container_width=True,
    ):
        if is_owner:
            db.delete_saved_list(selected_id, user_id)
            flash = "Menu supprimé."
        else:
            db.remove_list_share(selected_id, requesting_user_id=user_id, target_user_id=user_id)
            flash = "Tu as quitté ce menu partagé."
        st.session_state.pop("_list_detail_cache", None)
        st.session_state.pop(delete_confirm_key, None)
        st.session_state["open_list_id"] = None
        st.session_state["_flash_list_msg"] = flash
        st.rerun()
    if confirm_cols[1].button(
        "Annuler", key=f"confirm_delete_list_no_{selected_id}", use_container_width=True,
    ):
        st.session_state.pop(delete_confirm_key, None)
        st.rerun()

detail = _load_list_detail(selected_id, user_id)
if detail is None:
    st.warning("Cette liste n'existe plus.")
    st.stop()

if not detail["is_owner"]:
    st.caption(f"👥 Menu partagé par **{detail['owner_username']}**.")
else:
    with st.expander("👥 Partager ce menu"):
        shares = db.get_list_shares(selected_id, user_id)
        if shares:
            st.caption("Ce menu est actuellement partagé avec :")
            for share in shares:
                share_row_cols = st.columns([4, 1])
                share_row_cols[0].markdown(f"- {share['username']}")
                if share_row_cols[1].button(
                    "Retirer", key=f"unshare_{selected_id}_{share['user_id']}", use_container_width=True,
                ):
                    db.remove_list_share(selected_id, requesting_user_id=user_id, target_user_id=share["user_id"])
                    st.rerun()
        else:
            st.caption("Ce menu n'est partagé avec personne pour l'instant.")

        with st.form(f"share_form_{selected_id}", clear_on_submit=True):
            share_username = st.text_input("Identifiant du compte avec qui partager")
            share_submitted = st.form_submit_button("Partager")
        if share_submitted:
            if not share_username.strip():
                st.error("Indique un identifiant.")
            else:
                try:
                    shared_with = db.add_list_share(selected_id, user_id, share_username)
                except db.ListShareError as exc:
                    st.error(str(exc))
                else:
                    st.success(f"Menu partagé avec « {shared_with} ».")
                    st.rerun()

existing_recipe_names = db.get_recipe_names()
all_recipes_full = db.get_all_recipes()
recipes_by_id = {r["id"]: name for name, r in all_recipes_full.items()}

# ---------------------------------------------------------------------------
# État de chaque recette du menu par rapport à AUJOURD'HUI : toujours là et
# inchangée / renommée / modifiée / vraiment supprimée. Basé sur recipe_id
# (stable même si la recette est renommée depuis), pas sur le nom — voir
# db.save_shopping_list / db._migrate_schema pour le rattrapage des menus
# enregistrés avant l'ajout de cet id. Repli sur le nom pour ces
# anciens menus (uniquement s'il n'a pas changé depuis).
# ---------------------------------------------------------------------------
recipe_states = []
for r in detail["recipes"]:
    current_name = None
    if r.get("recipe_id") is not None and r["recipe_id"] in recipes_by_id:
        current_name = recipes_by_id[r["recipe_id"]]
    elif r["name"] in existing_recipe_names:
        current_name = r["name"]

    is_deleted = current_name is None
    is_modified = False
    diff = None
    if not is_deleted:
        current_recipe = all_recipes_full[current_name]
        if r.get("recipe_updated_at") and current_recipe.get("updated_at"):
            is_modified = r["recipe_updated_at"] != current_recipe["updated_at"]
        if is_modified and r.get("ingredients_snapshot") is not None:
            new_rows = common.scaled_ingredient_rows(current_recipe, r["people"])
            diff = common.diff_recipe_ingredients(r["ingredients_snapshot"], new_rows)

    recipe_states.append({
        **r,
        "current_name": current_name,
        "is_deleted": is_deleted,
        "is_modified": is_modified,
        "diff": diff,
    })

# ---------------------------------------------------------------------------
# Actions sur cette liste : télécharger / ouvrir dans une app, comme sur
# « 🛒 Générer ma liste » — sans rien recalculer, juste exporter les
# articles déjà enregistrés tels quels.
# ---------------------------------------------------------------------------
list_title = detail["reference"] or "Liste de courses"

export_grouped: dict[str, list[str]] = {}
for item in detail["items"]:
    export_grouped.setdefault(item["category"], []).append(item["label"])

# On ne garde que les recettes de la liste qui existent VRAIMENT encore
# (renommées incluses, via current_name) — une recette supprimée depuis ne
# peut plus être imprimée dans le carnet.
current_choices = [
    common.RecipeChoice(name=rs["current_name"], people=rs["people"])
    for rs in recipe_states if not rs["is_deleted"]
]
missing_recipes = [rs["name"] for rs in recipe_states if rs["is_deleted"]]

# ---------------------------------------------------------------------------
# Diff agrégé sur TOUT le menu (toutes recettes confondues), pour mettre en
# évidence les changements directement sur la liste de courses fusionnée —
# utile si les courses ont déjà été faites : d'un coup d'œil, ce qu'il
# manque peut-être ou ce qui a été acheté en quantité insuffisante.
# ---------------------------------------------------------------------------
old_rows_all: list[tuple] = []
new_rows_all: list[tuple] = []
has_any_snapshot = False
for rs in recipe_states:
    if rs.get("ingredients_snapshot") is not None:
        has_any_snapshot = True
        old_rows_all.extend(rs["ingredients_snapshot"])
    if not rs["is_deleted"]:
        new_rows_all.extend(common.scaled_ingredient_rows(all_recipes_full[rs["current_name"]], rs["people"]))

merged_diff = common.diff_recipe_ingredients(old_rows_all, new_rows_all) if has_any_snapshot else None

# {nom_canonique: {"kind": ..., "text": ...}} — un seul message par nom
# (si un même ingrédient a plusieurs unités avec des changements de nature
# différente, un seul s'affiche ; cas rare, simplification acceptée).
merged_warnings: dict[str, dict] = {}
if merged_diff:
    for name, qty, unit in merged_diff["added"]:
        merged_warnings[name] = {
            "kind": "added",
            "text": f"🆕 **{name.capitalize()}** — nouvel ingrédient, absent de ta liste initiale "
                    f"({common.format_quantity(qty)} {unit}).",
        }
    for name, qty, unit in merged_diff["removed"]:
        merged_warnings[name] = {
            "kind": "removed",
            "text": "➖ Retiré d'une recette depuis — tu n'en as peut-être plus besoin.",
        }
    for name, old_qty, new_qty, unit in merged_diff["changed"]:
        if new_qty > old_qty:
            merged_warnings[name] = {
                "kind": "increased",
                "text": f"⚠️ Quantité augmentée depuis l'enregistrement (c'était "
                        f"{common.format_quantity(old_qty)} {unit}) — il t'en manque peut-être.",
            }
        else:
            merged_warnings[name] = {
                "kind": "decreased",
                "text": f"ℹ️ Quantité diminuée depuis l'enregistrement (c'était "
                        f"{common.format_quantity(old_qty)} {unit}) — tu en as peut-être acheté trop.",
            }


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
            # Met en évidence les articles dont la quantité a changé (ou
            # qui ne sont plus nécessaires) depuis l'enregistrement — utile
            # si les courses ont déjà été faites. "added" n'a pas de case à
            # cocher existante ici (jamais enregistré à l'origine), affiché
            # séparément juste en dessous.
            item_name = item["label"].split(" : ", 1)[0].strip().lower()
            warning = merged_warnings.get(item_name)
            if warning and warning["kind"] != "added":
                st.caption(warning["text"])

    new_ingredient_texts = [w["text"] for w in merged_warnings.values() if w["kind"] == "added"]
    if new_ingredient_texts:
        st.info(
            "**Nouveaux ingrédients apparus dans une recette depuis l'enregistrement "
            "de ce menu** (absents de la liste ci-dessus) :\n\n"
            + "\n".join(f"- {t}" for t in new_ingredient_texts)
        )


# ---------------------------------------------------------------------------
# Recettes de ce menu — affichage détaillé sur demande
# ---------------------------------------------------------------------------

st.subheader("🍽️ Recettes de ce menu")

# Même comportement que la grille de recettes de « Composer mon menu » :
# taille de carte strictement fixe sur ordinateur (jamais de rétrécissement
# à cause du flex-grow par défaut de Streamlit), souple (min/max) sur
# smartphone/tablette. Voir pages/2_Composer_mon_menu.py pour le détail de
# chaque choix ci-dessous (sélecteur stColumn plutôt que "column" — le
# seul qui existe vraiment dans le DOM Streamlit —, !important nécessaire
# car Streamlit réapplique ses propres largeurs en style inline à chaque
# redimensionnement, display:flex forcé sur le parent car Streamlit peut
# aussi passer ce conteneur en CSS Grid selon la largeur d'écran).
MENUS_GRID_COLUMNS = 4
MENUS_CARD_WIDTH_PX = 320
MENUS_CARD_MIN_WIDTH_PX = 300
MENUS_CARD_MAX_WIDTH_PX = 380
MENUS_DESKTOP_BREAKPOINT_PX = 768

st.markdown(
    f"""
    <style>
    .st-key-mes_menus_recipe_grid div[data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-wrap: wrap !important;
        row-gap: 1.5rem;
    }}
    .st-key-mes_menus_recipe_grid div[data-testid="stColumn"] {{
        display: block !important;
        flex: 1 1 {MENUS_CARD_MIN_WIDTH_PX}px !important;
        width: {MENUS_CARD_MIN_WIDTH_PX}px !important;
        min-width: {MENUS_CARD_MIN_WIDTH_PX}px !important;
        max-width: {MENUS_CARD_MAX_WIDTH_PX}px !important;
    }}
    @media (min-width: {MENUS_DESKTOP_BREAKPOINT_PX}px) {{
        .st-key-mes_menus_recipe_grid div[data-testid="stColumn"] {{
            flex: 0 0 {MENUS_CARD_WIDTH_PX}px !important;
            width: {MENUS_CARD_WIDTH_PX}px !important;
            min-width: {MENUS_CARD_WIDTH_PX}px !important;
            max-width: {MENUS_CARD_WIDTH_PX}px !important;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="mes_menus_recipe_grid"):
    recipe_cols = st.columns(MENUS_GRID_COLUMNS)

    for i, rs in enumerate(recipe_states):
        with recipe_cols[i % MENUS_GRID_COLUMNS]:
            with st.container(border=True):
                if rs["is_deleted"]:
                    st.markdown(f"**{rs['name']}**")
                else:
                    # all_recipes_full est déjà chargé en entier plus haut (il
                    # nous fallait de toute façon les ingrédients actuels pour
                    # le diff agrégé) : on réutilise directement son image,
                    # pas besoin d'un second aller-retour pour les vignettes.
                    common.render_recipe_image_card(
                        rs["current_name"], all_recipes_full[rs["current_name"]]["image"]
                    )
                st.caption(f"{rs['people']} personne(s)")

                if rs["is_deleted"]:
                    st.caption("⚠️ Cette recette a été supprimée depuis.")
                    continue

                if rs["current_name"] != rs["name"]:
                    st.caption(f"ℹ️ Renommée depuis (« {rs['name']} » à l'origine).")

                if rs["is_modified"]:
                    st.caption("✏️ Cette recette a été modifiée depuis, vérifie ta liste.")
                    diff = rs["diff"]
                    if diff and (diff["added"] or diff["removed"] or diff["changed"]):
                        with st.expander("Voir ce qui a changé"):
                            for name, qty, unit in diff["added"]:
                                st.markdown(f"- 🆕 Ajouté : {common.format_quantity(qty)} {unit} de {name.capitalize()}")
                            for name, qty, unit in diff["removed"]:
                                st.markdown(f"- ➖ Retiré : {common.format_quantity(qty)} {unit} de {name.capitalize()}")
                            for name, old_qty, new_qty, unit in diff["changed"]:
                                st.markdown(
                                    f"- 🔁 {name.capitalize()} : "
                                    f"{common.format_quantity(old_qty)} → {common.format_quantity(new_qty)} {unit}"
                                )

                if st.button("👀 Voir la recette", key=f"viewrecipe_{selected_id}_{i}", use_container_width=True):
                    _recipe_dialog(rs["current_name"], rs["people"], all_recipes_full[rs["current_name"]])

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
                # all_recipes_full est déjà chargé en entier plus haut (il
                # nous fallait les ingrédients actuels pour le diff) : plus
                # besoin d'un second appel ici comme avant.
                st.session_state[booklet_key] = common.build_recipe_booklet_pdf(
                    current_choices, all_recipes_full, title=list_title,
                )
            if st.session_state.get(booklet_key):
                st.download_button(
                    "⬇️ Télécharger le PDF", data=st.session_state[booklet_key],
                    file_name=f"carnet_{selected_id}.pdf", mime="application/pdf",
                    use_container_width=True,
                )

    if missing_recipes:
        st.caption(f"⚠️ Recette(s) supprimée(s) depuis, exclue(s) du carnet : {', '.join(missing_recipes)}.")
