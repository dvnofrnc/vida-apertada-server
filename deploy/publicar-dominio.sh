#!/usr/bin/env bash
#
# Publica o Sentinela Eleitoral Ceará sob um domínio, com HTTPS.
#
#   sudo bash deploy/publicar-dominio.sh DOMINIO EMAIL [USUARIO_DE_LOGIN]
#
# Exemplo:
#   sudo bash deploy/publicar-dominio.sh painel.exemplo.gov.br ti@exemplo.gov.br dip
#
# Antes de rodar, o domínio já precisa apontar para o IP deste servidor
# (registro A no DNS). O script confere isso e avisa se ainda não propagou.
#
# O terceiro argumento é opcional e cria um login de acesso ao painel inteiro,
# pedido pelo navegador antes de qualquer coisa carregar. Sem ele, qualquer
# pessoa que descubra o endereço consegue LER a base — a chave do painel
# protege apenas a gravação. Para dado de investigação exposto na internet,
# vale a pena usar.

set -euo pipefail

DOMINIO=${1:-}
EMAIL=${2:-}
LOGIN=${3:-}
PORTA=${PORTA:-3000}

erro(){ echo "  ✗ $*" >&2; exit 1; }
passo(){ echo; echo "── $*"; }

[ "$(id -u)" -eq 0 ] || erro "Rode como root: sudo bash deploy/publicar-dominio.sh ..."
[ -n "$DOMINIO" ] || erro "Informe o domínio. Ex.: sudo bash $0 painel.exemplo.gov.br ti@exemplo.gov.br"
[ -n "$EMAIL" ]   || erro "Informe um e-mail para o certificado. Ex.: sudo bash $0 $DOMINIO ti@exemplo.gov.br"

systemctl is-active --quiet sentinela \
  || erro "O serviço sentinela não está no ar. Rode antes: sudo bash deploy/instalar.sh"

passo "Conferindo o DNS de $DOMINIO"
IP_SERVIDOR=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
IP_DOMINIO=$(getent ahostsv4 "$DOMINIO" 2>/dev/null | awk '{print $1; exit}' || true)
if [ -z "$IP_DOMINIO" ]; then
  erro "$DOMINIO ainda não resolve. Crie o registro A apontando para $IP_SERVIDOR e espere a propagação."
elif [ "$IP_DOMINIO" != "$IP_SERVIDOR" ]; then
  echo "  ⚠ $DOMINIO aponta para $IP_DOMINIO, e este servidor é $IP_SERVIDOR."
  echo "    O certificado vai falhar se o apontamento estiver errado."
  read -r -p "    Seguir mesmo assim? [s/N] " resposta
  [ "${resposta,,}" = "s" ] || exit 1
else
  echo "  $DOMINIO → $IP_SERVIDOR"
fi

passo "Nginx e certbot"
command -v nginx   >/dev/null 2>&1 || { apt-get update -qq; apt-get install -y nginx; }
command -v certbot >/dev/null 2>&1 || apt-get install -y certbot python3-certbot-nginx
command -v htpasswd >/dev/null 2>&1 || apt-get install -y apache2-utils

TRECHO_LOGIN=""
if [ -n "$LOGIN" ]; then
  passo "Login de acesso ao painel"
  if [ -f /etc/nginx/.sentinela-htpasswd ] && grep -q "^$LOGIN:" /etc/nginx/.sentinela-htpasswd; then
    echo "  Usuário $LOGIN já existe — senha mantida."
    echo "  Para trocar: sudo htpasswd /etc/nginx/.sentinela-htpasswd $LOGIN"
  else
    echo "  Defina a senha do usuário '$LOGIN' (a equipe usa a mesma):"
    if [ -f /etc/nginx/.sentinela-htpasswd ]; then
      htpasswd /etc/nginx/.sentinela-htpasswd "$LOGIN"
    else
      htpasswd -c /etc/nginx/.sentinela-htpasswd "$LOGIN"
    fi
    chown root:www-data /etc/nginx/.sentinela-htpasswd
    chmod 640 /etc/nginx/.sentinela-htpasswd
  fi
  TRECHO_LOGIN='
    auth_basic           "Sentinela Eleitoral — acesso restrito";
    auth_basic_user_file /etc/nginx/.sentinela-htpasswd;'
fi

passo "Configurando o Nginx"
cat > /etc/nginx/sites-available/sentinela <<FIM
server {
    listen 80;
    listen [::]:80;
    server_name $DOMINIO;

    # Prints chegam por upload; o padrão do Nginx cortaria os maiores.
    client_max_body_size 20m;

    access_log /var/log/nginx/sentinela-acesso.log;
    error_log  /var/log/nginx/sentinela-erro.log;

    location / {$TRECHO_LOGIN
        proxy_pass http://127.0.0.1:$PORTA;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
FIM
ln -sf /etc/nginx/sites-available/sentinela /etc/nginx/sites-enabled/sentinela
rm -f /etc/nginx/sites-enabled/default
nginx -t || erro "Configuração do Nginx recusada — nada foi aplicado."
systemctl reload nginx
echo "  Aplicada."

passo "Liberando as portas no firewall"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "Nginx Full" >/dev/null 2>&1 || true
  echo "  Portas 80 e 443 liberadas no ufw."
else
  echo "  ufw não está ativo — nada a fazer aqui."
  echo "  Se houver firewall na frente do servidor, libere as portas 80 e 443."
fi

passo "Certificado HTTPS"
certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos -m "$EMAIL" --redirect \
  || erro "O certbot falhou. Confira o DNS e tente de novo: sudo certbot --nginx -d $DOMINIO"
systemctl reload nginx

echo
echo "════════════════════════════════════════════════════════════════"
echo " Painel publicado"
echo "════════════════════════════════════════════════════════════════"
echo
echo "  Endereço:  https://$DOMINIO/dashboard"
echo
if [ -n "$LOGIN" ]; then
  echo "  Login do navegador:  $LOGIN  (a senha que o senhor acabou de definir)"
fi
echo "  Chave de gravação:   $(grep '^SENTINELA_CHAVE=' /etc/sentinela.env | cut -d= -f2-)"
echo "                       (informada uma vez por máquina, no botão 'Base')"
echo
echo "  O certificado se renova sozinho. Para conferir:"
echo "      sudo certbot renew --dry-run"
echo
