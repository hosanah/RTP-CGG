# RTP-CGG

Aplicação Flask que consulta o endpoint `https://cgg.bet.br` e exibe em tempo real o RTP (Return to Player) dos jogos de cassino.

## Pré-requisitos

- **Python** 3.12 ou superior com `pip` instalado.
- **Docker** (opcional) para executar a aplicação em container.

## Como executar

### Utilizando Python

1. Crie um ambiente virtual e instale as dependências:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Inicie o servidor Flask com suporte a WebSocket:
   ```bash
   python app.py
   ```
   Não utilize `flask run`, pois o websocket requer que o servidor do
   `Flask-SocketIO` seja iniciado. O serviço ficará disponível em
   `http://localhost:5000`.

### Utilizando Docker

1. Construa a imagem:
   ```bash
   docker build -t rtp-cgg .
   ```
2. Execute o container informando a porta desejada (padrão `5000`):
   ```bash
   docker run -e PORT=5000 -p 5000:5000 rtp-cgg
   ```
3. Acesse `http://localhost:5000` para visualizar o dashboard. Em
   produção, execute o servidor com:
   ```bash
   gunicorn -k eventlet -b 0.0.0.0:5000 wsgi:app
   ```

Esse mesmo Dockerfile funciona em plataformas como o **EasyPanel**, bastando informar a variável `PORT` caso a hospedagem utilize outra porta padrão.

## Scripts disponíveis

- `app.py` – servidor Flask principal.
- `Dockerfile` – script para criar a imagem Docker.
- `requirements.txt` – lista de dependências Python.

## Variáveis de ambiente

O projeto carrega variáveis definidas em um arquivo `.env` se presente. Nenhuma variável é obrigatória, mas várias opções podem ser configuradas manualmente:

- `FLASK_APP` e `FLASK_ENV` podem ser usados ao executar via `flask run`.
- `PORT` pode definir a porta do servidor caso utilize o comando `flask run`.
- Defina `DEBUG_REQUESTS=true` para registrar detalhes das chamadas HTTP.
- A variável `FLASK_DEBUG` controla o modo debug do Flask.
- `DATABASE_URL` define a conexão PostgreSQL (também lida via `.env`).
- `REQUEST_TIMEOUT` ajusta o tempo limite das requisições RTP (padrão `10`).
- `WINNERS_TIMEOUT` define o timeout para `/api/last-winners`.
- `RTP_UPDATE_INTERVAL` controla a pausa entre buscas automáticas (padrão `3`).

Aplicação Flask que exibe os dados de RTP de jogos em tempo real.

### Buscar RTP por jogo

Utilize a rota `/api/search-rtp` para obter o RTP mais atual de cada jogo
informado na requisição:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"names":["Wisdom of Athena"]}' \
  http://localhost:5000/api/search-rtp
```

A resposta retornará o RTP mais recente de cada título enviado.

## Verificação SSL
Por padrão, as requisições HTTPS verificam o certificado do servidor. Para manter a segurança, **não desative** essa verificação em ambientes de produção.

Caso precise desabilitar temporariamente, defina a variável `VERIFY_SSL=false`
ou utilize a flag `--insecure`:

```bash
VERIFY_SSL=false python app.py
# ou
python app.py --insecure
```

O domínio `cgg.bet` pode apresentar um certificado que não corresponde ao
endereço. Com `VERIFY_SSL=true`, a biblioteca `requests` lança
`requests.exceptions.SSLError`. Para consultar esse site, desative a verificação
e indique a casa `cgg` nos endpoints:

```bash
VERIFY_SSL=false python app.py
curl -X POST -H "Content-Type: application/json" \
  -d '{"names":["Wisdom of Athena"]}' \
  http://localhost:5000/api/search-rtp/cgg
```

Utilize essa opção apenas em cenários de desenvolvimento ou testes.


## Banco de dados PostgreSQL

A aplicação usa PostgreSQL para salvar o histórico de RTP. O endereço padrão é
`postgres://postgres:2412055aa@185.44.66.206:5432/vigilancia?sslmode=disable`,
mas é possível definir a variável `DATABASE_URL` para alterar a conexão.

Crie a tabela executando o script `schema.sql`:

```bash
psql "$DATABASE_URL" -f schema.sql
```

Se a tabela já existir, atualize o tipo da coluna `game_id` executando:

```bash
psql "$DATABASE_URL" -c "ALTER TABLE rtp_history ALTER COLUMN game_id TYPE BIGINT"
psql "$DATABASE_URL" -c "ALTER TABLE rtp_history ALTER COLUMN extra TYPE BIGINT"
psql "$DATABASE_URL" -c "ALTER TABLE rtp_history ADD COLUMN rtp_status TEXT"
psql "$DATABASE_URL" -c "UPDATE rtp_history SET rtp_status = CASE WHEN extra IS NULL THEN 'neutral' WHEN extra < 0 THEN 'down' ELSE 'up' END"
psql "$DATABASE_URL" -c "ALTER TABLE rtp_history ADD COLUMN casa TEXT DEFAULT 'cgg'"
psql "$DATABASE_URL" -c "UPDATE rtp_history SET casa = 'cgg'"
```


## Habilitar página de analytics

A página `/analytics` fica desabilitada por padrão. Defina a variável
`ENABLE_ANALYTICS=true` antes de iniciar o servidor para ativá-la:

```bash
ENABLE_ANALYTICS=true python app.py
```

### Consultar histórico

O endpoint `/api/history` retorna os registros gravados na tabela `rtp_history`.

Exemplos de uso:

```bash
# Últimos 50 registros
curl http://localhost:5000/api/history?limit=50

# Filtrar por jogo específico
curl http://localhost:5000/api/history?game_id=1024
```

## Documentação para contribuidores

As diretrizes de instalação e desenvolvimento estão em `AGENTS.md`. Já o arquivo `agents.md` concentra a descrição dos agentes e integrações. Consulte ambos ao fazer alterações.