#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Branding — composition de l'icône de l'installateur self-extracting.

Prend l'icône de l'utilisateur et y incruste un petit marquage « Jenga » en bas
à droite (pill sombre semi-transparente + texte blanc gras). Discret mais
visible : l'icône user reste le focal point.

Pillow est soft-dep (comme dans `Core/IconConverter.py`) : si absent ou échec,
la fonction retourne False et l'appelant utilise l'icône user telle quelle.

Nomenclature : fonctions/classes en PascalCase, variables locales en snake_case.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont   # type: ignore
    _PILLOW_OK = True
except ImportError:
    Image = ImageDraw = ImageFont = None          # type: ignore
    _PILLOW_OK = False

# Tailles standards d'un .ico Windows (mêmes que `Core/IconConverter.py`).
DEFAULT_ICO_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# Sous ce seuil (px), le texte "Jenga" devient illisible — on saute l'overlay.
MIN_SIZE_FOR_TEXT_OVERLAY = 48

# Polices TTF préférées par OS (gras pour la lisibilité dans une pill).
_FONT_CANDIDATES = (
    # Windows
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    # Linux (Dejavu/Liberation sont quasi-omniprésents)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def IsAvailable() -> bool:
    """Indique si la composition d'icône est disponible (Pillow installé)."""
    return _PILLOW_OK


def ComposeInstallerIcon(user_icon: Path, output: Path,
                          brand_text: str = "Jenga",
                          sizes: Iterable[int] = DEFAULT_ICO_SIZES) -> bool:
    """
    Produit un `.ico` multi-tailles à partir de l'icône user, avec marquage
    « Jenga » incrusté en bas à droite des tailles >= 48px.

    Retourne True si OK, False si :
      * Pillow n'est pas installé (-> l'appelant utilise user_icon tel quel) ;
      * user_icon est introuvable ou illisible ;
      * la composition échoue (cas pathologique).

    `output` est toujours produit avec extension `.ico` (Windows). Sur macOS,
    le branding s'applique aussi mais le caller doit ensuite convertir en
    `.icns` via `Core/IconConverter.ConvertPngToIcns`.
    """
    user_icon = Path(user_icon)
    output = Path(output)
    if not _PILLOW_OK:
        return False
    if not user_icon.exists():
        return False

    try:
        base = _LoadIconAsRgba(user_icon, max(sizes))
    except Exception:
        return False

    composed_layers: List[Image.Image] = []
    for size in sorted(set(sizes)):
        scaled = base.resize((size, size), Image.LANCZOS)
        if size >= MIN_SIZE_FOR_TEXT_OVERLAY:
            scaled = _OverlayBrandPill(scaled, brand_text)
        composed_layers.append(scaled)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Pillow sauvegarde un .ico multi-tailles : on passe la plus grande
        # comme image principale, et les autres via le param `sizes`.
        primary = composed_layers[-1]
        primary.save(output, format="ICO",
                     sizes=[(layer.width, layer.height) for layer in composed_layers],
                     append_images=composed_layers[:-1])
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────────────────────────────────────
def _LoadIconAsRgba(path: Path, target_size: int):
    """Charge n'importe quelle icône (.ico/.png/.jpg) en RGBA carrée. Pour un
    .ico multi-frames, on prend la frame la plus grande (>= target_size si
    dispo, sinon la plus grande disponible)."""
    img = Image.open(path)
    # ICO multi-frames : choisir la meilleure source.
    if getattr(img, "n_frames", 1) > 1:
        best = None
        for i in range(img.n_frames):
            img.seek(i)
            if best is None or img.size[0] > best.size[0]:
                best = img.copy()
        img = best or img
    img = img.convert("RGBA")
    # Carré centré si pas déjà.
    w, h = img.size
    if w != h:
        side = max(w, h)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(img, ((side - w) // 2, (side - h) // 2))
        img = square
    if img.size[0] < target_size:
        img = img.resize((target_size, target_size), Image.LANCZOS)
    return img


def _OverlayBrandPill(icon, brand_text: str):
    """Ajoute une pill sombre semi-transparente + texte blanc gras en bas à
    droite. La taille scale avec celle de l'icône."""
    icon = icon.copy()
    size = icon.size[0]
    overlay = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Police : ~16% de la hauteur de l'icône, plancher 9px.
    text_px = max(9, int(size * 0.16))
    font = _LoadBrandFont(text_px)
    if font is None:
        return icon  # pas de font utilisable -> on rend l'icône clean

    # Mesure du texte. Pillow >= 9.2 : font.getbbox(text) ; sinon textsize.
    bbox = _MeasureText(draw, brand_text, font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Marges/padding scalent avec la taille.
    pad_x = max(2, int(size * 0.05))
    pad_y = max(1, int(size * 0.02))
    margin = max(2, int(size * 0.06))

    pill_w = text_w + 2 * pad_x
    pill_h = text_h + 2 * pad_y
    pill_x = size - margin - pill_w
    pill_y = size - margin - pill_h
    # Si la pill déborderait (icône très petite), on abandonne l'overlay.
    if pill_x < 0 or pill_y < 0:
        return icon

    radius = max(2, int(pill_h * 0.45))
    fill = (20, 20, 20, 200)             # noir semi-transparent
    border = (255, 255, 255, 90)         # liséré blanc tres subtil

    # Pillow >= 8.2 : rounded_rectangle ; sinon, fallback rectangle simple.
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=radius, fill=fill, outline=border, width=max(1, size // 128))
    else:
        draw.rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
                       fill=fill, outline=border)

    # Texte (blanc, bold est dans la TTF choisie).
    text_x = pill_x + pad_x - bbox[0]
    text_y = pill_y + pad_y - bbox[1]
    draw.text((text_x, text_y), brand_text, fill=(255, 255, 255, 255), font=font)

    return Image.alpha_composite(icon, overlay)


def _LoadBrandFont(size_px: int):
    """Cherche une TTF gras adéquate ; fallback Pillow par défaut sinon."""
    for candidate in _FONT_CANDIDATES:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size_px)
            except OSError:
                continue
    # Fallback : font bitmap de Pillow (pas de taille variable, mais évite le crash).
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _MeasureText(draw, text: str, font):
    """Retourne (x0, y0, x1, y1) de la bbox d'un texte rendu avec `font`,
    compatible Pillow 8+ (getbbox) et anciennes versions (textsize)."""
    if hasattr(font, "getbbox"):
        bbox = font.getbbox(text)
        return bbox
    # Pillow ancien (< 9.2) : textsize sur le draw, puis bbox synthétique.
    w, h = draw.textsize(text, font=font)   # type: ignore[attr-defined]
    return (0, 0, w, h)
