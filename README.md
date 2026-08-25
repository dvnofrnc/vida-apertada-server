# Vida Apertada Server

Servidor Node/Express que reúne duas coisas:

- o **proxy** da API usada pelo aplicativo Vida Apertada (`/models`, `/data`, `/api/claude`);
- o **Sentinela Eleitoral Ceará**, painel de monitoramento de ameaças ao pleito
  do Departamento de Inteligência, servido em `/dashboard` e com base
  compartilhada em `/api/registros` e `/api/prints`.

## Rodando na própria máquina

```bash
npm install
DATA_DIR=./dados node server.js
```

O painel fica em <http://localhost:3000/dashboard>.

O arquivo `dashboard/sentinela-eleitoral-ce.html` também abre sozinho, com dois
cliques, sem servidor nenhum — nesse modo os dados ficam apenas no navegador de
quem abriu. Pela barra superior do painel, em **Base**, dá para apontar esse
arquivo solto para o servidor do Departamento e passar a trabalhar na base
compartilhada.

## Publicando em servidor próprio (Linux)

Com acesso ao servidor por SSH, um comando resolve:

```bash
git clone https://github.com/dvnofrnc/vida-apertada-server /tmp/sentinela
sudo bash /tmp/sentinela/deploy/instalar.sh
```

O script instala o Node se faltar, cria um usuário sem privilégios para o
serviço, publica o código em `/opt/sentinela`, aponta os dados para
`/var/lib/sentinela`, **gera uma chave de acesso** e registra o serviço no
systemd, para subir sozinho a cada reinício do servidor. Ao terminar, imprime o
endereço do painel e a chave.

Rodar o mesmo comando depois de um commit novo atualiza a instalação sem perder
dados.

### Sob um domínio, com HTTPS

Com o registro A do DNS já apontando para o servidor:

```bash
sudo bash /opt/sentinela/deploy/publicar-dominio.sh SEU-DOMINIO seu@email dip
```

O script confere o DNS, instala Nginx e certbot, publica o painel no domínio,
emite o certificado HTTPS com renovação automática, libera as portas no firewall
e — por causa do terceiro argumento — cria um **login de navegador** que protege
o painel inteiro, inclusive a leitura.

Esse terceiro argumento é opcional, mas importante: a `SENTINELA_CHAVE` protege
só a gravação. Sem o login, quem descobrir o endereço lê toda a base. Para dado
de investigação exposto na internet, use os dois.

`deploy/nginx.conf.exemplo` traz a mesma configuração para quem preferir
escrever à mão, e mostra como restringir o acesso por faixa de IP.

Comandos do dia a dia:

```bash
systemctl status sentinela      # estado do serviço
journalctl -u sentinela -f      # acompanhar o log
systemctl restart sentinela     # reiniciar
```

## Publicando em serviço de nuvem

O `render.yaml` na raiz já descreve o serviço. Em <https://render.com>:

1. **New → Blueprint** e escolha este repositório.
2. Confirme. O Render lê o `render.yaml`, cria o serviço, monta o disco
   persistente e aponta `DATA_DIR` para ele.
3. Em **Environment**, preencha `SENTINELA_CHAVE` com a senha que a equipe vai
   usar (veja abaixo) e, se o app Vida Apertada for usar o proxy,
   `ANTHROPIC_API_KEY`.
4. O endereço aparece no topo da página do serviço. O painel fica em
   `https://SEU-ENDERECO/dashboard`.

Qualquer outro provedor de Node serve igualmente — Railway, Fly.io, uma VM
própria. O que não pode faltar em nenhum deles: **`DATA_DIR` apontando para
armazenamento persistente**. Sem isso a base é gravada em `/tmp` e se perde a
cada reinício.

## Variáveis de ambiente

| Variável | Para que serve |
|---|---|
| `PORT` | Porta de escuta. Padrão `3000`; a maioria dos provedores define sozinha. |
| `DATA_DIR` | Pasta onde ficam a base do painel e os prints. Padrão `/tmp` — **troque em produção**. |
| `SENTINELA_CHAVE` | Chave de acesso do painel. Definida, toda gravação exige o cabeçalho `x-sentinela-chave`; vazia, a base fica aberta a quem tiver o endereço. |
| `ANTHROPIC_API_KEY` | Usada só pelo proxy `/api/claude` do app. |

### Sobre a chave de acesso

Sem `SENTINELA_CHAVE`, qualquer pessoa que descubra o endereço lê, inclui,
altera e exclui registros — e o painel exibe uma tarja de alerta enquanto for
assim. Com a chave definida, cada pessoa a informa uma vez por navegador, em
**Base**, e o painel a guarda naquela máquina.

A leitura permanece aberta nos dois casos. Se o painel precisar de sigilo também
na consulta, ele deve ficar atrás da rede interna do órgão ou de um proxy com
autenticação, não exposto na internet aberta.

## Endpoints do painel

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/dashboard` | Serve o painel. |
| `GET` | `/api/registros` | Devolve a base inteira. |
| `POST` | `/api/registros` | Inclui um caso. |
| `PUT` | `/api/registros/:id` | Altera um caso. |
| `DELETE` | `/api/registros/:id` | Exclui um caso. |
| `POST` | `/api/registros/lote` | Carga em lote — acrescenta ou substitui a base. |
| `POST` | `/api/prints` | Recebe um print (PNG, JPEG, WebP, GIF ou PDF, até 12 MB) e confere o SHA-256. |
| `GET` | `/api/prints/:id` | Devolve o print. |
| `DELETE` | `/api/prints/:id` | Remove o print. |

Os arquivos de print são gravados como chegaram, sem recompressão, para
preservar a integridade da prova.

## Cópias de segurança

O painel exporta a base em **CSV** (para planilha) e em **JSON** (backup
completo, que preserva a referência dos prints). O CSV não transporta prints.

Um backup do servidor equivale a copiar o conteúdo de `DATA_DIR`:
`sentinela_eleitoral.json` e a pasta `sentinela_prints/`.
