"""Lebenszyklus der Bruecke: Start, Handshake, Absicherung, sauberer Abbau.

Diese Tests starten einen echten Server auf 127.0.0.1:8765. Sie laufen deshalb
seriell und raeumen in tearDown auf -- eine haengende Bruecke wuerde jeden
weiteren Lauf mit "Port belegt" scheitern lassen, was genau das gewuenschte
Verhalten ist, aber als Testartefakt nichts taugt.
"""

import os
import socket
import unittest

import requests

from freecad_bridge import auth, runner
from freecad_bridge import state as bridge_state

BASE = "http://127.0.0.1:8765"


def port_is_taken():
    """Haelt ein FREMDER Prozess den Port?

    Der haeufigste Fall im Alltag: FreeCAD laeuft mit gestarteter Bruecke,
    waehrend jemand die Tests anstoesst. Das ist kein Testfehler, sondern genau
    das beabsichtigte Verhalten des festen Ports -- also ueberspringen statt
    zwoelf rote Meldungen zu erzeugen.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", runner.PORT))
            return False
        except OSError:
            return True


class BridgeLifecycleTest(unittest.TestCase):
    def setUp(self):
        runner.stop_bridge(quiet=True)
        if port_is_taken():
            self.skipTest(
                "Port %d ist von einem anderen Prozess belegt (meist FreeCAD mit "
                "gestarteter Bruecke). Im Dock-Panel stoppen und erneut laufen lassen."
                % runner.PORT
            )
        runner.start_bridge()
        self.state = bridge_state.get_state()
        self.headers = {"Authorization": "Bearer " + self.state.token}

    def tearDown(self):
        runner.stop_bridge(quiet=True)

    # -- Start ----------------------------------------------------------

    def test_laeuft_nach_start(self):
        self.assertTrue(self.state.running)
        self.assertTrue(self.state.session_id)
        self.assertGreater(len(self.state.token), 30)

    def test_start_ist_idempotent(self):
        session_before = self.state.session_id
        runner.start_bridge()
        self.assertEqual(bridge_state.get_state().session_id, session_before)

    # -- Handshake ------------------------------------------------------

    def test_handshake_datei_beschreibt_die_sitzung(self):
        data = auth.read_handshake()
        self.assertIsNotNone(data)
        self.assertEqual(data["magic"], auth.MAGIC)
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["port"], runner.PORT)
        self.assertEqual(data["token"], self.state.token)
        self.assertEqual(data["session_id"], self.state.session_id)
        self.assertTrue(data["contract_version"])

    def test_stop_entfernt_nur_die_eigene_handshake_datei(self):
        """Sonst raeumt eine zweite Instanz der laufenden ersten die Datei weg."""
        self.assertFalse(auth.remove_handshake("fremde-sitzung"))
        self.assertIsNotNone(auth.read_handshake())
        self.assertTrue(auth.remove_handshake(self.state.session_id))
        self.assertIsNone(auth.read_handshake())

    # -- Health ---------------------------------------------------------

    def test_health_antwortet(self):
        resp = requests.get(BASE + "/api/cad/health", headers=self.headers, timeout=5)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["running"])
        self.assertEqual(body["session_id"], self.state.session_id)
        self.assertEqual(body["pid"], os.getpid())

    def test_health_kennt_offene_dokumente(self):
        import FreeCAD

        from freecad_bridge import snapshot

        doc = FreeCAD.newDocument("LifecycleTestDoc")
        try:
            snapshot.refresh()
            resp = requests.get(BASE + "/api/cad/health", headers=self.headers, timeout=5)
            self.assertIn("LifecycleTestDoc", resp.json()["documents"])
        finally:
            FreeCAD.closeDocument(doc.Name)

    # -- Absicherung ----------------------------------------------------

    def test_ohne_token_401(self):
        resp = requests.get(BASE + "/api/cad/health", timeout=5)
        self.assertEqual(resp.status_code, 401)

    def test_fremder_origin_403(self):
        headers = dict(self.headers)
        headers["Origin"] = "http://evil.example"
        resp = requests.get(BASE + "/api/cad/health", headers=headers, timeout=5)
        self.assertEqual(resp.status_code, 403)

    # -- Abbau ----------------------------------------------------------

    def test_stop_raeumt_vollstaendig_ab(self):
        runner.stop_bridge()
        state = bridge_state.get_state()

        self.assertFalse(state.running)
        self.assertIsNone(state.thread)
        self.assertIsNone(state.loop)
        self.assertIsNone(state.runner)
        self.assertIsNone(auth.read_handshake())

        with self.assertRaises(requests.RequestException):
            requests.get(BASE + "/api/cad/health", timeout=2)

    def test_stop_ist_idempotent(self):
        runner.stop_bridge()
        runner.stop_bridge()  # darf nicht werfen
        self.assertFalse(bridge_state.get_state().running)

    def test_neustart_rotiert_das_token(self):
        """Deshalb muss das Backend die Handshake-Datei bei JEDEM Versuch neu lesen."""
        first_token = self.state.token
        first_session = self.state.session_id

        runner.stop_bridge()
        runner.start_bridge()
        state = bridge_state.get_state()

        self.assertNotEqual(state.token, first_token)
        self.assertNotEqual(state.session_id, first_session)
        self.assertEqual(auth.read_handshake()["token"], state.token)

    def test_generation_steigt_bei_jedem_start(self):
        generation_before = self.state.generation
        runner.stop_bridge()
        runner.start_bridge()
        self.assertGreater(bridge_state.get_state().generation, generation_before)


if __name__ == "__main__":
    unittest.main()
