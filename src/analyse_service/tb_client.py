"""ThingsBoard-REST-Client: Login, Geräte anlegen/finden, Telemetrie und Attribute schreiben."""
import os
import time
import requests


class ThingsBoard:
    def __init__(self):
        self.url = os.getenv("TB_URL", "").rstrip("/")
        self.user = os.getenv("TB_USER", "tenant@thingsboard.org")
        self.passwort = os.getenv("TB_PASS", "tenant")
        self.s = requests.Session()
        self.token_cache = {}                                    # Gerätename → Access Token
        self.jwt_zeit = 0

    @property
    def aktiv(self):
        return bool(self.url)

    def _login(self):
        r = self.s.post(f"{self.url}/api/auth/login", json={"username": self.user, "password": self.passwort}, timeout=10)
        r.raise_for_status()
        self.s.headers["X-Authorization"] = f"Bearer {r.json()['token']}"
        self.jwt_zeit = time.time()

    def _api(self, methode, pfad, **kw):
        if time.time() - self.jwt_zeit > 1800:                  # Token rechtzeitig erneuern
            self._login()
        r = self.s.request(methode, f"{self.url}{pfad}", timeout=10, **kw)
        if r.status_code == 401:
            self._login()
            r = self.s.request(methode, f"{self.url}{pfad}", timeout=10, **kw)
        return r

    def geraet_token(self, name, typ="Zelle"):
        """Access Token eines Geräts; legt das Gerät an, falls es noch nicht existiert."""
        if name in self.token_cache:
            return self.token_cache[name]
        r = self._api("GET", "/api/tenant/devices", params={"deviceName": name})
        if r.status_code == 200 and r.text:
            geraet_id = r.json()["id"]["id"]
        else:                                                    # neu anlegen (Profil = typ, wird ggf. erzeugt)
            r = self._api("POST", "/api/device", json={"name": name, "type": typ})
            r.raise_for_status()
            geraet_id = r.json()["id"]["id"]
        r = self._api("GET", f"/api/device/{geraet_id}/credentials")
        r.raise_for_status()
        token = r.json()["credentialsId"]
        self.token_cache[name] = token
        return token

    def telemetrie(self, name, werte, ts=None, typ="Zelle"):
        if not self.aktiv:
            return
        token = self.geraet_token(name, typ)
        payload = {"ts": ts, "values": werte} if ts else werte
        self.s.post(f"{self.url}/api/v1/{token}/telemetry", json=payload, timeout=10)

    def attribute(self, name, werte, typ="Zelle"):
        if not self.aktiv:
            return
        token = self.geraet_token(name, typ)
        self.s.post(f"{self.url}/api/v1/{token}/attributes", json=werte, timeout=10)
