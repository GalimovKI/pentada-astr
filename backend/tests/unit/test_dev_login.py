from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mail_search.api.dev_login import COOKIE, ORIGIN, LIFETIME, session_routes


class TestDevLogin(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        with TemporaryDirectory() as temp:
            verifier = Path(temp) / "hash"
            verifier.write_bytes(bcrypt.hashpw(b"example", bcrypt.gensalt(rounds=4)))
            app.include_router(session_routes(verifier))
        self.client = TestClient(app, base_url=ORIGIN, follow_redirects=False)

    def login(self, password="example", origin=ORIGIN):
        return self.client.post("/internal/dev/login", headers={"Origin": origin},
                                json={"username": "ruslan2005", "password": password})

    def check(self, token="", uri="/dev/api/v1/mailboxes"):
        return self.client.get("/internal/dev/check", headers={"Cookie": f"{COOKIE}={token}",
                               "X-Forwarded-Uri": uri, "X-Forwarded-Method": "GET"})

    def test_form_and_revocation(self):
        self.assertEqual(self.check(uri="/dev/").headers["location"], "/dev/login/")
        self.assertEqual(self.check().status_code, 401)
        self.assertEqual(self.login("incorrect").status_code, 401)
        self.assertEqual(self.login(origin="https://example.org").status_code, 403)
        login = self.login()
        self.assertEqual(login.status_code, 204)
        for attribute in ("Secure", "HttpOnly", "SameSite=strict", "Path=/dev/"):
            self.assertIn(attribute, login.headers["set-cookie"])
        token = login.cookies[COOKIE]
        self.assertEqual(self.check(token).status_code, 204)
        result = self.client.post("/internal/dev/logout", headers={"Origin": ORIGIN, "Cookie": f"{COOKIE}={token}"})
        self.assertEqual(result.status_code, 303)
        self.assertEqual(self.check(token).status_code, 401)

    def test_expiry(self):
        with patch("mail_search.api.dev_login.monotonic", return_value=100):
            token = self.login().cookies[COOKIE]
        with patch("mail_search.api.dev_login.monotonic", return_value=100 + LIFETIME):
            self.assertEqual(self.check(token).status_code, 401)
