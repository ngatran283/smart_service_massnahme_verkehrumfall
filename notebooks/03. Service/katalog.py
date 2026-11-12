import pandas as pd
import numpy as np


def massnahmen_empfehlen(df_unf, df_fzg, katalog, min_n=30, basis_unf=None, basis_fzg=None):
    """Prüft jede Situation auf der passenden Ebene und gibt Maßnahmen nach Überschuss priorisiert aus.
    basis_unf/basis_fzg: Vergleichsmaßstab (Standard: Durchschnitt des übergebenen Datenausschnitts).
    Für einzelne Zellen wird der stadtweite Durchschnitt übergeben."""
    rows = []
    for m in katalog:
        df_ = df_unf if m["Ebene"] == "Unfall" else df_fzg
        basis = basis_unf if m["Ebene"] == "Unfall" else basis_fzg
        if basis is None:
            basis = df_["schwer"].mean()
        s = df_[m["Bedingung"](df_)]
        if len(s) < min_n:
            continue
        ueberschuss = s["schwer"].sum() - len(s) * basis
        if ueberschuss <= 0:
            continue
        rows.append({"ID": m["ID"], "Situation": m["Situation"], "Ebene": m["Ebene"], "n": len(s),
                     "Anteil_schwer_%": round(s["schwer"].mean() * 100, 1),
                     "Ueberschuss": round(ueberschuss),
                     "Massnahme": m["Massnahme"], "3E": m["3E"], "Quelle": m["Quelle"]})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("Ueberschuss", ascending=False).reset_index(drop=True)
    out.index = out.index + 1
    out.index.name = "Prio"
    return out


katalog = [
    {"ID": "M1", "Ebene": "Unfall", "Situation": "Abend/Nacht (20–5 Uhr) in Büro-/Wohngebieten",
     "Bedingung": lambda d: (d["Abend_Nacht"] == 1)
                            & d["Area_accident_occured"].isin(["Office areas", "Residential areas"]),
     "Massnahme": "Abendliche Geschwindigkeitskontrollen, Tempo 30, Verkehrsberuhigung",
     "3E": "Enforcement, Engineering", "Quelle": "WHO Save LIVES: Speed management"},
    {"ID": "M2", "Ebene": "Unfall", "Situation": "Kollision mit Objekten am Straßenrand",
     "Bedingung": lambda d: d["Type_of_collision"] == "Collision with roadside objects",
     "Massnahme": "Schutzplanken, Leitpfosten, Absicherung von Hindernissen",
     "3E": "Engineering", "Quelle": "iRAP: Roadside safety barriers"},
    {"ID": "M3", "Ebene": "Fahrzeug", "Situation": "Fahrer unter 18 Jahren",
     "Bedingung": lambda d: d["Age_band_of_driver"] == "Under 18",
     "Massnahme": "Führerscheinkontrollen, Halterhaftung",
     "3E": "Enforcement", "Quelle": "WHO Save LIVES: Enforcement"},
    {"ID": "M4", "Ebene": "Fahrzeug", "Situation": "Überholen / Fahren auf der Gegenspur",
     "Bedingung": lambda d: d["Cause_of_accident"].isin(["Overtaking", "Driving to the left"]),
     "Massnahme": "Überholverbote, Mittelleitplanken",
     "3E": "Engineering, Enforcement", "Quelle": "iRAP: Median"},
    {"ID": "M5", "Ebene": "Unfall", "Situation": "Dunkelheit ohne Straßenbeleuchtung",
     "Bedingung": lambda d: d["Light_conditions"] == "Darkness - no lighting",
     "Massnahme": "Straßenbeleuchtung nachrüsten",
     "3E": "Engineering", "Quelle": "iRAP: Street Lighting"},
    {"ID": "M6", "Ebene": "Unfall", "Situation": "Fußgängerunfälle bei Dunkelheit",
     "Bedingung": lambda d: d["Light_conditions"].str.startswith("Darkness")
                            & (d["Type_of_collision"] == "Collision with pedestrians"),
     "Massnahme": "Beleuchtete Fußgängerüberwege, Mittelinseln",
     "3E": "Engineering", "Quelle": "iRAP: Pedestrian Crossing Facilities"},
    {"ID": "M7", "Ebene": "Unfall", "Situation": "Freie Strecke (kein Knotenpunkt) abends/nachts",
     "Bedingung": lambda d: (d["Types_of_Junction"] == "No junction") & (d["Abend_Nacht"] == 1),
     "Massnahme": "Streckenbezogene Geschwindigkeitsüberwachung, Leitpfosten, Fahrbahnmarkierung",
     "3E": "Enforcement, Engineering", "Quelle": "WHO Save LIVES: Speed management; iRAP: Delineation"},
]