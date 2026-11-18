"""
Erkennung neuer Problemsituationen (lernfähiger Teil des Smart Service, vgl. Kapitel 6.1 des Notebooks).

Ein kleiner Entscheidungsbaum sucht OHNE Vorgabe von Regeln nach Situationen mit vielen schweren
Unfällen. Jedes Blatt des Baums ist eine Situation. Für jedes Blatt wird geprüft:
  1. Ist es auffällig?      Überschuss > 0 und untere Grenze des 95-%-Konfidenzintervalls (Wilson)
                            über dem stadtweiten Durchschnitt
  2. Ist es abgedeckt?      Erfüllen mind. 50 % der Unfälle im Blatt eine Regel aus dem Katalog M1–M7?
Auffällig und NICHT abgedeckt → Status „NEU“ → Meldung an die Verkehrsbehörde (Human-in-the-loop).
Die Behörde entscheidet, ob eine neue Maßnahme (M8 …) in regelwerk.py aufgenommen wird.

Merkmale: nur Felder, die in jeder Unfallmeldung enthalten sind (Wetter und Wochentag fehlen im Feed).
"""
import math
import os

from sklearn.tree import DecisionTreeClassifier, _tree
from katalog import KATALOG, abend_nacht

MERKMALE = {
    "Abend/Nacht":           abend_nacht,
    "freie Strecke":         lambda u: u["Knoten"] == "No junction",
    "Wohngebiet":            lambda u: u["Area"] == "Residential areas",
    "Bürogebiet":            lambda u: u["Area"] == "Office areas",
    "Dunkelheit":            lambda u: str(u["Licht"]).startswith("Darkness"),
    "Dunkelheit ohne Licht": lambda u: u["Licht"] == "Darkness - no lighting",
    "Fußgänger":             lambda u: u["Kollision"] == "Collision with pedestrians",
    "Objekt am Rand":        lambda u: u["Kollision"] == "Collision with roadside objects",
    "Fahrer unter 18":       lambda u: u["Alter"] == "Under 18",
    "Überholen/Gegenspur":   lambda u: u["Ursache"] in ("Overtaking", "Driving to the left"),
}
NAMEN = list(MERKMALE)

# Nur für Test/Demo: Regeln, die bei der Abdeckungsprüfung „vergessen“ werden (z. B. "M3").
# So lässt sich zeigen, dass der Baum eine Situation findet, für die es (noch) keine Regel gibt.
OHNE = {r.strip() for r in os.getenv("ENTDECKUNG_OHNE", "").split(",") if r.strip()}


def wilson_unten(s, n, z=1.96):
    """Untere Grenze des 95-%-Konfidenzintervalls für den Anteil s/n (Wilson)."""
    if n == 0:
        return 0.0
    p = s / n
    mitte = p + z * z / (2 * n)
    rand = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (mitte - rand) / (1 + z * z / n)


def entdecken(unfalle, basis=None, max_tiefe=3, min_blatt=150, min_abdeckung=0.5):
    """Liefert alle Situationen (Blätter) mit Status, sortiert nach Überschuss.

    unfalle: Liste von dicts (Felder wie in der Unfallmeldung, dazu "schwer" 0/1)
    basis:    stadtweiter Anteil schwerer Unfälle; ohne Angabe aus den Daten berechnet
    """
    if len(unfalle) < 2 * min_blatt:
        return []
    X = [[int(bool(f(u))) for f in MERKMALE.values()] for u in unfalle]
    y = [u["schwer"] for u in unfalle]
    basis = basis if basis is not None else sum(y) / len(y)

    baum = DecisionTreeClassifier(max_depth=max_tiefe, min_samples_leaf=min_blatt, random_state=0).fit(X, y)
    t = baum.tree_
    katalog = [m for m in KATALOG if m["id"] not in OHNE]

    def pfade(knoten=0, bed=()):                       # Weg von der Wurzel zu jedem Blatt
        if t.feature[knoten] == _tree.TREE_UNDEFINED:
            yield knoten, bed
            return
        name = NAMEN[t.feature[knoten]]
        yield from pfade(t.children_left[knoten], bed + (f"nicht {name}",))
        yield from pfade(t.children_right[knoten], bed + (name,))

    blatt_von = baum.apply(X)
    ergebnis = []
    for knoten, bed in pfade():
        idx = [i for i, b in enumerate(blatt_von) if b == knoten]
        im_blatt = [unfalle[i] for i in idx]
        n, s = len(idx), sum(y[i] for i in idx)
        uberschuss = s - n * basis
        abgedeckt = sum(any(m["bedingung"](u) for m in katalog) for u in im_blatt) / n
        je_regel = {m["id"]: sum(bool(m["bedingung"](u)) for u in im_blatt) / n for m in katalog}
        beste = max(je_regel, key=je_regel.get)

        if uberschuss <= 0 or wilson_unten(s, n) <= basis:
            status = "unauffällig"
        elif abgedeckt >= min_abdeckung:
            status = f"abgedeckt (v. a. {beste})"
        else:
            status = "NEU"
        ergebnis.append({"situation": " & ".join(bed), "n": n, "schwer": s,
                         "anteil": round(s / n * 100, 1), "uberschuss": round(uberschuss, 1),
                         "abgedeckt_prozent": round(abgedeckt * 100), "status": status})
    return sorted(ergebnis, key=lambda e: e["uberschuss"], reverse=True)
