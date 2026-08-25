# -*- coding: utf-8 -*-
"""CORDEL simulado — só o bastante para exercitar cordel_sentinela de verdade:
cookie de sessão, gate _ve_tudo/_exige_intel, STATIC e CASOS."""
import os, sys, shutil, sqlite3
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

RAIZ = "/home/user/vida-apertada-server/integracao-cordel"
sys.path.insert(0, RAIZ)
import cordel_sentinela

BASE = "/tmp/claude-0/-home-user-vida-apertada-server/38ed6624-e71d-5df3-969d-2f88876be348/scratchpad/cordel_teste"
STATIC = os.path.join(BASE, "static")
CASOS = os.path.join(BASE, "casos")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(STATIC, exist_ok=True)
os.makedirs(CASOS, exist_ok=True)
shutil.copy(os.path.join(RAIZ, "sentinela.html"), os.path.join(STATIC, "sentinela.html"))

app = FastAPI()

# Espelha o host real: quem é DIP/COIN vê tudo; o resto, não.
UNIDADE = {"delegado": "DIP", "escrivao": "1ª DHPP"}


def _sql_wal(con):
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _usuario_atual(request):
    return request.cookies.get("cordel_sess") or None


def _ve_tudo(login):
    return UNIDADE.get(login) in ("DIP", "COIN")


def _exige_intel(request: Request):
    u = _usuario_atual(request)
    if not u or not _ve_tudo(u):
        raise HTTPException(403, "acesso restrito à Inteligência (DIP/COIN)")
    return u


@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    # A regra de Host do sentinela., como vai para o api.py
    host = request.headers.get("host", "").lower()
    if host.startswith("sentinela."):
        p = request.url.path
        ok = ("/intel/sentinela", "/login", "/logout", "/static/", "/assets/", "/favicon", "/auth", "/eu")
        if request.method == "GET" and not any(p == a or p.startswith(a) for a in ok):
            return RedirectResponse("/intel/sentinela")
    if request.url.path in ("/login", "/entrar"):
        return await call_next(request)
    if not _usuario_atual(request):
        if request.method != "GET":
            return JSONResponse({"detail": "sessão expirada — faça login de novo"}, status_code=401)
        return RedirectResponse("/login")
    return await call_next(request)


@app.get("/login")
def login():
    return JSONResponse({"pagina": "login"})


@app.get("/entrar")
def entrar(quem: str = "delegado"):
    r = JSONResponse({"ok": True, "login": quem})
    r.set_cookie("cordel_sess", quem, httponly=True, samesite="lax")
    return r


@app.get("/inteligencia")
def portal():
    return JSONResponse({"pagina": "portal INTEL"})


@app.get("/app")
def appcasos():
    return JSONResponse({"pagina": "app de casos"})


cordel_sentinela.montar(app, STATIC=STATIC, CASOS=CASOS,
                        exige_intel=_exige_intel, sql_wal=_sql_wal,
                        usuario_atual=_usuario_atual, ve_tudo=_ve_tudo)
