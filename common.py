"""
common.py — Logique métier partagée entre les pages de l'application :
conversion d'unités, agrégation de la liste de courses, génération des
images de secours et du carnet de recettes PDF.
"""

from __future__ import annotations

import streamlit as st
import io
import platform
import subprocess
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from fractions import Fraction

from PIL import Image, ImageDraw, ImageFont

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image as RLImage,
    Table, TableStyle, ListFlowable, ListItem,
)

# ---------------------------------------------------------------------------
# Conversions d'unités pour l'agrégation de la liste de courses
# ---------------------------------------------------------------------------

UNIT_CONVERSIONS = {
    "cac": ("ml", 5),
    "cuillère à café": ("ml", 5),

    "cas": ("ml", 15),
    "cuillère à soupe": ("ml", 15),

    "l": ("ml", 1000),
    "litre": ("ml", 1000),

    "kg": ("g", 1000),
}

# Unités suggérées dans le formulaire d'ajout de recette
COMMON_UNITS = [
    "g", "kg", "ml", "l", "cac", "cas", "pièce", "gousse",
    "tranche", "feuilles", "brins", "cube", "pincée", "unité",
]

# Catégories/régimes suggérés dans le formulaire d'ajout de recette. La
# liste n'est pas fermée : le formulaire permet aussi d'ajouter des
# catégories personnalisées en texte libre.
COMMON_TAGS = [
    "Végétarien",
    "Végan",
    "Sans gluten",
    "Sans lactose",
    "Sans noix",
    "Pescétarien",
    "Rapide (< 30 min)",
    "Économique",
    "Épicé",
    "Sucré",
    "Healthy",
    "Enfants",
    "Fêtes / Occasions spéciales",
    "Plat unique",
    "Entrée",
    "Dessert",
]

# Longueur maximale du petit texte de présentation d'une recette. Doit
# correspondre à db.MAX_DESCRIPTION_CHARS.
MAX_DESCRIPTION_CHARS = 300

def header_logo():
    col1, col2, col3 = st.columns(3)
    with col2:
        st.image("images/CookPotes_logo.png", width=300)
        #st.markdown(f"**{r[L'app qui te simplifie la vie]}**")
    

def format_datetime(iso_string: str | None) -> str:
    """Formate une date ISO stockée en base en un texte lisible (ex: 28/08/2026 à 14h32)."""
    if not iso_string:
        return "date inconnue"
    try:
        dt = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return dt.strftime("%d/%m/%Y à %Hh%M")


def format_time_minutes(minutes: int | None) -> str | None:
    """Formate une durée en minutes en texte lisible (ex: 1h15, 45 min)."""
    if minutes is None:
        return None
    minutes = int(minutes)
    if minutes <= 0:
        return None
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def normalize_unit(quantity, unit):
    """
    Convertit une quantité vers une unité standard pour la liste
    de courses uniquement.

    Exemples :
        1 cac  -> 5 ml
        2 cas  -> 30 ml
        1.5 kg -> 1500 g
    """
    unit = unit.strip().lower()

    if unit in UNIT_CONVERSIONS:
        target_unit, factor = UNIT_CONVERSIONS[unit]
        quantity = Fraction(quantity).limit_denominator(100) * factor
        return quantity, target_unit

    return Fraction(quantity).limit_denominator(100), unit


# ---------------------------------------------------------------------------
# Classement des ingrédients par rayon
# ---------------------------------------------------------------------------

INGREDIENT_CATEGORIES = {
    # Fruits et légumes
    "courgette": "Fruits et légumes", "carotte": "Fruits et légumes",
    "oignon": "Fruits et légumes", "oignon rouge": "Fruits et légumes",
    "échalote": "Fruits et légumes", "ail": "Fruits et légumes",
    "piment": "Fruits et légumes", "poivron": "Fruits et légumes",
    "poivron rouge": "Fruits et légumes", "poivron vert": "Fruits et légumes",
    "poivron jaune": "Fruits et légumes", "tomate": "Fruits et légumes",
    "tomates cerises": "Fruits et légumes", "concombre": "Fruits et légumes",
    "laitue romaine": "Fruits et légumes", "salade": "Fruits et légumes",
    "roquette": "Fruits et légumes", "épinards": "Fruits et légumes",
    "brocoli": "Fruits et légumes", "chou-fleur": "Fruits et légumes",
    "chou blanc": "Fruits et légumes", "courge": "Fruits et légumes",
    "aubergine": "Fruits et légumes", "champignons": "Fruits et légumes",
    "haricots verts": "Fruits et légumes", "petits pois": "Fruits et légumes",
    "maïs": "Fruits et légumes", "pommes de terre": "Fruits et légumes",
    "patate douce": "Fruits et légumes", "radis": "Fruits et légumes",
    "avocat": "Fruits et légumes", "citron": "Fruits et légumes",
    "citron vert": "Fruits et légumes", "orange": "Fruits et légumes",
    "pomme": "Fruits et légumes", "poire": "Fruits et légumes",
    "banane": "Fruits et légumes", "ananas": "Fruits et légumes",
    "mangue": "Fruits et légumes", "fraise": "Fruits et légumes",
    "framboise": "Fruits et légumes", "myrtille": "Fruits et légumes",
    "persil": "Fruits et légumes", "ciboulette": "Fruits et légumes",
    "basilic frais": "Fruits et légumes", "coriandre": "Fruits et légumes",
    "menthe": "Fruits et légumes", "thym": "Fruits et légumes",
    "romarin": "Fruits et légumes", "poireaux": "Fruits et légumes",

    # Boucherie
    "poulet": "Boucherie", "poulet entier": "Boucherie",
    "blanc de poulet": "Boucherie", "cuisse de poulet": "Boucherie",
    "dinde": "Boucherie", "steak haché": "Boucherie",
    "bœuf haché": "Boucherie", "bœuf": "Boucherie",
    "rôti de bœuf": "Boucherie", "porc": "Boucherie",
    "filet mignon": "Boucherie", "côte de porc": "Boucherie",
    "agneau": "Boucherie", "veau": "Boucherie", "jambon": "Boucherie",
    "lardons": "Boucherie", "bacon": "Boucherie",
    "chair à saucisse": "Boucherie", "saucisse": "Boucherie",
    "merguez": "Boucherie", "chorizo": "Boucherie",

    # Poissonnerie
    "saumon": "Poissonnerie", "cabillaud": "Poissonnerie",
    "thon frais": "Poissonnerie", "thon": "Poissonnerie",
    "crevettes": "Poissonnerie", "moules": "Poissonnerie",
    "calamars": "Poissonnerie", "filet de poisson": "Poissonnerie",

    # Crèmerie
    "lait": "Crèmerie", "beurre": "Crèmerie", "crème fraîche": "Crèmerie",
    "crème liquide": "Crèmerie", "yaourt": "Crèmerie",
    "yaourt grec nature": "Crèmerie", "fromage râpé": "Crèmerie",
    "parmesan": "Crèmerie", "mozzarella": "Crèmerie", "cheddar": "Crèmerie",
    "emmental": "Crèmerie", "comté": "Crèmerie",
    "fromage de chèvre frais": "Crèmerie", "feta": "Crèmerie",
    "ricotta": "Crèmerie", "mascarpone": "Crèmerie", "œuf": "Crèmerie",
    "œufs": "Crèmerie",

    # Boulangerie
    "pain": "Boulangerie", "baguette": "Boulangerie",
    "pain de mie": "Boulangerie", "tortilla": "Boulangerie",
    "wrap": "Boulangerie", "pâte brisée": "Boulangerie",
    "pâte feuilletée": "Boulangerie", "croûtons": "Boulangerie",
    "chapelure": "Boulangerie",

    # Épicerie salée
    "spaghetti": "Épicerie", "pâtes": "Épicerie", "penne": "Épicerie",
    "tagliatelles": "Épicerie", "riz": "Épicerie", "riz basmati": "Épicerie",
    "riz complet": "Épicerie", "riz à risotto": "Épicerie",
    "semoule": "Épicerie", "quinoa": "Épicerie", "boulgour": "Épicerie",
    "farine": "Épicerie", "maïzena": "Épicerie", "huile d'olive": "Épicerie",
    "huile de tournesol": "Épicerie", "vinaigre balsamique": "Épicerie",
    "vinaigre": "Épicerie", "moutarde": "Épicerie", "ketchup": "Épicerie",
    "mayonnaise": "Épicerie", "mayonnaise allégée": "Épicerie",
    "sauce soja": "Épicerie", "sauce piquante": "Épicerie",
    "sauce césar": "Épicerie", "pâte de curry": "Épicerie",
    "lait de coco": "Épicerie", "crème de soja": "Épicerie",
    "bouillon de légumes": "Épicerie", "bouillon de volaille": "Épicerie",
    "pois chiches": "Épicerie", "lentilles": "Épicerie",
    "haricots rouges": "Épicerie", "haricots blancs": "Épicerie",
    "tomates concassées": "Épicerie", "purée de tomate": "Épicerie",
    "olives vertes": "Épicerie", "olives noires": "Épicerie",
    "thon en boîte": "Épicerie", "maïs en boîte": "Épicerie",

    # Épices et condiments
    "sel": "Épices", "poivre": "Épices", "paprika": "Épices",
    "paprika doux": "Épices", "cumin": "Épices", "curcuma": "Épices",
    "curry": "Épices", "gingembre": "Épices", "origan": "Épices",
    "herbes de provence": "Épices", "herbes italiennes sèchées": "Épices",
    "ail en poudre": "Épices", "cannelle": "Épices", "muscade": "Épices",

    # Surgelés
    "petits pois surgelés": "Surgelés", "épinards surgelés": "Surgelés",
    "frites surgelées": "Surgelés", "mélange de légumes surgelés": "Surgelés",

    # Boissons
    "eau pétillante": "Boissons", "jus d'orange": "Boissons",
    "cola": "Boissons", "bière": "Boissons", "vin blanc": "Boissons",
    "vin rouge": "Boissons",

    # Pâtisserie / Sucré
    "sucre": "Pâtisserie", "sucre roux": "Pâtisserie",
    "sucre glace": "Pâtisserie", "cassonade": "Pâtisserie",
    "chocolat noir": "Pâtisserie", "chocolat au lait": "Pâtisserie",
    "cacao": "Pâtisserie", "levure chimique": "Pâtisserie",
    "sucre vanillé": "Pâtisserie", "miel": "Pâtisserie",
    "confiture": "Pâtisserie",
}

DEFAULT_CATEGORY = "Divers"

CATEGORY_ORDER = [
    "Fruits et légumes", "Boucherie", "Poissonnerie", "Crèmerie",
    "Boulangerie", "Épicerie", "Épices", "Pâtisserie", "Surgelés",
    "Boissons", "Divers",
]


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class RecipeChoice:
    name: str
    people: int


@dataclass
class ShoppingList:
    items: dict = field(default_factory=lambda: defaultdict(Fraction))

    def add(self, name: str, quantity, unit: str) -> None:
        quantity, unit = normalize_unit(quantity, unit)
        key = (name.strip().lower(), unit)
        self.items[key] += quantity

    def as_grouped_lines(self) -> dict:
        """Retourne un dict {catégorie: [lignes formatées]}."""
        grouped = defaultdict(list)

        for (name, unit), qty in sorted(self.items.items()):
            display_qty = qty
            display_unit = unit

            if unit == "g" and qty >= 1000:
                display_qty = qty / 1000
                display_unit = "kg"
            elif unit == "ml" and qty >= 1000:
                display_qty = qty / 1000
                display_unit = "l"

            qty_str = format_quantity(display_qty)
            label = name.capitalize()

            if display_unit and display_unit != "unité":
                text = f"{qty_str} {display_unit} de {label}"
            else:
                text = f"{qty_str} x {label}"

            category = INGREDIENT_CATEGORIES.get(name.lower(), DEFAULT_CATEGORY)
            grouped[category].append(text)

        return grouped


def format_quantity(qty: Fraction) -> str:
    """Affiche une fraction sous forme lisible (entier ou décimal court)."""
    if qty.denominator == 1:
        return str(qty.numerator)
    value = float(qty)
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


# ---------------------------------------------------------------------------
# Images des recettes (photo stockée en base sinon image générée en mémoire)
# ---------------------------------------------------------------------------

def get_recipe_image(name: str, image_bytes: bytes | None) -> Image.Image:
    if image_bytes:
        try:
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            pass
    return generate_placeholder_image(name)


# Taille de police fixe utilisée pour le calcul de la mise en page du texte.
# On ne se fie jamais à un éventuel attribut `.size` de l'objet police
# (absent sur la police bitmap par défaut de Pillow), afin que le rendu
# fonctionne quel que soit l'OS et même si aucune police TrueType n'est
# trouvée sur la machine.
_PLACEHOLDER_FONT_SIZE = 42

# Quelques emplacements courants de polices "grasses" selon l'OS. On essaie
# chacun dans l'ordre ; si aucun ne fonctionne, on bascule sur la police
# par défaut intégrée à Pillow (toujours disponible, sans dépendance système).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # Linux (Debian/Ubuntu)
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",             # Linux (autres distros)
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/Library/Fonts/Arial Bold.ttf",                           # macOS
    "C:\\Windows\\Fonts\\arialbd.ttf",                          # Windows
    "C:\\Windows\\Fonts\\seguisb.ttf",                          # Windows (secours)
]


def _load_placeholder_font(size: int = _PLACEHOLDER_FONT_SIZE):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # Aucune police TrueType trouvée : on utilise la police par défaut de
    # Pillow, en lui demandant si possible la même taille (Pillow >= 9.2).
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Anciennes versions de Pillow : load_default() n'accepte pas `size`.
        return ImageFont.load_default()


def generate_placeholder_image(text: str, size=(800, 500)) -> Image.Image:
    """Crée une image simple (fond coloré + nom de la recette centré)."""
    palette = [
        (222, 184, 135), (176, 196, 222), (255, 200, 124),
        (188, 220, 180), (240, 180, 180), (200, 200, 240),
    ]
    color = palette[abs(hash(text)) % len(palette)]

    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)

    font = _load_placeholder_font()

    words = text.split() or [text]
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        try:
            test_width = draw.textlength(test, font=font)
        except Exception:
            test_width = len(test) * (_PLACEHOLDER_FONT_SIZE * 0.55)
        if test_width > size[0] - 80 and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    if not lines:
        lines = [text]

    line_height = _PLACEHOLDER_FONT_SIZE + 10
    total_height = line_height * len(lines)
    y = (size[1] - total_height) / 2

    for line in lines:
        try:
            w = draw.textlength(line, font=font)
        except Exception:
            w = len(line) * (_PLACEHOLDER_FONT_SIZE * 0.55)
        x = (size[0] - w) / 2
        draw.text((x, y), line, fill=(60, 40, 20), font=font)
        y += line_height

    return img


# ---------------------------------------------------------------------------
# Calcul de la liste de courses
# ---------------------------------------------------------------------------

def build_shopping_list(choices: list[RecipeChoice], recipes: dict) -> ShoppingList:
    shopping = ShoppingList()
    for choice in choices:
        recipe = recipes[choice.name]
        base = recipe["portions_base"]
        ratio = Fraction(choice.people, base)
        for section in recipe["ingredients"].values():
            for ingredient_name, qty, unit in section:
                scaled = Fraction(str(qty)).limit_denominator(100) * ratio
                shopping.add(ingredient_name, scaled, unit)
    return shopping


def build_shopping_text(title: str, grouped: dict) -> str:
    lines = [title, "=" * len(title), ""]
    for category in CATEGORY_ORDER:
        if category in grouped:
            lines.append(f"=== {category.upper()} ===")
            for item in grouped[category]:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export vers l'app Notes de macOS (via AppleScript / osascript)
# ---------------------------------------------------------------------------
#
# Ne fonctionne que si le serveur Streamlit tourne LUI-MÊME sur un Mac (ce
# qui est le cas d'un usage local classique : `streamlit run app.py` sur
# votre propre machine). Sur un serveur distant ou un autre OS, cette
# fonction retourne simplement False sans rien faire.

def export_to_macos_notes(title: str, grouped: dict) -> bool:
    if platform.system() != "Darwin":
        return False

    body_html = f"<h1>{_escape_applescript(title)}</h1>"
    for category in CATEGORY_ORDER:
        if category not in grouped:
            continue
        body_html += f"<h2>{_escape_applescript(category)}</h2><ul>"
        for item in grouped[category]:
            body_html += f"<li>{_escape_applescript(item)}</li>"
        body_html += "</ul>"

    applescript = f'''
    tell application "Notes"
        tell account "iCloud"
            make new note at folder "Notes" with properties {{body:"{body_html}"}}
        end tell
        activate
    end tell
    '''

    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Génération du carnet de recettes en PDF (en mémoire)
# ---------------------------------------------------------------------------

def build_recipe_booklet_pdf(choices: list[RecipeChoice], recipes: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "RecipeTitle", parent=styles["Title"], fontSize=22, spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=12,
        textColor=colors.grey, spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontSize=14,
        spaceBefore=12, spaceAfter=6,
    )
    cover_title_style = ParagraphStyle(
        "CoverTitle", parent=styles["Title"], fontSize=28, alignment=TA_CENTER,
    )

    story = []

    # --- Page de couverture : sommaire de la semaine ---
    logo = RLImage("images/CookPotes_logo_with_subtitle.png", width=8*cm, height=8*cm)

    logo.hAlign = "CENTER"

    story.append(Spacer(1, 2 * cm))
    story.append(logo)

    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("Carnet de recettes de la semaine", cover_title_style))
    story.append(Spacer(1, 1.5 * cm))
    sommaire_items = [
        ListItem(Paragraph(f"{c.name} — {c.people} personne(s)", styles["Normal"]))
        for c in choices
    ]
    story.append(ListFlowable(sommaire_items, bulletType="bullet"))
    story.append(PageBreak())

    # --- Une page par recette ---
    for choice in choices:
        recipe = recipes[choice.name]
        base = recipe["portions_base"]
        ratio = Fraction(choice.people, base)

        pil_image = get_recipe_image(choice.name, recipe["image"])
        img_buffer = io.BytesIO()
        pil_image.save(img_buffer, format="JPEG", quality=90)
        img_buffer.seek(0)
        rl_image = RLImage(img_buffer, width=15 * cm, height=9.4 * cm)
        rl_image.hAlign = "CENTER"

        story.append(Paragraph(choice.name, title_style))
        subtitle_parts = [f"Pour {choice.people} personne(s)"]
        prep = format_time_minutes(recipe.get("prep_time_minutes"))
        cook = format_time_minutes(recipe.get("cook_time_minutes"))
        if prep:
            subtitle_parts.append(f"Préparation : {prep}")
        if cook:
            subtitle_parts.append(f"Cuisson : {cook}")
        if recipe.get("tags"):
            subtitle_parts.append(", ".join(recipe["tags"]))
        story.append(Paragraph("  •  ".join(subtitle_parts), subtitle_style))
        if recipe.get("description"):
            story.append(Paragraph(recipe["description"], styles["Italic"]))
            story.append(Spacer(1, 6))
        story.append(rl_image)

        story.append(Paragraph("Ingrédients", section_style))

        for section_name, ingredients in recipe["ingredients"].items():
            story.append(Paragraph(section_name, styles["Heading3"]))

            table_data = [["Quantité", "Ingrédient"]]
            for ingredient_name, qty, unit in ingredients:
                scaled = Fraction(str(qty)).limit_denominator(100) * ratio
                qty_str = format_quantity(scaled)
                unit_str = "" if unit == "unité" else unit
                table_data.append([
                    f"{qty_str} {unit_str}".strip(),
                    ingredient_name.capitalize(),
                ])

            table = Table(table_data, colWidths=[4 * cm, 11 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFE7DA")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
            story.append(Spacer(1, 6))

        instructions = recipe.get("instructions")
        if instructions:
            story.append(Paragraph("Préparation", section_style))
            step_items = [
                ListItem(Paragraph(step, styles["Normal"]), leftIndent=10)
                for step in instructions
            ]
            story.append(ListFlowable(step_items, bulletType="1"))

        story.append(PageBreak())

    if story and isinstance(story[-1], PageBreak):
        story.pop()

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
