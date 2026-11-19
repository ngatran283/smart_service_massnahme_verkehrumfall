"""
Datenquelle des Prototyps: simuliert die Polizei, die Unfallmeldungen per MQTT an ThingsBoard sendet.
  python tb_feed.py --modus historie --bis 2026-09-01       # Vorlauf: Unfaelle bis 31.08.2026 mit Original-Zeitstempel
  python tb_feed.py --modus live --von 2026-09-01 --pause 1 # Demo: aktuelle Uhrzeit, eine Meldung pro Sekunde
"""
import argparse
import json
import time

import pandas as pd

TB_HOST = "localhost"
TB_PORT = 1883
TOKEN = "kkG6KYYjIlmPBxrh1WXX"     # Access Token des Geräts „Polizei-Feed" eintragen
TOPIC = "v1/devices/me/telemetry"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modus", choices=["historie", "live"], default="historie")
    ap.add_argument("--von", default="2026-09-01")
    ap.add_argument("--bis", default=None, help="historie: nur Unfaelle vor diesem Datum senden (z. B. 2026-09-01)")
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    feed = pd.read_csv("daten/thingsboard_datenfeed.csv", parse_dates=["Zeitpunkt"]).sort_values("Zeitpunkt")
    if a.modus == "live":
        feed = feed[feed["Zeitpunkt"] >= a.von]
    elif a.bis:
        feed = feed[feed["Zeitpunkt"] < a.bis]
    if a.test:
        feed = feed.head(5)

    client = None
    if not a.test:
        import paho.mqtt.client as mqtt
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            client = mqtt.Client()
        client.username_pw_set(TOKEN)
        client.connect(TB_HOST, TB_PORT, 60)
        client.loop_start()

    for i, r in enumerate(feed.itertuples(index=False), 1):
        ts = int(time.time() * 1000) if a.modus == "live" else int(r.Zeitpunkt_ms)
        werte = {
            "ts_ms": ts, "Unfall_ID": int(r.Unfall_ID), "Zelle": r.Zelle,
            "latitude": round(r.Lat, 5), "longitude": round(r.Lon, 5),
            "schwer": int(r.schwer), "Schwere": r.Accident_severity,
            "Knoten": r.Types_of_Junction, "Area": r.Area_accident_occured,
            "Licht": r.Light_conditions, "Kollision": r.Type_of_collision,
            "Ursache": r.Cause_of_accident, "Alter": r.Age_band_of_driver,
        }
        nachricht = {"ts": ts, "values": werte}
        if a.test:
            print(json.dumps(nachricht, ensure_ascii=False))
        else:
            client.publish(TOPIC, json.dumps(nachricht), qos=1)

        if a.modus == "live":
            print(f"{i:4d}  {r.Zelle:10s}  {'SCHWER' if r.schwer else 'leicht'}")
            time.sleep(a.pause)
        elif i % 100 == 0:
            print(f"{i} Meldungen gesendet")
            time.sleep(1.0)        # Rule Engine und Analyse-Service hinterherkommen lassen

    if client:
        time.sleep(2)
        client.loop_stop()
        client.disconnect()
    print("Fertig.")


if __name__ == "__main__":
    main()
