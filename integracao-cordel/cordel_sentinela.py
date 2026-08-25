# -*- coding: utf-8 -*-
"""
cordel_sentinela.py — Sentinela Eleitoral (monitoramento de ameaças ao pleito)
==============================================================================
Capacidade do Portal de Inteligência (doc 13). Registra postagens com ameaça ao
processo eleitoral — cidade, identificador do autor, região de localização,
difusão aos órgãos e o resultado — com os prints que comprovam cada uma.

Vizinho do card "Padrões & Modus Operandi" do roadmap, que classifica O ACERVO
de extrações; aqui o objeto é a postagem pública captada em monitoramento.

Segue o padrão do doc 12 ("Padrão pra adicionar uma tela"):
  1. HTML em static/sentinela.html
  2. Rota de página gated (aqui)
  3. Endpoints de dados gated por _exige_intel (aqui)
  4. Controle no BACKEND — o front esconder botão não é controle de acesso

Armazenamento (sidecars, no padrão do _cross_tel.db / _vulgos.db):
  casos/_sentinela.db          registros + metadados dos prints
  casos/_sentinela_prints/     os arquivos, gravados como vieram

Auditoria: toda consulta e toda gravação entram em consulta_intel, como o
Dossiê e o Mapa de Vulgos.

INTEGRAÇÃO no api.py — três pontos, todos descritos em INSTRUCOES.md:
    import cordel_sentinela
    cordel_sentinela.montar(app, STATIC=STATIC, CASOS=CASOS,
                            exige_intel=_exige_intel, sql_wal=_sql_wal,
                            usuario_atual=_usuario_atual, ve_tudo=_ve_tudo)
"""
import os
import re
import json
import time
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone

from fastapi import HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

# ── Limites ──────────────────────────────────────────────────────────────────
LIMITE_REGISTROS = 50000
LIMITE_PRINTS = 12                      # por registro
TAMANHO_MAX_PRINT = 12 * 1024 * 1024    # 12 MB
TIPOS_PRINT = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
    "image/gif": "gif", "application/pdf": "pdf",
}
# Assinatura real do arquivo. O Content-Type do navegador é palpite; num sistema
# que guarda prova, o que vale é o conteúdo.
_MAGICOS = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)

CAMPOS_TEXTO = {
    "data": 10, "teor": 2000, "plataforma": 60, "url": 600, "cidade": 120,
    "regiao": 120, "identificador": 200, "tipo_ident": 60, "tipo": 120,
    "nivel": 20, "situacao": 60, "resultado": 80, "procedimento": 80, "obs": 2000,
}

_con = None
_lock = threading.Lock()        # serializa a conexão única (padrão do _cross_lock)
_ctx = {}


# ══════════════ Banco ══════════════
def _db():
    global _con
    if _con is None:
        caminho = os.path.join(_ctx["CASOS"], "_sentinela.db")
        os.makedirs(_ctx["CASOS"], exist_ok=True)
        con = sqlite3.connect(caminho, check_same_thread=False)
        sql_wal = _ctx.get("sql_wal")
        _con = sql_wal(con) if sql_wal else con
        _con.execute("""CREATE TABLE IF NOT EXISTS registro(
            id             TEXT PRIMARY KEY,
            data           TEXT,
            teor           TEXT,
            plataforma     TEXT,
            url            TEXT,
            cidade         TEXT,
            regiao         TEXT,
            identificador  TEXT,
            tipo_ident     TEXT,
            tipo           TEXT,
            nivel          TEXT,
            alcance        INTEGER DEFAULT 0,
            destinos       TEXT,
            situacao       TEXT,
            resultado      TEXT,
            procedimento   TEXT,
            obs            TEXT,
            criado_por     TEXT,
            criado_em      TEXT,
            atualizado_por TEXT,
            atualizado_em  TEXT
        )""")
        _con.execute("CREATE INDEX IF NOT EXISTS ix_reg_data   ON registro(data)")
        _con.execute("CREATE INDEX IF NOT EXISTS ix_reg_cidade ON registro(cidade)")
        _con.execute("""CREATE TABLE IF NOT EXISTS print(
            id          TEXT PRIMARY KEY,
            registro_id TEXT,
            nome        TEXT,
            tipo        TEXT,
            ext         TEXT,
            tamanho     INTEGER,
            sha256      TEXT,
            criado_por  TEXT,
            criado_em   TEXT
        )""")
        _con.execute("CREATE INDEX IF NOT EXISTS ix_print_reg ON print(registro_id)")
        # Contador que só avança. Número de registro é citado em ofício e em
        # procedimento: não pode ser reaproveitado depois de um expurgo.
        _con.execute("CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT)")
        _con.commit()
    return _con


def _dir_prints():
    d = os.path.join(_ctx["CASOS"], "_sentinela_prints")
    os.makedirs(d, exist_ok=True)
    return d


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _auditar(login, acao, alvo=""):
    """Trilha das consultas de INTEL, no mesmo formato do Dossiê e do Vulgos."""
    try:
        with _lock:
            _db().execute("CREATE TABLE IF NOT EXISTS consulta_intel(login TEXT, alvo TEXT, ts REAL)")
            _db().execute("INSERT INTO consulta_intel(login,alvo,ts) VALUES(?,?,?)",
                          (login, f"sentinela:{acao}" + (f":{alvo}" if alvo else ""), time.time()))
            _db().commit()
    except Exception:
        pass    # auditoria nunca derruba a operação


# ══════════════ Saneamento ══════════════
def _txt(v, maximo):
    return str("" if v is None else v).strip()[:maximo]


def _saneia(bruto, ident, anterior, login):
    agora = _agora()
    dados = {campo: _txt(bruto.get(campo), tam) for campo, tam in CAMPOS_TEXTO.items()}
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dados["data"] or ""):
        dados["data"] = agora[:10]
    destinos = bruto.get("destinos") or []
    if not isinstance(destinos, list):
        destinos = []
    dados["destinos"] = json.dumps([_txt(d, 80) for d in destinos[:24] if _txt(d, 80)],
                                   ensure_ascii=False)
    try:
        dados["alcance"] = max(0, min(int(bruto.get("alcance") or 0), 10 ** 12))
    except (TypeError, ValueError):
        dados["alcance"] = 0
    dados["id"] = ident
    dados["criado_por"] = (anterior or {}).get("criado_por") or login
    dados["criado_em"] = (anterior or {}).get("criado_em") or agora
    dados["atualizado_por"] = login
    dados["atualizado_em"] = agora
    return dados


def _proximo_id():
    """Numeração monotônica: nunca reaproveita um número já emitido, mesmo que o
    registro tenha sido excluído. Chamar sempre com _lock tomado."""
    con = _db()
    linha = con.execute("SELECT valor FROM meta WHERE chave='seq'").fetchone()
    seq = int(linha[0]) if linha and str(linha[0]).isdigit() else 0
    if not seq:    # base já existente antes desta versão: parte do maior id gravado
        antigo = con.execute(
            "SELECT id FROM registro WHERE id LIKE 'REG-%' ORDER BY id DESC LIMIT 1").fetchone()
        if antigo:
            m = re.fullmatch(r"REG-(\d+)", antigo[0] or "")
            if m:
                seq = int(m.group(1))
    seq += 1
    con.execute("INSERT OR REPLACE INTO meta(chave,valor) VALUES('seq',?)", (str(seq),))
    con.commit()
    return "REG-%04d" % seq


_COLUNAS = ["id", "data", "teor", "plataforma", "url", "cidade", "regiao", "identificador",
            "tipo_ident", "tipo", "nivel", "alcance", "destinos", "situacao", "resultado",
            "procedimento", "obs", "criado_por", "criado_em", "atualizado_por", "atualizado_em"]


def _linha_para_dict(linha, prints_por_registro):
    reg = dict(zip(_COLUNAS, linha))
    try:
        reg["destinos"] = json.loads(reg.get("destinos") or "[]")
    except Exception:
        reg["destinos"] = []
    reg["prints"] = prints_por_registro.get(reg["id"], [])
    return reg


def _todos():
    with _lock:
        linhas = _db().execute(
            "SELECT %s FROM registro ORDER BY data DESC, id DESC" % ",".join(_COLUNAS)).fetchall()
        prints = _db().execute(
            "SELECT registro_id,id,nome,tipo,tamanho,sha256,criado_em FROM print "
            "ORDER BY criado_em").fetchall()
    por_registro = {}
    for reg_id, pid, nome, tipo, tamanho, sha, criado in prints:
        por_registro.setdefault(reg_id, []).append(
            {"id": pid, "nome": nome, "tipo": tipo, "tamanho": tamanho,
             "sha256": sha, "em": criado})
    return [_linha_para_dict(l, por_registro) for l in linhas]


def _gravar(dados):
    with _lock:
        _db().execute(
            "INSERT OR REPLACE INTO registro(%s) VALUES(%s)"
            % (",".join(_COLUNAS), ",".join("?" * len(_COLUNAS))),
            [dados[c] for c in _COLUNAS])
        _db().commit()


def _vincular_prints(registro_id, prints):
    """Amarra ao registro os prints que subiram soltos e solta os que saíram dele.
    O arquivo em disco NÃO é apagado aqui — some só no DELETE explícito, para que
    um desvínculo por engano seja reversível.

    Só chame quando o cliente tiver enviado a lista: uma alteração parcial, sem o
    campo 'prints', não pode desamarrar a prova do registro."""
    ids = [_txt(p.get("id"), 80) for p in (prints or []) if isinstance(p, dict) and p.get("id")]
    ids = ids[:LIMITE_PRINTS]
    with _lock:
        _db().execute("UPDATE print SET registro_id='' WHERE registro_id=?", (registro_id,))
        for pid in ids:
            _db().execute("UPDATE print SET registro_id=? WHERE id=?", (registro_id, pid))
        _db().commit()


def _resposta(login, extra=None):
    corpo = {"ok": True, "usuario": login, "registros": _todos(),
             "atualizadoEm": _agora()}
    if extra:
        corpo.update(extra)
    return JSONResponse(corpo)


# ══════════════ Rotas ══════════════
def montar(app, *, STATIC, CASOS, exige_intel, sql_wal=None,
           usuario_atual=None, ve_tudo=None):
    """Registra as rotas do Sentinela no app do CORDEL.

    exige_intel   — o gate do portal INTEL (_exige_intel do api.py): devolve o
                    login ou levanta 403. É ele que garante DIP/COIN.
    sql_wal       — o _sql_wal do api.py (WAL + pragmas), para o sidecar seguir
                    o mesmo regime das outras conexões.
    """
    _ctx.update(STATIC=STATIC, CASOS=CASOS, sql_wal=sql_wal)

    # ── Página ───────────────────────────────────────────────────────────────
    @app.get("/intel/sentinela")
    def sentinela_page(request: Request):
        login = usuario_atual(request) if usuario_atual else None
        if not login:
            return RedirectResponse("/login")
        if ve_tudo and not ve_tudo(login):
            return RedirectResponse("/app")
        return FileResponse(os.path.join(STATIC, "sentinela.html"),
                            headers={"Cache-Control": "no-store"})

    # ── Registros ────────────────────────────────────────────────────────────
    @app.get("/intel/sentinela/registros")
    def sentinela_listar(request: Request):
        login = exige_intel(request)
        _auditar(login, "listar")
        return _resposta(login)

    @app.post("/intel/sentinela/registros")
    async def sentinela_incluir(request: Request):
        login = exige_intel(request)
        bruto = await request.json()
        with _lock:
            total = _db().execute("SELECT COUNT(*) FROM registro").fetchone()[0]
            if total >= LIMITE_REGISTROS:
                raise HTTPException(413, "limite de registros da base atingido")
            ident = _proximo_id()
        dados = _saneia(bruto or {}, ident, None, login)
        if not (dados["teor"] and dados["cidade"] and dados["identificador"]):
            raise HTTPException(400, "teor, cidade e identificador são obrigatórios")
        _gravar(dados)
        _vincular_prints(ident, (bruto or {}).get("prints"))
        _auditar(login, "incluir", ident)
        return _resposta(login, {"registro": ident})

    @app.put("/intel/sentinela/registros/{ident}")
    async def sentinela_alterar(ident: str, request: Request):
        login = exige_intel(request)
        bruto = await request.json()
        with _lock:
            atual = _db().execute(
                "SELECT criado_por, criado_em FROM registro WHERE id=?", (ident,)).fetchone()
        if not atual:
            raise HTTPException(404, "registro não encontrado")
        dados = _saneia(bruto or {}, ident,
                        {"criado_por": atual[0], "criado_em": atual[1]}, login)
        if not (dados["teor"] and dados["cidade"] and dados["identificador"]):
            raise HTTPException(400, "teor, cidade e identificador são obrigatórios")
        _gravar(dados)
        if isinstance(bruto, dict) and "prints" in bruto:
            _vincular_prints(ident, bruto.get("prints"))
        _auditar(login, "alterar", ident)
        return _resposta(login, {"registro": ident})

    @app.delete("/intel/sentinela/registros/{ident}")
    def sentinela_excluir(ident: str, request: Request):
        login = exige_intel(request)
        with _lock:
            achou = _db().execute("SELECT 1 FROM registro WHERE id=?", (ident,)).fetchone()
            if not achou:
                raise HTTPException(404, "registro não encontrado")
            _db().execute("DELETE FROM registro WHERE id=?", (ident,))
            _db().execute("UPDATE print SET registro_id='' WHERE registro_id=?", (ident,))
            _db().commit()
        _auditar(login, "excluir", ident)
        return _resposta(login)

    @app.post("/intel/sentinela/lote")
    async def sentinela_lote(request: Request):
        """Carga em lote (importação de planilha). Acrescenta ou substitui a base."""
        login = exige_intel(request)
        corpo = await request.json()
        entrada = (corpo or {}).get("registros")
        if not isinstance(entrada, list):
            raise HTTPException(400, "envie { registros: [...] }")
        substituir = bool((corpo or {}).get("substituir"))
        if len(entrada) > LIMITE_REGISTROS:
            raise HTTPException(413, "lote acima do limite da base")
        with _lock:
            if substituir:
                _db().execute("DELETE FROM registro")
                _db().execute("UPDATE print SET registro_id=''")
                _db().commit()
        gravados = 0
        for bruto in entrada:
            if not isinstance(bruto, dict):
                continue
            with _lock:
                ident = _proximo_id()
            dados = _saneia(bruto, ident, None, login)
            if not (dados["teor"] or dados["identificador"] or dados["cidade"]):
                continue
            _gravar(dados)
            _vincular_prints(ident, bruto.get("prints"))
            gravados += 1
        _auditar(login, "lote", str(gravados))
        return _resposta(login, {"importados": gravados})

    # ── Prints ───────────────────────────────────────────────────────────────
    @app.post("/intel/sentinela/prints")
    async def sentinela_subir_print(request: Request, arquivo: UploadFile = File(...)):
        """Recebe o print e o grava COMO VEIO — sem recompressão, sem redimensionar.
        O tipo é conferido pela assinatura do arquivo, não pelo que o navegador diz."""
        login = exige_intel(request)
        bytes_ = await arquivo.read(TAMANHO_MAX_PRINT + 1)
        if not bytes_:
            raise HTTPException(400, "arquivo vazio")
        if len(bytes_) > TAMANHO_MAX_PRINT:
            raise HTTPException(413, "print acima de 12 MB")

        tipo = next((t for assinatura, t in _MAGICOS if bytes_.startswith(assinatura)), None)
        if tipo is None and bytes_[:4] == b"RIFF" and bytes_[8:12] == b"WEBP":
            tipo = "image/webp"
        if tipo is None:
            raise HTTPException(415, "formato não aceito — use PNG, JPEG, WebP, GIF ou PDF")

        ext = TIPOS_PRINT[tipo]
        sha = hashlib.sha256(bytes_).hexdigest()
        pid = hashlib.sha256((sha + str(time.time())).encode()).hexdigest()[:24]
        destino = os.path.join(_dir_prints(), pid + "." + ext)
        # Escrita fora do loop de eventos: o cordel-web roda com UM worker, e uma
        # gravação síncrona de 12 MB seguraria todos os analistas.
        await run_in_threadpool(_escrever, destino, bytes_)
        nome = _txt(getattr(arquivo, "filename", ""), 200) or ("print." + ext)
        with _lock:
            _db().execute(
                "INSERT INTO print(id,registro_id,nome,tipo,ext,tamanho,sha256,criado_por,criado_em)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, "", nome, tipo, ext, len(bytes_), sha, login, _agora()))
            _db().commit()
        _auditar(login, "print", pid)
        return JSONResponse({"ok": True, "print": {
            "id": pid, "nome": nome, "tipo": tipo, "tamanho": len(bytes_),
            "sha256": sha, "em": _agora()}})

    @app.get("/intel/sentinela/prints/{pid}")
    def sentinela_ver_print(pid: str, request: Request):
        exige_intel(request)
        if not re.fullmatch(r"[0-9a-f]{24}", pid or ""):
            raise HTTPException(404, "print não encontrado")
        with _lock:
            linha = _db().execute("SELECT tipo, ext, nome FROM print WHERE id=?", (pid,)).fetchone()
        if not linha:
            raise HTTPException(404, "print não encontrado")
        caminho = os.path.join(_dir_prints(), pid + "." + linha[1])
        if not os.path.exists(caminho):
            raise HTTPException(404, "arquivo do print não está mais no disco")
        return FileResponse(caminho, media_type=linha[0], headers={
            "Cache-Control": "private, max-age=86400",
            "X-Robots-Tag": "noindex, nofollow",
        })

    @app.delete("/intel/sentinela/prints/{pid}")
    def sentinela_apagar_print(pid: str, request: Request):
        login = exige_intel(request)
        if not re.fullmatch(r"[0-9a-f]{24}", pid or ""):
            raise HTTPException(404, "print não encontrado")
        with _lock:
            linha = _db().execute("SELECT ext FROM print WHERE id=?", (pid,)).fetchone()
            if linha:
                _db().execute("DELETE FROM print WHERE id=?", (pid,))
                _db().commit()
        if linha:
            caminho = os.path.join(_dir_prints(), pid + "." + linha[0])
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except OSError:
                    pass
        _auditar(login, "print-excluir", pid)
        return JSONResponse({"ok": True})

    return app


def _escrever(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "wb") as f:
        f.write(dados)
    os.replace(tmp, caminho)
