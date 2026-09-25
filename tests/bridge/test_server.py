"""Tests der HTTP-Schicht -- ohne echten Port, ohne Zusatzpaket.

aiohttp.test_utils ist in FreeCADs Python vorhanden; pytest ist es NICHT.
Deshalb stdlib-unittest plus AioHTTPTestCase.
"""

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from freecad_bridge import auth, server, snapshot
from freecad_bridge import state as bridge_state

TOKEN = "test-token-nur-fuer-diese-suite"


class HealthRouteTest(AioHTTPTestCase):
    async def get_application(self):
        state = bridge_state.get_state()
        state.token = TOKEN
        state.session_id = "test-session"
        state.running = True
        snapshot.refresh()
        return server.create_app()

    def auth_headers(self, **extra):
        headers = {"Authorization": "Bearer " + TOKEN}
        headers.update(extra)
        return headers

    async def test_health_antwortet_mit_token(self):
        resp = await self.client.get("/api/cad/health", headers=self.auth_headers())
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["session_id"], "test-session")
        self.assertTrue(body["contract_version"])
        self.assertIsInstance(body["documents"], list)

    async def test_health_ohne_token_ist_401(self):
        resp = await self.client.get("/api/cad/health")
        self.assertEqual(resp.status, 401)
        body = await resp.json()
        self.assertEqual(body["error"]["code"], "unauthorized")

    async def test_falsches_token_ist_401(self):
        resp = await self.client.get(
            "/api/cad/health", headers={"Authorization": "Bearer daneben"}
        )
        self.assertEqual(resp.status, 401)

    async def test_fremder_origin_ist_403(self):
        resp = await self.client.get(
            "/api/cad/health", headers=self.auth_headers(Origin="http://evil.example")
        )
        self.assertEqual(resp.status, 403)
        body = await resp.json()
        self.assertEqual(body["error"]["code"], "forbidden_origin")

    async def test_erlaubter_origin_geht_durch(self):
        resp = await self.client.get(
            "/api/cad/health", headers=self.auth_headers(Origin="http://127.0.0.1:8000")
        )
        self.assertEqual(resp.status, 200)

    async def test_fehlender_origin_geht_durch(self):
        """curl, Tests und das Backend senden keinen Origin."""
        resp = await self.client.get("/api/cad/health", headers=self.auth_headers())
        self.assertEqual(resp.status, 200)

    async def test_fremder_host_ist_403(self):
        resp = await self.client.get(
            "/api/cad/health", headers=self.auth_headers(Host="angreifer.example")
        )
        self.assertEqual(resp.status, 403)
        body = await resp.json()
        self.assertEqual(body["error"]["code"], "forbidden_host")

    async def test_websocket_braucht_token(self):
        resp = await self.client.get("/ws")
        self.assertEqual(resp.status, 401)


class AuthHelperTest(unittest.TestCase):
    def test_bearer_parsing(self):
        self.assertEqual(auth.bearer_from_header("Bearer abc"), "abc")
        self.assertEqual(auth.bearer_from_header("bearer abc"), "abc")
        self.assertIsNone(auth.bearer_from_header("Basic abc"))
        self.assertIsNone(auth.bearer_from_header(""))
        self.assertIsNone(auth.bearer_from_header(None))

    def test_token_vergleich(self):
        self.assertTrue(auth.token_matches("abc", "abc"))
        self.assertFalse(auth.token_matches("abc", "abd"))
        self.assertFalse(auth.token_matches("", ""))
        self.assertFalse(auth.token_matches(None, "abc"))

    def test_origin_allowlist(self):
        self.assertTrue(auth.origin_allowed(None))
        self.assertTrue(auth.origin_allowed("http://127.0.0.1:8000"))
        self.assertTrue(auth.origin_allowed("http://localhost:5173"))
        self.assertFalse(auth.origin_allowed("http://evil.example"))
        self.assertFalse(auth.origin_allowed("https://127.0.0.1:8000"))

    def test_host_allowlist(self):
        self.assertTrue(auth.host_allowed(None))
        self.assertTrue(auth.host_allowed("127.0.0.1:8765"))
        self.assertTrue(auth.host_allowed("localhost:8765"))
        self.assertFalse(auth.host_allowed("angreifer.example"))
        self.assertFalse(auth.host_allowed("angreifer.example:8765"))

    def test_neue_token_sind_verschieden_und_lang(self):
        a, b = auth.new_token(), auth.new_token()
        self.assertNotEqual(a, b)
        self.assertGreater(len(a), 30)


if __name__ == "__main__":
    unittest.main()
