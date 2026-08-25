# -*- coding: utf-8 -*-
"""Gera integracao-cordel/sentinela.html a partir do painel autônomo.

Mantém intactos gráficos, tabela, filtros, visualizador de prints e impressão.
Troca só a camada de dados: base local/chave → sessão do CORDEL + rotas do
Portal de Inteligência.
"""
import io, re, sys

ORIGEM = "dashboard/sentinela-eleitoral-ce.html"
DESTINO = "integracao-cordel/sentinela.html"

s = io.open(ORIGEM, encoding="utf-8").read()
trocas = 0


def troca(antigo, novo, conta=1):
    global s, trocas
    assert s.count(antigo) >= 1, "não achei: " + antigo[:80]
    s = s.replace(antigo, novo, conta)
    trocas += 1


def corta(inicio, fim, novo=""):
    """Remove o trecho entre dois marcadores (inclusive o inicial, exclusive o final)."""
    global s, trocas
    a = s.index(inicio)
    b = s.index(fim, a)
    s = s[:a] + novo + s[b:]
    trocas += 1


# ── 1. Cabeçalho da página ───────────────────────────────────────────────────
troca("<title>Sentinela Eleitoral Ceará</title>",
      "<title>Sentinela Eleitoral — CORDEL</title>")

troca('''  <button class="btn" id="btnBase" title="Origem dos dados"><span class="ponto" id="pontoBase"></span><span id="rotuloBase">Base local</span></button>
''',
      '''  <a class="btn" href="/inteligencia" title="Voltar ao Portal de Inteligência">← Portal</a>
  <span class="btn" id="chipUsuario" style="cursor:default"><span class="ponto" id="pontoBase"></span><span id="rotuloBase">conectando…</span></span>
''')

# ── 2. Avisos que não existem dentro do CORDEL ───────────────────────────────
corta('  <div class="notice" id="avisoAberta" hidden>', '  <!-- FILTROS -->')

# ── 3. Modal de origem de dados: fora ────────────────────────────────────────
corta('<div class="backdrop" id="modalBase">', '<div class="visor" id="visor"')

# ── 4. Rodapé explicativo ────────────────────────────────────────────────────
troca('''    Regiões conforme as 14 Regiões de Planejamento do Estado do Ceará (IPECE). A região é sugerida
    automaticamente a partir do município e pode ser corrigida manualmente em cada registro.
    Os dados ficam gravados apenas neste navegador (armazenamento local) — use o backup JSON para
    transportar a base entre máquinas. Documento de uso interno: classifique conforme a política
    de sigilo do órgão antes de compartilhar.''',
      '''    Regiões conforme as 14 Regiões de Planejamento do Estado do Ceará (IPECE). A região é sugerida
    automaticamente a partir do município e pode ser corrigida manualmente em cada registro.
    A base é única e fica no servidor do Departamento — o que um agente lança aparece para todos.
    Acesso restrito a DIP/COIN; toda consulta e toda gravação entram na trilha de auditoria.''')

# ── 5. Base de demonstração: fora (a base nasce vazia, com dado real) ────────
corta('/* ═══════════════════════════════════════════════════════════════\n'
      '   2. BASE DE DEMONSTRAÇÃO',
      '/* ═══════════════════════════════════════════════════════════════\n'
      '   3. ESTADO E PERSISTÊNCIA',
      'function baseDemo(){ return []; }\n\n')

# ── 6. Camada de dados ───────────────────────────────────────────────────────
troca('''/* Origem dos dados: "compartilhado" = base única no servidor do Departamento;
   "local" = apenas o armazenamento deste navegador. */
let modo = "local";
let servidor = "";               // vazio = mesma origem da página
let chaveAcesso = "";
let protegido = false;
let atualizadoEm = null;''',
      '''/* Base única no servidor do CORDEL. Autenticação é a sessão do próprio
   CORDEL (cookie cordel_sess) — não há chave separada nem modo local. */
const modo = "compartilhado";
const ROTA = "/intel/sentinela";
let usuario = "";
let atualizadoEm = null;''')

troca('''function guardarConexao(){
  try{
    localStorage.setItem(CHAVE+"_modo", modo);
    localStorage.setItem(CHAVE+"_servidor", servidor);
    localStorage.setItem(CHAVE+"_chave", chaveAcesso);
  }catch(e){}
}
function lerConexao(){
  try{
    servidor    = localStorage.getItem(CHAVE+"_servidor") || "";
    chaveAcesso = localStorage.getItem(CHAVE+"_chave") || "";
    return localStorage.getItem(CHAVE+"_modo") || "";
  }catch(e){ return ""; }
}

async function api(metodo, caminho, corpo){
  const opcoes = { method:metodo, headers:{} };
  if(corpo !== undefined){
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  if(chaveAcesso) opcoes.headers["x-sentinela-chave"] = chaveAcesso;
  const resp = await fetch((servidor||"") + caminho, opcoes);
  let dados = null;
  try{ dados = await resp.json(); }catch(e){}
  if(!resp.ok) throw new Error((dados && dados.error) || ("o servidor respondeu " + resp.status));
  return dados;
}''',
      '''async function api(metodo, caminho, corpo){
  const opcoes = { method:metodo, credentials:"same-origin", headers:{} };
  if(corpo !== undefined){
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const resp = await fetch(ROTA + caminho, opcoes);
  if(resp.status === 401){ location.href = "/login"; throw new Error("sessão expirada"); }
  let dados = null;
  try{ dados = await resp.json(); }catch(e){}
  if(!resp.ok) throw new Error((dados && dados.detail) || ("o servidor respondeu " + resp.status));
  return dados;
}
/* Envio de print: multipart, não base64 — o arquivo sobe como veio. */
async function apiPrint(arquivo){
  const corpo = new FormData();
  corpo.append("arquivo", arquivo, arquivo.name || "print");
  const resp = await fetch(ROTA + "/prints", {method:"POST", credentials:"same-origin", body:corpo});
  if(resp.status === 401){ location.href = "/login"; throw new Error("sessão expirada"); }
  let dados = null;
  try{ dados = await resp.json(); }catch(e){}
  if(!resp.ok) throw new Error((dados && dados.detail) || ("o servidor respondeu " + resp.status));
  return dados.print;
}''')

troca('''function absorver(resposta){
  registros = resposta.registros || [];
  atualizadoEm = resposta.atualizadoEm || null;
  protegido = !!resposta.protegido;
}
async function conectar(){
  const resposta = await api("GET","/api/registros");
  absorver(resposta);
  modo = "compartilhado";
  guardarConexao();
  return resposta;
}''',
      '''function absorver(resposta){
  registros = resposta.registros || [];
  atualizadoEm = resposta.atualizadoEm || null;
  if(resposta.usuario) usuario = resposta.usuario;
}
async function conectar(){
  const resposta = await api("GET","/registros");
  absorver(resposta);
  return resposta;
}''')

troca('''async function sincronizar(){
  if(modo !== "compartilhado" || document.hidden) return;
  try{
    const resposta = await api("GET","/api/registros");''',
      '''async function sincronizar(){
  if(document.hidden) return;
  try{
    const resposta = await api("GET","/registros");''')

troca('''function marcarBase(estado){
  const ponto = $("#pontoBase"), rotulo = $("#rotuloBase");
  if(!ponto) return;
  ponto.className = "ponto " + estado;
  if(modo === "compartilhado"){
    rotulo.textContent = estado === "off" ? "Base compartilhada (sem conexão)" : "Base compartilhada";
    $("#btnBase").title = "Base única em " + (servidor || "este servidor") +
      (atualizadoEm ? " · atualizada em " + new Date(atualizadoEm).toLocaleString("pt-BR") : "");
  }else{
    rotulo.textContent = "Base local";
    $("#btnBase").title = "Os dados ficam apenas neste navegador. Clique para conectar à base compartilhada.";
  }
  $("#avisoAberta").hidden = !(modo === "compartilhado" && !protegido);
}''',
      '''function marcarBase(estado){
  const ponto = $("#pontoBase"), rotulo = $("#rotuloBase");
  if(!ponto) return;
  ponto.className = "ponto " + estado;
  rotulo.textContent = estado === "off" ? "sem conexão com a base"
                     : (usuario ? usuario : "base do Departamento");
  $("#chipUsuario").title = "Base única do Departamento de Inteligência" +
    (atualizadoEm ? " · sincronizada às " + new Date(atualizadoEm).toLocaleTimeString("pt-BR") : "");
}''')

troca('''/* Armazenamento local — usado apenas fora da base compartilhada */
function carregarLocal(){
  try{
    const bruto = localStorage.getItem(CHAVE);
    if(bruto){
      const obj = JSON.parse(bruto);
      if(Array.isArray(obj)){ registros = obj; return; }
      if(obj && Array.isArray(obj.registros)){ registros = obj.registros; return; }
    }
  }catch(e){ /* armazenamento indisponível — segue com a base de demonstração */ }
  registros = baseDemo();
}
function salvar(){
  if(modo === "compartilhado") return;
  try{ localStorage.setItem(CHAVE, JSON.stringify({versao:1, registros})); }
  catch(e){ aviso("A base local encheu — provavelmente por causa dos prints. Conecte-se à base compartilhada ou exporte um backup JSON."); }
}
function temDemo(){ return modo !== "compartilhado" && registros.some(r=>r.demo); }''',
      '''function carregarLocal(){ registros = []; }
function salvar(){ /* a base vive no servidor */ }
function temDemo(){ return false; }''')

# ── 6b. A tarja de demonstração não existe aqui ──────────────────────────────
troca('  $("#avisoDemo").hidden = !temDemo();\n', '')

# ── 7. Prints: upload pela rota do CORDEL ────────────────────────────────────
troca('''      if(modo === "compartilhado"){
        const r = await api("POST","/api/prints",
          { nome:provisorio.nome, tipo:arq.type, sha256, dados:paraBase64(buffer) });
        Object.assign(provisorio, r.print, {enviando:false, dados:null});
      }else{
        provisorio.dados = "data:"+arq.type+";base64,"+paraBase64(buffer);
        provisorio.sha256 = sha256;
        provisorio.enviando = false;
      }''',
      '''      const enviado = await apiPrint(arq);
      if(sha256 && enviado.sha256 && sha256 !== enviado.sha256)
        throw new Error("hash divergente — o arquivo chegou corrompido");
      Object.assign(provisorio, enviado, {enviando:false, dados:null});''')

troca('''async function subirAnexosPendentes(){
  for(const p of anexos){
    if(!p.dados || !String(p.dados).startsWith("data:")) continue;
    const base64 = String(p.dados).split(",")[1] || "";
    const r = await api("POST","/api/prints",
      { nome:p.nome, tipo:p.tipo, sha256:p.sha256, dados:base64 });
    Object.assign(p, r.print, {dados:null});
  }
}''',
      '''async function subirAnexosPendentes(){ /* os prints já sobem ao serem anexados */ }''')

troca('  return p.dados ? p.dados : (servidor||"") + "/api/prints/" + encodeURIComponent(p.id);',
      '  return p.dados ? p.dados : ROTA + "/prints/" + encodeURIComponent(p.id);')

# ── 8. Gravação e exclusão: sempre no servidor ───────────────────────────────
troca('''  if(modo === "compartilhado"){
    try{
      await subirAnexosPendentes();
      dados.prints = anexos.map(p=>({id:p.id, nome:p.nome, tipo:p.tipo, tamanho:p.tamanho, sha256:p.sha256, em:p.em}));
    }catch(e){
      erro.textContent = "Falha ao enviar os prints: " + e.message;
      erro.hidden = false; return;
    }
    try{
      const resposta = editandoId
        ? await api("PUT", "/api/registros/" + encodeURIComponent(editandoId), dados)
        : await api("POST", "/api/registros", dados);
      absorver(resposta);
      aviso(editandoId ? "Registro atualizado na base compartilhada." : "Registro incluído na base compartilhada.");
    }catch(e){
      erro.textContent = "Não foi possível gravar: " + e.message;
      erro.hidden = false; return;
    }
  }else{
    if(editandoId){
      const i = registros.findIndex(r=>r.id===editandoId);
      registros[i] = {...registros[i], ...dados, demo:false};
      aviso("Registro atualizado.");
    }else{
      registros.unshift({id:novoId(), ...dados});
      aviso("Registro incluído na base.");
    }
    salvar();
  }
  fecharModal(); render();''',
      '''  try{
    const resposta = editandoId
      ? await api("PUT", "/registros/" + encodeURIComponent(editandoId), dados)
      : await api("POST", "/registros", dados);
    absorver(resposta);
    aviso(editandoId ? "Registro atualizado na base do Departamento."
                     : "Registro incluído na base do Departamento.");
  }catch(e){
    erro.textContent = "Não foi possível gravar: " + e.message;
    erro.hidden = false; return;
  }
  fecharModal(); render();''')

troca('''  if(modo === "compartilhado"){
    try{
      absorver(await api("DELETE", "/api/registros/" + encodeURIComponent(editandoId)));
    }catch(e){
      const erro = $("#erroForm");
      erro.textContent = "Não foi possível excluir: " + e.message;
      erro.hidden = false; return;
    }
  }else{
    registros = registros.filter(r=>r.id!==editandoId);
    salvar();
  }
  fecharModal();''',
      '''  try{
    absorver(await api("DELETE", "/registros/" + encodeURIComponent(editandoId)));
  }catch(e){
    const erro = $("#erroForm");
    erro.textContent = "Não foi possível excluir: " + e.message;
    erro.hidden = false; return;
  }
  fecharModal();''')

# ── 9. Importação em lote ────────────────────────────────────────────────────
troca('''  const onde = modo === "compartilhado" ? "a base compartilhada" : "a base local";''',
      '''  const onde = "a base do Departamento";''')

troca('''  if(modo === "compartilhado"){
    try{
      absorver(await api("POST","/api/registros/lote",{registros:limpos, substituir}));
    }catch(e){ aviso("Falha na importação: "+e.message); return; }
  }else{
    registros = substituir ? limpos : registros.filter(r=>!r.demo).concat(limpos);
    salvar();
  }
  render();''',
      '''  try{
    absorver(await api("POST","/lote",{registros:limpos, substituir}));
  }catch(e){ aviso("Falha na importação: "+e.message); return; }
  render();''')

# ── 10. Eventos e inicialização ──────────────────────────────────────────────
troca('''  /* Origem dos dados */
  $("#btnBase").addEventListener("click", abrirModalBase);
  $("#btnFecharBase").addEventListener("click", fecharModalBase);
  $("#btnCancelarBase").addEventListener("click", fecharModalBase);
  $("#formBase").addEventListener("submit", conectarPeloFormulario);
  $("#btnUsarLocal").addEventListener("click", ()=>{
    modo = "local"; guardarConexao(); carregarLocal();
    marcarBase(""); fecharModalBase(); render();
    aviso("Painel usando a base local deste navegador.");
  });
  $("#modalBase").addEventListener("mousedown", e=>{ if(e.target.id === "modalBase") fecharModalBase(); });''',
      '''  /* Recarga manual da base */
  $("#chipUsuario").addEventListener("dblclick", sincronizar);''')

troca('''  $("#btnLimparDemo").addEventListener("click", ()=>{
    if(!confirm("Remover todos os registros de demonstração e iniciar a base vazia?")) return;
    registros = registros.filter(r=>!r.demo);
    salvar(); render(); aviso("Base de demonstração removida.");
  });
}''', '}')

troca('''    if(e.key === "Escape"){
      if($("#modalBase").classList.contains("on")) fecharModalBase();
      else if($("#modal").classList.contains("on")) fecharModal();
    }''',
      '''    if(e.key === "Escape" && $("#modal").classList.contains("on")) fecharModal();''')

corta('function abrirModalBase(){', '/* Abre na base compartilhada sempre',
      '')

troca('''/* Abre na base compartilhada sempre que ela estiver ao alcance; cai para a
   base local quando o painel roda como arquivo solto ou o servidor não responde. */
async function iniciarBase(){
  const modoGravado = lerConexao();
  const podeServidor = servidor || location.protocol === "http:" || location.protocol === "https:";
  if(podeServidor && modoGravado !== "local"){
    try{
      await conectar();
      marcarBase("on");
      return;
    }catch(e){
      if(modoGravado === "compartilhado"){
        aviso("Base compartilhada fora de alcance — abrindo a cópia local.");
      }
    }
  }
  modo = "local";
  carregarLocal();
  marcarBase("");
}''',
      '''async function iniciarBase(){
  try{
    await conectar();
    marcarBase("on");
  }catch(e){
    marcarBase("off");
    aviso("Não foi possível falar com a base: " + e.message);
  }
}''')

# ── 11. Downloads: dentro do CORDEL é sempre o link direto ───────────────────
troca('''let nsDownloads = null, nsDownloadsResolvido = false;
async function obterDownloads(){
  if(nsDownloadsResolvido) return nsDownloads;
  nsDownloadsResolvido = true;
  try{
    nsDownloads = (window.claude && typeof window.claude.use === "function")
      ? await window.claude.use("downloads") : null;
  }catch(e){ nsDownloads = null; }
  return nsDownloads;
}''',
      '''async function obterDownloads(){ return null; }''')

io.open(DESTINO, "w", encoding="utf-8").write(s)
print("trocas aplicadas:", trocas)
print("tamanho:", len(s), "bytes")
for proibido in ["chaveAcesso", "x-sentinela-chave", "modalBase", "avisoAberta",
                 "btnLimparDemo", "/api/registros", "/api/prints", "DEMO-"]:
    if proibido in s:
        print("  ⚠ ainda aparece:", proibido)
        sys.exit(1)
print("nenhum resíduo da versão autônoma")
