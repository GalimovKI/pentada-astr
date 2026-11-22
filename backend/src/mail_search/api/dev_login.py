"""Dev-only cookie sessions. Uvicorn runs one worker per environment."""
import asyncio
from collections import OrderedDict
import hmac
from pathlib import Path
import secrets
from time import monotonic

import bcrypt
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, SecretStr
from starlette.responses import RedirectResponse, Response

COOKIE = "__Secure-smartmail_dev"
ORIGIN = "https://smartmail-hackaton.ru"
LIFETIME = 8 * 60 * 60
NO_STORE = {"Cache-Control": "no-store"}


class Login(BaseModel):
    username: str = Field(max_length=128)
    password: SecretStr = Field(max_length=72)


def session_routes(verifier_file: Path) -> APIRouter:
    verifier = verifier_file.read_bytes().strip()
    router = APIRouter(prefix="/internal/dev", include_in_schema=False)
    sessions: OrderedDict[str, float] = OrderedDict()
    verifying = asyncio.Lock()

    @router.post("/login")
    async def login(request: Request, form: Login):
        if request.headers.get("origin") != ORIGIN:
            return Response(status_code=403, headers=NO_STORE)
        password = form.password.get_secret_value().encode()
        if len(password) > 72:
            return Response(status_code=401, headers=NO_STORE)
        if verifying.locked():
            return Response(status_code=429, headers=NO_STORE)
        async with verifying:
            valid = await asyncio.to_thread(bcrypt.checkpw, password, verifier)
        if not valid or not hmac.compare_digest(form.username.encode(), b"ruslan2005"):
            return Response(status_code=401, headers=NO_STORE)
        token = secrets.token_urlsafe(32)
        now = monotonic()
        while sessions and (len(sessions) >= 1024 or next(iter(sessions.values())) <= now):
            sessions.popitem(last=False)
        sessions.pop(request.cookies.get(COOKIE), None)
        sessions[token] = now + LIFETIME
        response = Response(status_code=204, headers=NO_STORE)
        response.set_cookie(COOKIE, token, max_age=LIFETIME, path="/dev/", secure=True,
                            httponly=True, samesite="strict")
        return response

    @router.post("/logout")
    async def logout(request: Request):
        if request.headers.get("origin") != ORIGIN:
            return Response(status_code=403, headers=NO_STORE)
        sessions.pop(request.cookies.get(COOKIE), None)
        response = RedirectResponse("/dev/login/", status_code=303, headers=NO_STORE)
        response.delete_cookie(COOKIE, path="/dev/", secure=True, httponly=True, samesite="strict")
        return response

    @router.get("/check")
    async def check(request: Request):
        if request.headers.get("x-forwarded-method") not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and origin != ORIGIN:
                return Response(status_code=403, headers=NO_STORE)
        if sessions.get(request.cookies.get(COOKIE), 0) > monotonic():
            return Response(status_code=204, headers=NO_STORE)
        if request.headers.get("x-forwarded-uri", "").partition("?")[0] == "/dev/":
            return RedirectResponse("/dev/login/", status_code=303, headers=NO_STORE)
        return Response(status_code=401, headers=NO_STORE)

    return router
