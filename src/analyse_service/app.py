"""
Analyse-Service des Smart Service „Priorisierung von Maßnahmen gegen schwere Verkehrsunfälle".
Endpunkte
  POST /analyse        – wird von ThingsBoard (Rule Chain, REST API Call) für JEDE neue Unfallmeldung aufgerufen
  POST /neuberechnen   – stadtweite Neuberechnung (läuft zusätzlich automatisch alle RECALC_SECONDS)
  POST /entdecken      – Erkennung neuer Problemsituationen (Entscheidungsbaum, läuft zusätzlich
                         bei jeder ENTDECKEN_ALLE-ten Neuberechnung)
"""
import json
import os
import threading
import time
from collections import defaultdict, deque
import pandas as pd
from fastapi import Body, FastAPI

from entdeckung import entdecken as baum_entdecken
from katalog import massnahmen_empfehlen, MAX_MASSNAHMEN, KOSTEN, KATALOG
from tb_client import ThingsBoard

TAG_MS = 24 * 3600 * 1000
FENSTER_ALARM_TAGE = 90           # Fenster für den Service-Trigger
FENSTER_REGEL_TAGE = 365          # Fenster für Maßnahmenempfehlung und Hotspot-Ranking
MIN_RELEVANT = int(os.getenv("MIN_RELEVANT", 20))
RECALC_SECONDS = int(os.getenv("RECALC_SECONDS", 60))
STATUS_DATEI = os.getenv("STATUS_DATEI", "/daten/massnahmen_status.json")
FEED_GERATE = os.getenv("FEED_GERATE", "Polizei-Feed")
KPI_SERVICE = os.getenv("KPI_SERVICE", "Smart-Service-KPI")
HINWEIS_GERATE = os.getenv("HINWEIS_GERATE", "Problemerkennung")   # eigenes Gerät, damit keine Schleife über die Rule Chain
ENTDECKEN_ALLE = int(os.getenv("ENTDECKEN_ALLE", 10))             # alle 10 Neuberechnungen (= 10 Minuten)

app = FastAPI(title="Analyse-Service Verkehrsunfälle")
tb = ThingsBoard()
sperre = threading.Lock()
zellen = defaultdict(deque)
"""
zellen = {
    "998_4309":  deque([case1, case5, case9, ...]),   # Zelle → Unfälle der letzten 12 Monate
    "1003_4320": deque([case2, case7, ...]),
    ...
}
"""
alle = deque()                    # alle Unfälle der letzten 12 Monate (für den Durchschnitt)
zustand = {"basis": 0.166, "letzter_ts": 0, "hotspots": [], "kpis": {}, "meldungen": 0,
           "neuberechnungen": 0, "entdeckung": []}

SPALTEN = {"Knoten": "Types_of_Junction", "Area": "Area_accident_occured",
           "Licht": "Light_conditions", "Kollision": "Type_of_collision",
           "Ursache": "Cause_of_accident", "Alter": "Age_band_of_driver"}

def als_dataframe(unfalle):
    df = pd.DataFrame(unfalle).rename(columns=SPALTEN)
    df["Abend_Nacht"] = ((df["Stunde"] >= 20) | (df["Stunde"] <= 5)).astype(int)
    return df

def lade_status():
    """Umgesetzte Maßnahmen (in der Praxis von der Verkehrsbehörde gepflegt)."""
    try:
        with open(STATUS_DATEI, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def zellname(z):
    return f"Zelle {z}"


def kuerzen(dq, ts, tage):
    while dq and dq[0]["ts"] < ts - tage * TAG_MS:
        dq.popleft()


def fenster(unfalle, ts, tage):
    return [u for u in unfalle if u["ts"] >= ts - tage * TAG_MS]

'''
Ablauf je Unfallmeldung
  1. Unfall der GPS-Zelle zuordnen und speichern (gleitend 12 Monate)
  2. Schwere Unfälle der letzten 90 Tage zählen → Überschuss gegenüber dem Durchschnitt
  3. Ist die Zelle relevant (≥ MIN_RELEVANT Unfälle in 12 Monaten): Regelwerk anwenden → Maßnahme
  4. Ergebnis als Telemetrie/Attribute an das Zellen-Gerät in ThingsBoard schreiben
     → das Geräteprofil „Zelle" löst bei ueberschuss_90T ≥ Schwelle einen Alarm aus
'''
@app.post("/analyse")
def analyse(d: dict = Body(...)):
    if "ts_ms" not in d or "Zelle" not in d:
        return {"hinweis": "keine Unfallmeldung – ignoriert"}
    u = {
        "ts": int(d["ts_ms"]), "zelle": d["Zelle"], "schwer": int(d["schwer"]),
        "Knoten": d.get("Knoten"), "Area": d.get("Area"), "Stunde": int(d.get("Stunde", 0)),
        "Licht": d.get("Licht"), "Kollision": d.get("Kollision"), "Ursache": d.get("Ursache"),
        "Alter": d.get("Alter"), "lat": d.get("latitude"), "lon": d.get("longitude"),
    }
    with sperre:
        z = zellen[u["zelle"]]
        z.append(u); alle.append(u)
        kuerzen(z, u["ts"], FENSTER_REGEL_TAGE); kuerzen(alle, u["ts"], FENSTER_REGEL_TAGE)
        zustand["letzter_ts"] = max(zustand["letzter_ts"], u["ts"]); zustand["meldungen"] += 1
        basis = zustand["basis"]
        jahr = list(z)
    # filter 90 days
    f90 = fenster(jahr, u["ts"], FENSTER_ALARM_TAGE)
    n90, s90 = len(f90), sum(x["schwer"] for x in f90)
    ergebnis = {"zelle": u["zelle"], "unfalle_90T": n90, "schwer_90T": s90,
                "ueberschuss_90T": round(s90 - n90 * basis, 1), "relevant": len(jahr) >= MIN_RELEVANT}

    if ergebnis["relevant"]:
        df = als_dataframe(jahr)
        empf = massnahmen_empfehlen(df, df, KATALOG, min_n=10, basis_unf=basis, basis_fzg=basis)
        top3 = empf.head(MAX_MASSNAHMEN)
        top = empf.iloc[0] if not empf.empty else None
        ergebnis.update({"massnahme_id": ", ".join(top3["ID"]) if top is not None else "–",
                         "massnahme": top["Massnahme"] if top is not None
                         else "keine eindeutige Situation – Vor-Ort-Prüfung"})
        liste = " | ".join(f'{i}. {r["ID"]} {r["Massnahme"]} – {r["Situation"]}: {r["Anteil_schwer_%"]} % schwer, '
                           f'n = {r["n"]}, Überschuss +{r["Ueberschuss"]}, ca. {KOSTEN[r["ID"]]} €/Jahr'
                           for i, (_, r) in enumerate(top3.iterrows(), 1))
        name = zellname(u["zelle"])
        tb.telemetrie(name, {"schwer": u["schwer"], "unfaelle_90T": n90, "schwer_90T": s90,
                             "anteil_schwer_90T": round(s90 / n90 * 100, 1),
                             "ueberschuss_90T": ergebnis["ueberschuss_90T"]}, ts=u["ts"])
        tb.attribute(name, {"Massnahme_ID": ergebnis["massnahme_id"], "Massnahme": ergebnis["massnahme"],
                            "Begruendung": (f'{top["Situation"]}: {top["Anteil_schwer_%"]} % schwer '
                                            f'(n = {top["n"]}, Überschuss +{top["Ueberschuss"]})') if top is not None else "",
                            "Massnahmen_Vorschlaege": liste,
                            "latitude": u["lat"], "longitude": u["lon"], "unfaelle_12M": len(jahr)})
    return ergebnis


@app.post("/neuberechnen")
def neuberechnen():
    t0 = time.time()
    with sperre:
        if not alle:
            return {"hinweis": "noch keine Daten"}
        jetzt = zustand["letzter_ts"]
        basis = sum(u["schwer"] for u in alle) / len(alle)          # stadtweiter Durchschnitt (12 Monate)
        zustand["basis"] = basis
        kopie = {k: list(v) for k, v in zellen.items()}

    # Hotspot-Ranking: relevante Zellen nach Überschuss (12 Monate)
    ranking = sorted(((z, sum(x["schwer"] for x in v) - len(v) * basis, len(v))
                      for z, v in kopie.items() if len(v) >= MIN_RELEVANT), key=lambda t: t[1], reverse=True)
    neue_hs = [z for z, _, _ in ranking[:3]]
    for alt in set(zustand["hotspots"]) - set(neue_hs):
        tb.attribute(zellname(alt), {"ist_Hotspot": False, "Rang": 0})
    for rang, (z, ue, n) in enumerate(ranking[:3], 1):
        tb.attribute(zellname(z), {"ist_Hotspot": True, "Rang": rang, "ueberschuss_12M": round(ue, 1)})
    zustand["hotspots"] = neue_hs

    # Wirkungsmessung umgesetzter Maßnahmen: Vorher-Nachher mit Kontrollzellen (DiD, je Jahr)
    status = lade_status()
    def schwer_rate(unf, von, bis):
        tage = max((bis - von) / TAG_MS, 1)
        return sum(x["schwer"] for x in unf if von <= x["ts"] < bis) / tage * 365

    wirkung, kosten, umgesetzt = 0.0, 0, 0
    for z, info in status.items():
        tb.attribute(zellname(z), {"Rolle": "Massnahmen-Hotspot", "Massnahme_umgesetzt": bool(info.get("umgesetzt"))})
        for k in info["kontrolle"]:
            tb.attribute(zellname(k), {"Rolle": "Kontrolle", "Kontrolle_fuer": zellname(z)})
        if not info.get("umgesetzt"):
            continue
        umgesetzt += 1
        seit = int(info["seit_ms"])
        if jetzt <= seit: # noch keine Nachher-Daten
            continue
        #dif-in-dif: hotspot anderung, kontrolle anderung
        d_hs = schwer_rate(kopie.get(z, []), seit, jetzt) - info["vorher_schwer"]
        d_k = [schwer_rate(kopie.get(k, []), seit, jetzt) - info["kontrolle_vorher_schwer"][k] for k in info["kontrolle"]]
        did = d_hs - sum(d_k) / len(d_k)
        wirkung += -did # did < 0 -> vermeiden -did
        kosten += KOSTEN[info["massnahme"]]
        tb.attribute(zellname(z), {"umgesetzt": True, "DiD_schwer_je_Jahr": round(did, 1)})

    empfohlen = max(len([s for s in status.values()]), 1)
    kpis = {"vermiedene_schwere_unfalle_DiD": round(wirkung, 1), #kpi1
            "Kosten_je_vermiedenem_Unfall_EUR": round(kosten / wirkung) if wirkung > 0 else None, #kpi2
            "Umsetzungsquote_Prozent": round(umgesetzt / empfohlen * 100), #kpi3
            "Aktualisierungsdauer_s": round(time.time() - t0, 3), #kpi4
            "Durchschnitt_schwer_Prozent": round(basis * 100, 1),
            "Hotspots": ", ".join(zellname(z) for z in neue_hs)}
    zustand["kpis"] = kpis
    tb.attribute(KPI_SERVICE, kpis, typ="default")
    return kpis

@app.post("/entdecken")
def entdecken():
    """Sucht mit einem Entscheidungsbaum Situationen mit vielen schweren Unfällen, die der Katalog nicht abdeckt."""
    with sperre:
        daten, basis, jetzt = list(alle), zustand["basis"], zustand["letzter_ts"]
    situationen = baum_entdecken(daten, basis)
    neu = [x for x in situationen if x["status"] == "NEU"]
    zustand["entdeckung"] = situationen
    text = " | ".join(f'{x["situation"]}: {x["anteil"]} % schwer (n = {x["n"]}, Überschuss +{x["ueberschuss"]}, '
                      f'Katalog deckt {x["abgedeckt_prozent"]} % ab)' for x in neu) or "keine"
    tb.telemetrie(HINWEIS_GERATE, {"anzahl_neue_Situationen": len(neu)}, ts=jetzt or None, typ="Hinweis")
    tb.attribute(HINWEIS_GERATE, {"neue_Situationen": text, "gepruft_unfalle": len(daten),
                                  "Situationen_gesamt": len(situationen)}, typ="Hinweis")
    return {"neu": neu, "alle": situationen}


def periodisch():
    while True:
        time.sleep(RECALC_SECONDS)
        try:
            neuberechnen()
            zustand["neuberechnungen"] += 1
            if zustand["neuberechnungen"] % ENTDECKEN_ALLE == 0:
                entdecken()
        except Exception as e:
            print("Neuberechnung fehlgeschlagen:", e)


@app.on_event("startup")
def start():
    threading.Thread(target=periodisch, daemon=True).start()
