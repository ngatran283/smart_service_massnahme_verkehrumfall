# Set up Thingsboard
Unfallmeldungen kommen per MQTT in ThingsBoard an, eine Rule Chain
ruft für jede Meldung den Analyse-Service auf, dieser bewertet die betroffene GPS-Zelle, wählt anhand des
Regelwerks eine Maßnahme und schreibt das Ergebnis zurück. ThingsBoard löst Alarme aus und zeigt alles im Dashboard.

```
tb_feed.py ──MQTT──► ThingsBoard ──Rule Chain: REST API Call──► Analyse-Service (FastAPI)
(Polizei,            Gerät „Polizei-Feed"                         /analyse       je Meldung
 simuliert)                                                       /neuberechnen  alle 60 s
                     Geräte „Zelle …"  ◄──── Telemetrie/Attribute ─┘
                     Geräteprofil „Zelle": Alarm bei ueberschuss_90T ≥ 4
                     Dashboard
```

## Inhalt

| Datei | Aufgabe |
|---|---|
| `docker-compose.yml` | Startet PostgreSQL, ThingsBoard CE und den Analyse-Service |
| `analyse_service/katalog.py` | Maßnahmenkatalog M1–M7 (aus Kapitel 5 des Notebooks; ohne Fahrzeuganzahl) |
| `analyse_service/app.py` | Analyse-Service: Zellenbewertung, Empfehlung, Hotspot-Ranking, KPIs |
| `analyse_service/tb_client.py` | Schreibt Ergebnisse über die REST-API in ThingsBoard |
| `tb_feed.py` | Datenquelle: sendet Unfallmeldungen per MQTT (simuliert die Polizei) |
| `daten/thingsboard_datenfeed.csv` | Unfälle 2025 (Datensatz) und 2026 (simuliert), aus dem Notebook |
| `daten/massnahmen_status.json` | Umgesetzte Maßnahmen und Kontrollzellen (pflegt in der Praxis die Verkehrsbehörde) |

---

## 1 Plattform starten

```bash
docker compose run --rm -e INSTALL_TB=true -e LOAD_DEMO=true thingsboard-ce   
docker compose up -d --build
docker compose logs -f thingsboard-ce       
```

- ThingsBoard: <http://localhost:8080> – Login **tenant@thingsboard.org / tenant**
- Analyse-Service: <http://localhost:8000> 

## 2 Geräteprofile anlegen (Profiles → Device profiles → +)

1. Polizei-Feed - Rule Chain "Unfall-Analyse"
2. Hinweis - Device: Smart-Service-KPI und Problemerkennung
3. Zelle – Reiter **Alarm rules → Add alarm rule**
   - Alarm type: `Hotspot-Warnung`
   - Create alarm: Severity *Major*, Bedingung: Telemetrie `ueberschuss_90T` **größer oder gleich 4**
   - Clear alarm: Bedingung: `ueberschuss_90T` **kleiner als 2**

## 3 Daten einspielen (Vorlauf)

```bash
pip install paho-mqtt pandas
python tb_feed.py --modus historie       # alle Unfälle 2025/2026, dauert ca. 10–15 Minuten
python tb_feed.py --test                 
```

