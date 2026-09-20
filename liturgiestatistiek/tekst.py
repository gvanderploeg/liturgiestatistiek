"""Hulpfuncties voor het normaliseren van tekst en het maken van sleutels."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_AANHALINGSTEKENS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def eenvoudig(tekst: str) -> str:
    """Kleine letters, rechte aanhalingstekens, enkele spaties."""
    tekst = (tekst or "").translate(_AANHALINGSTEKENS)
    return " ".join(tekst.split()).strip().lower()


def normaliseer(tekst: str) -> str:
    """Vergelijkingsvorm: kleine letters, geen accenten, alleen letters, cijfers en spaties."""
    tekst = eenvoudig(tekst)
    tekst = unicodedata.normalize("NFKD", tekst)
    tekst = "".join(c for c in tekst if not unicodedata.combining(c))
    tekst = re.sub(r"[^a-z0-9&]+", " ", tekst)
    return " ".join(tekst.split())


def slug(tekst: str) -> str:
    return normaliseer(tekst).replace("&", "en").replace(" ", "-")


def sleutel(*delen: str) -> str:
    """Korte, stabiele hash van tekst. Gebruikt om naar een rij te verwijzen zonder de tekst zelf op te slaan."""
    basis = "|".join(normaliseer(d) for d in delen)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
