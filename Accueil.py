#!/usr/bin/env python3
"""
app.py — Page d'accueil de l'application.

Lancement :
    streamlit run app.py

Les autres pages se trouvent dans le dossier pages/ et apparaissent
automatiquement dans le menu de navigation à gauche :
  1. 🍳 Ajouter une recette      : encoder / modifier des recettes
                                    (réservé aux comptes éditeurs)
  2. 🛒 Générer ma liste         : choisir des recettes, un nb de personnes,
                                    et générer la liste de courses + le PDF
  3. 👤 Gestion des utilisateurs : créer des comptes et attribuer le statut
                                    éditeur (réservé aux administrateurs)

Au tout premier lancement, un compte administrateur par défaut est créé
automatiquement : identifiant "admin", mot de passe "admin123". Connectez-
vous avec ce compte puis changez immédiatement ce mot de passe depuis la
page « Gestion des utilisateurs ».
"""

import streamlit as st

import auth
import common
import db

st.set_page_config(
    page_title="Liste de courses & carnet de recettes",
    page_icon="🛒",
    layout="wide",
)

db.init_db()
auth.render_sidebar_auth()

common.header_logo()

st.markdown(
    """
Bienvenue ! Cette application te permet de :

- **🛒 Générer ta liste de courses** : sélectionnes les recettes pour 
  la semaine (ou le mois, soyons foufolles). Indique le
  nombre de personnes pour chaque recette, un clic et le tour est joué ! Tu reçois 
  ta liste de courses et un carnet avec les recettes sélectionnées en PDF.
- **🍳 Ajouter une recette** : partage tes recettes coup de coeur ou celles de ton grand-père. **Réservé aux comptes avec le statut éditeur·rice** —
  connectez-vous via le menu à gauche.

Utilise le menu à gauche pour naviguer entre les pages.
"""
)
recipes = db.get_all_recipes()

col1, col2 = st.columns(2)
col1.metric("Recettes enregistrées", len(recipes))

recent = db.get_recent_recipes(limit=5)
if recent:
    st.subheader("🆕 Dernières recettes ajoutées")
    recent_cols = st.columns(len(recent))
    for col, r in zip(recent_cols, recent):
        with col:
            img = common.get_recipe_image(r["name"], r["image"])
            st.image(img, use_container_width=True)
            st.markdown(f"**{r['name']}**")
            st.caption(
                f"👤 {r['created_by'] or 'inconnu'}  \n"
                f"🗓️ {common.format_datetime(r['created_at'])}"
            )
else:
    st.info("Aucune recette pour l'instant. Rendez-vous sur la page « Ajouter une recette ».")

