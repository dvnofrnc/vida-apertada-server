const express = require('express');
const fetch = require('node-fetch');
const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const DATA_FILE = path.join('/tmp', 'vida_apertada_data.json');

// ── CORS ────────────────────────────────────────────────────────────────────
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, x-sentinela-chave');
  res.setHeader('Access-Control-Max-Age', '86400');
  if (req.method === 'OPTIONS') return res.status(204).end();
  next();
});

app.use(express.json({ limit: '50mb' }));

// ── HEALTH ──────────────────────────────────────────────────────────────────
app.get('/', (req, res) => {
  res.json({ status: 'ok', message: 'Vida Apertada API Proxy', dashboard: '/dashboard' });
});

// ── DASHBOARD ───────────────────────────────────────────────────────────────
// Painel de monitoramento de ameaças ao pleito (Departamento de Inteligência)
app.get('/dashboard', (req, res) => {
  res.sendFile(path.join(__dirname, 'dashboard', 'sentinela-eleitoral-ce.html'));
});


// ── BASE COMPARTILHADA DO PAINEL ELEITORAL ──────────────────────────────────
// Arquivo próprio, separado dos dados do app. Defina DATA_DIR para apontar
// para um disco persistente; sem isso a base fica em /tmp e se perde a cada
// reinício do serviço.
const SENTINELA_FILE  = path.join(process.env.DATA_DIR || '/tmp', 'sentinela_eleitoral.json');
// Com SENTINELA_CHAVE definida, toda gravação exige o cabeçalho
// x-sentinela-chave. Sem ela, qualquer pessoa com o link grava na base.
const SENTINELA_CHAVE = process.env.SENTINELA_CHAVE || '';
const LIMITE_REGISTROS = 20000;
const LIMITE_PRINTS = 12;                       // prints por registro
const TAMANHO_MAX_PRINT = 12 * 1024 * 1024;     // 12 MB por print
const PRINTS_DIR = path.join(process.env.DATA_DIR || '/tmp', 'sentinela_prints');
const TIPOS_PRINT = {
  'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
  'image/gif': 'gif', 'application/pdf': 'pdf'
};

function lerBase() {
  try {
    if (!fs.existsSync(SENTINELA_FILE)) return { registros: [], atualizadoEm: null };
    const obj = JSON.parse(fs.readFileSync(SENTINELA_FILE, 'utf8'));
    return {
      registros: Array.isArray(obj.registros) ? obj.registros : [],
      atualizadoEm: obj.atualizadoEm || null
    };
  } catch (err) {
    console.error('base do painel ilegível:', err.message);
    return { registros: [], atualizadoEm: null };
  }
}

function gravarBase(registros) {
  const atualizadoEm = new Date().toISOString();
  fs.mkdirSync(path.dirname(SENTINELA_FILE), { recursive: true });
  const tmp = SENTINELA_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify({ versao: 1, atualizadoEm, registros }), 'utf8');
  fs.renameSync(tmp, SENTINELA_FILE);
  return atualizadoEm;
}

const txt = (v, max) => String(v === undefined || v === null ? '' : v).trim().slice(0, max);

function saneia(bruto, id, anterior) {
  const agora = new Date().toISOString();
  return {
    id,
    data: /^\d{4}-\d{2}-\d{2}$/.test(bruto.data) ? bruto.data : agora.slice(0, 10),
    teor: txt(bruto.teor, 2000),
    plataforma: txt(bruto.plataforma, 60),
    url: txt(bruto.url, 600),
    cidade: txt(bruto.cidade, 120),
    regiao: txt(bruto.regiao, 120),
    identificador: txt(bruto.identificador, 200),
    tipoIdent: txt(bruto.tipoIdent, 60),
    tipo: txt(bruto.tipo, 120),
    nivel: txt(bruto.nivel, 20),
    alcance: Math.max(0, Math.min(Math.round(Number(bruto.alcance) || 0), 1e12)),
    destinos: Array.isArray(bruto.destinos) ? bruto.destinos.slice(0, 24).map(d => txt(d, 80)).filter(Boolean) : [],
    situacao: txt(bruto.situacao, 60),
    resultado: txt(bruto.resultado, 80),
    procedimento: txt(bruto.procedimento, 80),
    obs: txt(bruto.obs, 2000),
    prints: Array.isArray(bruto.prints) ? bruto.prints.slice(0, LIMITE_PRINTS).map(pr => ({
      id: txt(pr && pr.id, 80),
      nome: txt(pr && pr.nome, 200),
      tipo: txt(pr && pr.tipo, 60),
      tamanho: Math.max(0, Math.min(Math.round(Number(pr && pr.tamanho) || 0), 1e9)),
      sha256: txt(pr && pr.sha256, 64),
      em: txt(pr && pr.em, 40)
    })).filter(pr => pr.id) : [],
    registradoEm: (anterior && anterior.registradoEm) || agora,
    atualizadoEm: agora
  };
}

function proximoId(registros) {
  let maior = 0;
  registros.forEach(r => {
    const m = /^REG-(\d+)$/.exec(String(r && r.id || ''));
    if (m) maior = Math.max(maior, Number(m[1]));
  });
  return 'REG-' + String(maior + 1).padStart(4, '0');
}

// Bloqueia a gravação quando há chave configurada e o pedido não a apresenta.
function bloqueado(req, res) {
  if (!SENTINELA_CHAVE) return false;
  if (req.get('x-sentinela-chave') === SENTINELA_CHAVE) return false;
  res.status(401).json({ ok: false, error: 'Chave de acesso ausente ou inválida.' });
  return true;
}

const resposta = (res, registros, atualizadoEm, extra) =>
  res.json(Object.assign({
    ok: true,
    protegido: Boolean(SENTINELA_CHAVE),
    atualizadoEm,
    registros
  }, extra || {}));

// Leitura da base inteira
app.get('/api/registros', (req, res) => {
  const base = lerBase();
  resposta(res, base.registros, base.atualizadoEm);
});

// Inclusão de um caso
app.post('/api/registros', (req, res) => {
  if (bloqueado(req, res)) return;
  const base = lerBase();
  if (base.registros.length >= LIMITE_REGISTROS) {
    return res.status(413).json({ ok: false, error: 'Limite de registros da base atingido.' });
  }
  const novo = saneia(req.body || {}, proximoId(base.registros), null);
  if (!novo.teor || !novo.cidade || !novo.identificador) {
    return res.status(400).json({ ok: false, error: 'Teor, cidade e identificador são obrigatórios.' });
  }
  base.registros.unshift(novo);
  const atualizadoEm = gravarBase(base.registros);
  resposta(res, base.registros, atualizadoEm, { registro: novo });
});

// Alteração de um caso
app.put('/api/registros/:id', (req, res) => {
  if (bloqueado(req, res)) return;
  const base = lerBase();
  const i = base.registros.findIndex(r => r.id === req.params.id);
  if (i < 0) return res.status(404).json({ ok: false, error: 'Registro não encontrado.' });
  base.registros[i] = saneia(req.body || {}, req.params.id, base.registros[i]);
  const atualizadoEm = gravarBase(base.registros);
  resposta(res, base.registros, atualizadoEm, { registro: base.registros[i] });
});

// Exclusão de um caso
app.delete('/api/registros/:id', (req, res) => {
  if (bloqueado(req, res)) return;
  const base = lerBase();
  const restantes = base.registros.filter(r => r.id !== req.params.id);
  if (restantes.length === base.registros.length) {
    return res.status(404).json({ ok: false, error: 'Registro não encontrado.' });
  }
  const atualizadoEm = gravarBase(restantes);
  resposta(res, restantes, atualizadoEm);
});

// Carga em lote — acrescenta ou substitui a base inteira
app.post('/api/registros/lote', (req, res) => {
  if (bloqueado(req, res)) return;
  const entrada = Array.isArray(req.body && req.body.registros) ? req.body.registros : null;
  if (!entrada) return res.status(400).json({ ok: false, error: 'Envie { registros: [...] }.' });
  const base = lerBase();
  const manter = req.body.substituir ? [] : base.registros;
  if (manter.length + entrada.length > LIMITE_REGISTROS) {
    return res.status(413).json({ ok: false, error: 'Limite de registros da base atingido.' });
  }
  let seq = manter.slice();
  const novos = entrada.map(bruto => {
    const r = saneia(bruto, proximoId(seq), null);
    seq = seq.concat([r]);
    return r;
  }).filter(r => r.teor || r.identificador || r.cidade);
  const registros = novos.concat(manter);
  const atualizadoEm = gravarBase(registros);
  resposta(res, registros, atualizadoEm, { importados: novos.length });
});

// ── PRINTS DAS POSTAGENS ────────────────────────────────────────────────────
// O arquivo enviado é gravado como veio, sem recompressão, para preservar a
// integridade da prova. O hash SHA-256 é conferido no recebimento.
app.post('/api/prints', (req, res) => {
  if (bloqueado(req, res)) return;
  const { nome, tipo, dados, sha256 } = req.body || {};
  const ext = TIPOS_PRINT[tipo];
  if (!ext) return res.status(415).json({ ok: false, error: 'Formato não aceito. Use PNG, JPEG, WebP, GIF ou PDF.' });
  if (typeof dados !== 'string' || !dados) return res.status(400).json({ ok: false, error: 'Arquivo vazio.' });

  let bytes;
  try { bytes = Buffer.from(dados, 'base64'); }
  catch (err) { return res.status(400).json({ ok: false, error: 'Conteúdo ilegível.' }); }
  if (!bytes.length) return res.status(400).json({ ok: false, error: 'Arquivo vazio.' });
  if (bytes.length > TAMANHO_MAX_PRINT) {
    return res.status(413).json({ ok: false, error: 'Print acima de 12 MB.' });
  }

  const hash = crypto.createHash('sha256').update(bytes).digest('hex');
  if (sha256 && sha256 !== hash) {
    return res.status(400).json({ ok: false, error: 'Arquivo corrompido no envio (hash divergente).' });
  }

  const id = crypto.randomBytes(12).toString('hex');
  fs.mkdirSync(PRINTS_DIR, { recursive: true });
  fs.writeFileSync(path.join(PRINTS_DIR, id + '.' + ext), bytes);
  res.json({
    ok: true,
    print: {
      id, nome: txt(nome, 200) || ('print.' + ext), tipo,
      tamanho: bytes.length, sha256: hash, em: new Date().toISOString()
    }
  });
});

function caminhoPrint(id) {
  if (!/^[0-9a-f]{24}$/.test(String(id || ''))) return null;
  for (const ext of Object.values(TIPOS_PRINT)) {
    const alvo = path.join(PRINTS_DIR, id + '.' + ext);
    if (fs.existsSync(alvo)) return { alvo, ext };
  }
  return null;
}

app.get('/api/prints/:id', (req, res) => {
  const achado = caminhoPrint(req.params.id);
  if (!achado) return res.status(404).json({ ok: false, error: 'Print não encontrado.' });
  const tipo = Object.keys(TIPOS_PRINT).find(k => TIPOS_PRINT[k] === achado.ext);
  res.setHeader('Content-Type', tipo);
  res.setHeader('Cache-Control', 'private, max-age=86400');
  fs.createReadStream(achado.alvo).pipe(res);
});

app.delete('/api/prints/:id', (req, res) => {
  if (bloqueado(req, res)) return;
  const achado = caminhoPrint(req.params.id);
  if (achado) fs.unlinkSync(achado.alvo);
  res.json({ ok: true });
});

// ── MODELOS ─────────────────────────────────────────────────────────────────
app.get('/models', async (req, res) => {
  try {
    const response = await fetch('https://api.anthropic.com/v1/models', {
      headers: { 'x-api-key': ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01' }
    });
    res.json(await response.json());
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── DADOS PERSISTENTES ───────────────────────────────────────────────────────
// GET /data  — carrega os dados salvos
app.get('/data', (req, res) => {
  try {
    if (fs.existsSync(DATA_FILE)) {
      const raw = fs.readFileSync(DATA_FILE, 'utf8');
      res.json({ ok: true, data: JSON.parse(raw) });
    } else {
      res.json({ ok: true, data: null }); // sem dados ainda
    }
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /data  — salva os dados
app.post('/data', (req, res) => {
  try {
    fs.writeFileSync(DATA_FILE, JSON.stringify(req.body), 'utf8');
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// ── PROXY CLAUDE ─────────────────────────────────────────────────────────────
app.post('/api/claude', async (req, res) => {
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY não configurada' });
  }
  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify(req.body)
    });
    const data = await response.json();
    if (!response.ok) return res.status(response.status).json(data);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => console.log(`Servidor rodando na porta ${PORT}`));
