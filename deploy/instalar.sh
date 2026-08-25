#!/usr/bin/env bash
#
# Instala o Sentinela Eleitoral Ceará em um servidor Linux (Debian/Ubuntu).
#
#   sudo bash deploy/instalar.sh
#
# O que ele faz: instala o Node se faltar, cria um usuário sem privilégios para
# rodar o serviço, publica o código em /opt/sentinela, aponta os dados para
# /var/lib/sentinela, gera uma chave de acesso se ainda não houver e registra o
# serviço no systemd para subir sozinho a cada reinício do servidor.
#
# Rodar de novo depois de um commit novo atualiza a instalação sem perder dados.

set -euo pipefail

APP_DIR=${APP_DIR:-/opt/sentinela}
DADOS_DIR=${DADOS_DIR:-/var/lib/sentinela}
USUARIO=${USUARIO:-sentinela}
PORTA=${PORTA:-3000}
REPO=${REPO:-https://github.com/dvnofrnc/vida-apertada-server}
RAMO=${RAMO:-main}
ENV_FILE=/etc/sentinela.env

erro(){ echo "  ✗ $*" >&2; exit 1; }
passo(){ echo; echo "── $*"; }

[ "$(id -u)" -eq 0 ] || erro "Rode como root: sudo bash deploy/instalar.sh"

passo "Conferindo o Node"
if ! command -v node >/dev/null 2>&1; then
  echo "  Node não encontrado — instalando a versão 22."
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi
VERSAO=$(node -p "process.versions.node.split('.')[0]")
[ "$VERSAO" -ge 18 ] || erro "Node $VERSAO é antigo demais. O servidor precisa da versão 18 ou maior."
echo "  Node $(node -v)"

command -v git >/dev/null 2>&1 || { echo "  Instalando git."; apt-get install -y git; }

passo "Usuário do serviço"
if id "$USUARIO" >/dev/null 2>&1; then
  echo "  $USUARIO já existe."
else
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USUARIO"
  echo "  $USUARIO criado."
fi

passo "Código em $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$RAMO"
  git -C "$APP_DIR" reset --quiet --hard "origin/$RAMO"
  echo "  Atualizado para o topo de $RAMO."
else
  mkdir -p "$APP_DIR"
  git clone --quiet --branch "$RAMO" "$REPO" "$APP_DIR"
  echo "  Clonado."
fi
( cd "$APP_DIR" && npm install --omit=dev --silent --no-audit --no-fund )

passo "Pasta de dados em $DADOS_DIR"
mkdir -p "$DADOS_DIR"
chown -R "$USUARIO":"$USUARIO" "$DADOS_DIR" "$APP_DIR"
chmod 750 "$DADOS_DIR"
echo "  Base e prints ficam aqui. É esta pasta que precisa entrar na rotina de backup."

passo "Chave de acesso"
if [ -f "$ENV_FILE" ] && grep -q '^SENTINELA_CHAVE=' "$ENV_FILE"; then
  echo "  Já configurada em $ENV_FILE — mantida."
else
  CHAVE=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20)
  cat > "$ENV_FILE" <<FIM
# Configuração do Sentinela Eleitoral Ceará
PORT=$PORTA
DATA_DIR=$DADOS_DIR
SENTINELA_CHAVE=$CHAVE
# Preencha se este servidor também for o proxy do app Vida Apertada:
ANTHROPIC_API_KEY=
FIM
  chmod 600 "$ENV_FILE"
  echo "  Gerada e gravada em $ENV_FILE."
fi

passo "Serviço do systemd"
install -m 644 "$APP_DIR/deploy/sentinela.service" /etc/systemd/system/sentinela.service
sed -i "s#__APP_DIR__#$APP_DIR#g; s#__USUARIO__#$USUARIO#g; s#__DADOS_DIR__#$DADOS_DIR#g" \
  /etc/systemd/system/sentinela.service
systemctl daemon-reload
systemctl enable --quiet sentinela
systemctl restart sentinela
sleep 2

if systemctl is-active --quiet sentinela; then
  echo "  Serviço no ar."
else
  echo "  ✗ O serviço não subiu. Veja o motivo com: journalctl -u sentinela -n 40 --no-pager"
  exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "════════════════════════════════════════════════════════════════"
echo " Sentinela Eleitoral Ceará instalado"
echo "════════════════════════════════════════════════════════════════"
echo
echo "  Painel:   http://${IP:-localhost}:$PORTA/dashboard"
echo "  Dados:    $DADOS_DIR"
echo "  Config:   $ENV_FILE"
echo
echo "  Chave de acesso (informe uma vez em cada máquina, no botão 'Base'):"
echo
echo "      $(grep '^SENTINELA_CHAVE=' "$ENV_FILE" | cut -d= -f2-)"
echo
echo "  Comandos úteis:"
echo "      systemctl status sentinela      estado do serviço"
echo "      journalctl -u sentinela -f      acompanhar o log"
echo "      systemctl restart sentinela     reiniciar"
echo
echo "  Antes de expor na internet, ponha o Nginx com HTTPS na frente:"
echo "      veja deploy/nginx.conf.exemplo"
echo
