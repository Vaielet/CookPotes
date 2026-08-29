"""
common.py — Logique métier partagée entre les pages de l'application :
conversion d'unités, agrégation de la liste de courses, génération des
images de secours et du carnet de recettes PDF.
"""

from __future__ import annotations

import streamlit as st
import base64
import html
import io
import platform
import subprocess
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from fractions import Fraction

from PIL import Image, ImageDraw, ImageFont, ImageOps

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
            img = Image.open(io.BytesIO(image_bytes))
            # Beaucoup de photos (notamment prises au smartphone) stockent leur
            # orientation réelle dans les métadonnées EXIF plutôt que dans les
            # pixels eux-mêmes : sans ce correctif, une photo prise en portrait
            # peut s'afficher "à plat" en paysage. exif_transpose() applique la
            # rotation/le miroir indiqués par l'EXIF puis supprime cette
            # métadonnée (devenue inutile) du résultat.
            img = ImageOps.exif_transpose(img)
            return img.convert("RGB")
        except Exception:
            pass
    return generate_placeholder_image(name)


def prepare_image_for_storage(
    image_bytes: bytes,
    max_dimension: int = 1600,
    quality: int = 85,
) -> tuple[bytes, str]:
    """
    Prépare une photo pour l'enregistrement en base : applique l'orientation
    EXIF, réduit l'image si elle dépasse `max_dimension` px de large ou de
    haut (proportions conservées), puis la réencode en JPEG compressé.

    Les photos prises directement au smartphone pèsent souvent plusieurs Mo
    et dépassent largement la définition utile pour un affichage à l'écran
    ou une impression A4 — les stocker telles quelles alourdit inutilement
    la base de données et ralentit le chargement des pages. À appeler avant
    tout enregistrement d'une photo de recette.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), "image/jpeg"


def fit_image_to_canvas(
    img: Image.Image,
    size: tuple[int, int] = (400, 260),
    background: tuple[int, int, int] = (238, 231, 218),
) -> Image.Image:
    """
    Cale une image dans un cadre de dimensions `size` fixes, SANS la
    recadrer ni changer son orientation (une photo portrait reste
    portrait, une photo paysage reste paysage) : l'image est réduite pour
    tenir entièrement dans le cadre, puis centrée sur un fond uni qui
    comble l'espace restant (bordure/marge). Toutes les vignettes ainsi
    produites ont exactement les mêmes dimensions, quelle que soit
    l'orientation ou le ratio de la photo d'origine.
    """
    canvas = Image.new("RGB", size, color=background)
    thumb = img.copy()
    thumb.thumbnail(size, Image.LANCZOS)
    x = (size[0] - thumb.width) // 2
    y = (size[1] - thumb.height) // 2
    canvas.paste(thumb, (x, y))
    return canvas


def image_to_data_uri(img: Image.Image, format: str = "JPEG", quality: int = 85) -> str:
    """Encode une image PIL en data URI base64 pour l'intégrer dans du HTML (ex: st.markdown)."""
    buffer = io.BytesIO()
    img.save(buffer, format=format, quality=quality)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    mime = "image/jpeg" if format.upper() == "JPEG" else f"image/{format.lower()}"
    return f"data:{mime};base64,{encoded}"


# Dimensions fixes des vignettes recette, utilisées partout où une photo de
# recette est affichée (page d'accueil, générateur de liste, ...), pour un
# rendu homogène sur toute l'application.
RECIPE_CARD_IMAGE_SIZE = (400, 260)

# Fond orange uni de l'étiquette de nom superposée sur la photo.
RECIPE_CARD_LABEL_COLOR = "#E8730C"


def render_recipe_image_card(name: str, image: Image.Image, size: tuple[int, int] = RECIPE_CARD_IMAGE_SIZE) -> None:
    """
    Affiche la photo d'une recette dans un cadre de dimensions fixes
    (orientation d'origine conservée — portrait reste portrait, paysage
    reste paysage —, une marge est ajoutée si besoin pour uniformiser
    toutes les vignettes), avec le nom de la recette en étiquette orange
    superposée en bas de la photo.
    """
    canvas = fit_image_to_canvas(image, size=size)
    data_uri = image_to_data_uri(canvas)
    st.markdown(
        f"""
        <div style="position:relative; width:100%; margin-bottom:0.6em;
                    border-radius:10px; overflow:hidden; border:1px solid #ddd;">
          <img src="{data_uri}" style="width:100%; height:auto; display:block;" />
          <div style="position:absolute; bottom:0; left:0; right:0;
                      background:{RECIPE_CARD_LABEL_COLOR};
                      color:white; padding:0.5em 0.7em; font-weight:600;
                      font-size:1.05em; line-height:1.2;">
            {name}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
                lines.append(f"☐ {item}")
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
#
# Palette reprise de l'identité visuelle de l'app (même orange que les
# étiquettes de vignette recette, même beige que le fond des photos), pour
# que le PDF ait l'air de sortir du même site plutôt que d'un générateur
# générique.

PDF_ORANGE_HEX = "#E8730C"
PDF_ORANGE = colors.HexColor(PDF_ORANGE_HEX)
PDF_ORANGE_SOFT = colors.HexColor("#F8E6D3")   # fond zébré très léger des tableaux
PDF_BEIGE = colors.HexColor("#EEE7DA")          # fond de la carte d'en-tête (identique au fond photo)
PDF_INK = colors.HexColor("#3A2E22")            # texte principal, brun chaud plutôt que noir pur
PDF_GREY = colors.HexColor("#8A7F72")           # texte secondaire (sous-titres, pied de page)
PDF_LINE = colors.HexColor("#E3D9C8")           # filets/grilles discrets

# Chaque recette tient normalement sur une seule page (marges réduites,
# typographie compacte). Une recette avec beaucoup d'ingrédients ou
# d'étapes déborde naturellement sur la page suivante — Reportlab gère ça
# tout seul tant qu'on ne force pas de saut de page au milieu du contenu ;
# le PageBreak() explicite n'intervient qu'APRÈS chaque recette.
PDF_MARGIN = 1.6 * cm


def _pdf_footer(canvas, doc) -> None:
    """Pied de page discret sur chaque page : liseré orange + nom de l'app + numéro de page."""
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(PDF_ORANGE)
    canvas.setLineWidth(1)
    canvas.line(PDF_MARGIN, 1.25 * cm, width - PDF_MARGIN, 1.25 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(PDF_GREY)
    canvas.drawString(PDF_MARGIN, 0.8 * cm, "CookPotes")
    canvas.drawRightString(width - PDF_MARGIN, 0.8 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _underline_heading(text_str: str, style: ParagraphStyle, width: float) -> Table:
    """Titre de section avec un filet orange en-dessous, sur toute la largeur donnée."""
    t = Table([[Paragraph(text_str, style)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, PDF_ORANGE),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_recipe_booklet_pdf(
    choices: list[RecipeChoice],
    recipes: dict,
    title: str = "Carnet de recettes de la semaine",
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=PDF_MARGIN, bottomMargin=1.7 * cm,
        leftMargin=PDF_MARGIN, rightMargin=PDF_MARGIN,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "RecipeTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=19, leading=22, textColor=PDF_ORANGE, alignment=0,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=9.5, leading=13,
        textColor=PDF_GREY, spaceAfter=2,
    )
    tags_style = ParagraphStyle(
        "Tags", parent=styles["Normal"], fontSize=8.5, leading=12,
        textColor=PDF_ORANGE, spaceAfter=2,
    )
    description_style = ParagraphStyle(
        "Description", parent=styles["Italic"], fontSize=9.5, leading=12.5,
        textColor=PDF_INK, spaceBefore=3,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12.5, textColor=PDF_ORANGE, spaceBefore=0, spaceAfter=0,
        leading=15,
    )
    subsection_style = ParagraphStyle(
        "SubSection", parent=styles["Heading3"], fontName="Helvetica-Bold",
        fontSize=10, spaceBefore=6, spaceAfter=3, textColor=PDF_INK,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=PDF_INK,
    )
    cover_title_style = ParagraphStyle(
        "CoverTitle", parent=styles["Title"], fontSize=26, alignment=TA_CENTER,
        textColor=PDF_ORANGE,
    )
    cover_item_style = ParagraphStyle(
        "CoverItem", parent=styles["Normal"], fontSize=11.5, leading=19, textColor=PDF_INK,
    )

    CONTENT_WIDTH = A4[0] - 2 * PDF_MARGIN

    story = []

    # --- Page de couverture ---
    try:
        logo = RLImage("images/CookPotes_logo_with_subtitle.png", width=6.5 * cm, height=6.5 * cm)
        logo.hAlign = "CENTER"
        story.append(Spacer(1, 1.3 * cm))
        story.append(logo)
        story.append(Spacer(1, 1.8 * cm))
    except Exception:
        story.append(Spacer(1, 4 * cm))

    story.append(Paragraph(html.escape(title), cover_title_style))
    story.append(Spacer(1, 1.2 * cm))
    sommaire_items = [
        ListItem(
            Paragraph(f"<b>{html.escape(c.name)}</b> — {c.people} personne(s)", cover_item_style),
            spaceAfter=4,
        )
        for c in choices
    ]
    story.append(ListFlowable(
        sommaire_items, bulletType="bullet", bulletColor=PDF_ORANGE, bulletFontSize=11,
    ))
    story.append(PageBreak())

    # --- Une page par recette ---
    # Reportlab laisse le contenu s'écouler naturellement : si une recette a
    # beaucoup d'ingrédients ou d'étapes, la fin déborde toute seule sur une
    # page supplémentaire avant le PageBreak() explicite de fin de recette —
    # pas besoin de forcer quoi que ce soit pour ça. Le travail porte donc
    # sur la densité de la mise en page pour qu'une recette "normale" tienne
    # confortablement sur une seule page.
    PHOTO_HEIGHT_CM = 5
    PHOTO_WIDTH_CM = 6
    _dpi = 150
    _photo_canvas_size = (
        int(PHOTO_WIDTH_CM / 2.54 * _dpi),
        int(PHOTO_HEIGHT_CM / 2.54 * _dpi),
    )
    LEFT_COL_WIDTH = 6.2 * cm
    GUTTER_PT = 12
    RIGHT_COL_WIDTH = CONTENT_WIDTH - LEFT_COL_WIDTH - (GUTTER_PT / 72 * 2.54 * cm / 2.54)

    for choice in choices:
        recipe = recipes[choice.name]
        base = recipe["portions_base"]
        ratio = Fraction(choice.people, base)

        pil_image = get_recipe_image(choice.name, recipe["image"])
        canvas_image = fit_image_to_canvas(pil_image, size=_photo_canvas_size, background=(238, 231, 218))
        img_buffer = io.BytesIO()
        canvas_image.save(img_buffer, format="JPEG", quality=90)
        img_buffer.seek(0)
        rl_image = RLImage(img_buffer, width=PHOTO_WIDTH_CM * cm, height=PHOTO_HEIGHT_CM * cm)
        rl_image.hAlign = "CENTER"

        # --- Carte d'en-tête : titre + infos clés, fond beige + liseré orange ---
        header_flow = [Paragraph(html.escape(choice.name), title_style)]

        subtitle_parts = [f"{choice.people} personne(s)"]
        prep = format_time_minutes(recipe.get("prep_time_minutes"))
        cook = format_time_minutes(recipe.get("cook_time_minutes"))
        if prep:
            subtitle_parts.append(f"Préparation {prep}")
        if cook:
            subtitle_parts.append(f"Cuisson {cook}")
        header_flow.append(Paragraph(" &nbsp;·&nbsp; ".join(subtitle_parts), subtitle_style))

        if recipe.get("tags"):
            tags_txt = " &nbsp;&nbsp; ".join(html.escape(t) for t in recipe["tags"])
            header_flow.append(Paragraph(tags_txt, tags_style))

        if recipe.get("description"):
            header_flow.append(Paragraph(html.escape(recipe["description"]), description_style))

        header_table = Table([[header_flow]], colWidths=[CONTENT_WIDTH])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PDF_BEIGE),
            ("LINEBEFORE", (0, 0), (0, -1), 4, PDF_ORANGE),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 9))

        # --- Ingrédients : construits pour une largeur donnée (réutilisé
        # pour les deux mises en page ci-dessous) ---
        def _build_ingredients_flow(width: float) -> list:
            flow = [_underline_heading("Ingrédients", section_style, width)]
            flow.append(Spacer(1, 4))
            multi_section = len(recipe["ingredients"]) > 1
            for section_name, ingredients in recipe["ingredients"].items():
                if multi_section:
                    flow.append(Paragraph(html.escape(section_name), subsection_style))

                table_data = [["Qté", "Ingrédient"]]
                for ingredient_name, qty, unit in ingredients:
                    scaled = Fraction(str(qty)).limit_denominator(100) * ratio
                    qty_str = format_quantity(scaled)
                    unit_str = "" if unit == "unité" else unit
                    table_data.append([
                        f"{qty_str} {unit_str}".strip(),
                        ingredient_name.capitalize(),
                    ])

                ing_table = Table(
                    table_data,
                    colWidths=[2.3 * cm, width - 2.3 * cm],
                    repeatRows=1,
                )
                ing_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), PDF_ORANGE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PDF_ORANGE_SOFT]),
                    ("GRID", (0, 0), (-1, -1), 0.4, PDF_LINE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                flow.append(ing_table)
                flow.append(Spacer(1, 5))
            return flow

        # Un tableau photo+ingrédients côte à côte n'a qu'UNE seule ligne :
        # Reportlab ne peut pas le scinder sur deux pages, il plante si le
        # contenu est trop haut. Pour les recettes avec beaucoup
        # d'ingrédients, on bascule donc sur une mise en page empilée
        # (photo, puis ingrédients pleine largeur) qui, elle, se scinde
        # naturellement sur autant de pages que nécessaire.
        total_ingredient_rows = sum(len(rows) for rows in recipe["ingredients"].values())
        use_side_by_side = total_ingredient_rows <= 22

        if use_side_by_side:
            # --- Photo (gauche) + ingrédients (droite), côte à côte ---
            ingredients_flowables = _build_ingredients_flow(RIGHT_COL_WIDTH)
            layout_table = Table(
                [[rl_image, ingredients_flowables]],
                colWidths=[LEFT_COL_WIDTH, RIGHT_COL_WIDTH],
            )
            layout_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (0, 0), 0.6, PDF_LINE),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 0),
                ("LEFTPADDING", (1, 0), (1, -1), GUTTER_PT),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(layout_table)
            story.append(Spacer(1, 10))
        else:
            # --- Mise en page empilée pour les grosses recettes ---
            img_buffer.seek(0)  # rl_image a déjà consommé la lecture du buffer une première fois
            small_image = RLImage(img_buffer, width=4.2 * cm, height=3.5 * cm)
            small_image.hAlign = "LEFT"
            story.append(small_image)
            story.append(Spacer(1, 8))
            for flowable in _build_ingredients_flow(CONTENT_WIDTH):
                story.append(flowable)
            story.append(Spacer(1, 4))

        # --- Étapes de préparation, sous la photo et les ingrédients ---
        instructions = recipe.get("instructions")
        if instructions:
            story.append(_underline_heading("Préparation", section_style, CONTENT_WIDTH))
            story.append(Spacer(1, 4))
            step_items = [
                ListItem(Paragraph(html.escape(step), body_style), leftIndent=6, spaceAfter=4)
                for step in instructions
            ]
            story.append(ListFlowable(
                step_items, bulletType="1", bulletColor=PDF_ORANGE, bulletFontName="Helvetica-Bold",
            ))

        story.append(PageBreak())

    if story and isinstance(story[-1], PageBreak):
        story.pop()

    doc.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    buffer.seek(0)
    return buffer.getvalue()
