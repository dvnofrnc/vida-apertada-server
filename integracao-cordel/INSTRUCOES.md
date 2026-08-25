# Sentinela Eleitoral — integração ao CORDEL Web

Pacote pronto para entrar em `dvnofrnc/cordel`, ramo `feat-gdocs-docx`.
Painel de monitoramento de ameaças ao pleito no Ceará: postagem, cidade,
identificador, região de localização, difusão aos órgãos e resultado, com os
prints que comprovam cada ocorrência.

É o **card 9 do roadmap do Portal de Inteligência** (doc 13, "Padrões & Modus
Operandi — classificação temática … ameaça") saindo do papel, e segue o
"Padrão pra adicionar uma tela" do doc 12.

## Arquivos

| Deste pacote | Vai para |
|---|---|
| `cordel_sentinela.py` | `cordel_server/cordel_sentinela.py` |
| `sentinela.html` | `cordel_server/static/sentinela.html` |

Nada mais é copiado. As três alterações no `api.py` estão abaixo, e o card no
portal, no fim.

## As três alterações no `api.py`

### 1. Montar o módulo (perto do bloco de INTELIGÊNCIA, após `_exige_intel`)

`_exige_intel` está definido em `api.py` na altura da linha 20409; monte logo
depois dele, para que a função já exista quando o módulo for montado.

```python
# ══════════════ SENTINELA ELEITORAL (card 9: classificação de AMEAÇA) ══════════════
import cordel_sentinela

cordel_sentinela.montar(
    app,
    STATIC=STATIC,
    CASOS=CASOS,
    exige_intel=_exige_intel,       # o gate DIP/COIN, reaproveitado inteiro
    sql_wal=_sql_wal,               # mesmo regime WAL das outras conexões
    usuario_atual=_usuario_atual,
    ve_tudo=_ve_tudo,
)
```

O módulo não importa `api.py` — recebe tudo por parâmetro. Sem import circular,
e dá para testar isolado (foi assim que ele foi validado).

### 2. Roteamento por Host do novo subdomínio (no `_auth_mw`, ~linha 806)

Hoje o middleware trata `inteligencia.`. Acrescente o `sentinela.` logo depois,
no mesmo espírito: esse subdomínio serve **só** o Sentinela.

```python
    # sentinela.redecordel.com.br → SÓ o Sentinela Eleitoral. Qualquer outra
    # página redireciona para ele (separação real, como o portal INTEL).
    if request.headers.get("host", "").lower().startswith("sentinela."):
        _p = request.url.path
        _sent_ok = ("/intel/sentinela", "/login", "/logout", "/reset-senha",
                    "/static/", "/assets/", "/favicon", "/auth", "/eu")
        if request.method == "GET" and not any(_p == a or _p.startswith(a) for a in _sent_ok):
            return RedirectResponse("/intel/sentinela")
```

### 3. Raiz do subdomínio (na função que hoje decide entre `/inteligencia` e `/app`, ~linha 20390)

```python
    if request.headers.get("host", "").lower().startswith("sentinela."):
        return RedirectResponse("/intel/sentinela")
    if request.headers.get("host", "").lower().startswith("inteligencia."):
        return RedirectResponse("/inteligencia")
    return RedirectResponse("/app")
```

## DNS do subdomínio

Conforme o doc 08 — **rodar como usuário `cordel`**, senão o `cert.pem` de
`/home/cordel/.cloudflared/` não é encontrado:

```bash
cloudflared tunnel route dns 74fc7c04-… sentinela.redecordel.com.br
```

O ingress do túnel já manda tudo para `localhost:8000` (o Caddy); como o
roteamento é por Host, **não é preciso mexer no `config.yml` nem no Caddyfile**.

> **Aviso ao gestor, registrado no doc 12:** o cookie `cordel_sess` é host-only.
> Um subdomínio novo significa que cada agente loga **mais uma vez** —
> credenciais iguais, sessão separada de `cordel.` e de `inteligencia.`. Se isso
> incomodar no uso, a página continua acessível por
> `inteligencia.redecordel.com.br/intel/sentinela`, sem login adicional; basta
> não divulgar o subdomínio.

## Card no portal (`static/inteligencia.html`)

No grid dos 9 cards, o card 9 deixa de ser "planejado":

```html
<a class="card" href="/intel/sentinela">
  <h3>Sentinela Eleitoral</h3>
  <p>Ameaças ao pleito: postagem, município, identificador, região, difusão
     aos órgãos e resultado — com os prints.</p>
  <span class="tag ok">disponível</span>
</a>
```

Ajuste as classes ao que o `inteligencia.html` já usa nos outros cards.

## Deploy

Nada aqui exige janela especial **além da regra que já vale**: subir o módulo
novo pede `systemctl restart cordel-web`, e o doc 09 diz que reiniciar derruba
todos os analistas (worker único). Suba junto do próximo deploy planejado.

O `sentinela.html` é estático servido pelo Caddy — entra sem restart, e o
`Cache-Control: no-cache` do Caddy faz o navegador revalidar sozinho.

## Onde os dados ficam

```
casos/_sentinela.db          registros, metadados dos prints, contador e trilha
casos/_sentinela_prints/     os arquivos, gravados como vieram
```

Sidecars, no padrão do `_cross_tel.db` e do `_vulgos.db`. Entram na mesma rotina
de backup — e, diferente dos índices, **não são reconstrutíveis**: são dado
lançado à mão pelos analistas. Trate-os como o `relatorio.db`.

## Decisões que valem revisão de vocês

- **Prints saem pelo Python, não pelo Caddy.** Contraria a regra do doc 12 de
  tirar estático do app, e foi de propósito: o print é prova, e servi-lo pelo
  Caddy o deixaria acessível sem passar pelo gate DIP/COIN. São imagens
  pequenas, vistas sob demanda, entregues por `FileResponse` (sendfile). Se o
  volume crescer, o caminho é o padrão do `/entrega/`: diretório com sufixo
  aleatório por link, servido pelo Caddy.
- **Gravação em disco fora do loop de eventos** (`run_in_threadpool`), porque o
  `cordel-web` roda com um worker só e 12 MB síncronos segurariam todo mundo.
- **Tipo do arquivo conferido pela assinatura**, não pelo `Content-Type` do
  navegador. Um `.png` com cabeçalho `MZ` é recusado — testado.
- **Numeração monotônica.** `REG-0007` excluído não volta a ser emitido: o
  número vai para ofício e procedimento.
- **Desvincular print exige intenção.** Um `PUT` sem o campo `prints` mantém os
  anexos; só uma lista explícita (inclusive vazia) altera o vínculo. O arquivo
  em disco só some no `DELETE` do print — desvínculo por engano é reversível.
  Em compensação, print desvinculado e nunca reaproveitado fica órfão no disco;
  não há expurgo automático, de propósito.
- **Auditoria** em `consulta_intel`, com `alvo` no formato
  `sentinela:<ação>:<id>` — consulta, inclusão, alteração, exclusão e upload.

## Como foi validado

Contra um CORDEL simulado (FastAPI real, cookie de sessão, `_exige_intel`,
`_ve_tudo`), com o módulo e o HTML de verdade, dirigido por navegador headless:

- gate: sem sessão → `/login`; sessão de fora do DIP → `403` na API e no print;
- inclusão com dois prints, conferindo SHA-256 no cliente e no servidor;
- alteração, exclusão, importação em lote com substituição;
- print entregue com o `Content-Type` certo e negado a quem não é DIP;
- travessia de caminho no id do print → `404`;
- arquivo com extensão de imagem e conteúdo de executável → `415`;
- duas sessões enxergando a mesma base;
- página sem erro de runtime, nos temas claro e escuro.
