import os
import urllib3
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from flask import send_file, abort

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()
import requests
from google.protobuf import message_factory
from google.protobuf.descriptor_pb2 import FileDescriptorProto
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.json_format import MessageToDict

import db

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

DEBUG_REQUESTS = os.environ.get("DEBUG_REQUESTS", "false").lower() in (
    "1",
    "true",
    "yes",
)

# Permite personalizar a verificação SSL via variável de ambiente.
# A verificação é habilitada por padrão e só é desativada quando
# `VERIFY_SSL=false` é definido explicitamente.
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() not in (
    "false",
    "0",
    "no",
)
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "3"))
WINNERS_TIMEOUT = float(os.environ.get("WINNERS_TIMEOUT", str(REQUEST_TIMEOUT)))
RTP_UPDATE_INTERVAL = float(os.environ.get("RTP_UPDATE_INTERVAL", "3"))

url = "https://cgg.bet.br/casinogo/widgets/v2/live-rtp"
search_url = "https://cgg.bet.br/casinogo/widgets/v2/live-rtp/search"
headers = {
    "accept": "application/x-protobuf",
    "content-type": "application/x-protobuf",
    "accept-language": "pt-BR",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
        "Gecko/20100101 Firefox/140.0"
    ),
    "x-language-iso": "pt-BR",
    "origin": "https://cgg.bet.br",
    "referer": "https://cgg.bet.br/pt-BR/casinos/casino/lobby",
}
data = b"\x08\x01\x10\x02"
data_weekly = b"\x08\x02\x10\x02"

IMAGE_CACHE_DIR = "image_cache"
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)


def get_protobuf_message():
    proto_schema = FileDescriptorProto()
    proto_schema.name = "rtp.proto"
    proto_schema.package = "rtp"

    game = proto_schema.message_type.add()
    game.name = "Game"

    game.field.add(name="id", number=1, type=3)
    game.field.add(name="name", number=2, type=9)
    game_provider = game.nested_type.add()
    game_provider.name = "Provider"
    game_provider.field.add(name="name", number=2, type=9)
    game_provider.field.add(name="slug", number=5, type=9)

    game.field.add(name="provider", number=3, type=11, type_name=".rtp.Game.Provider")
    game.field.add(name="image", number=4, type=9)
    game.field.add(name="rtp", number=5, type=5)
    game.field.add(name="extra", number=6, type=4)

    response = proto_schema.message_type.add()
    response.name = "Response"
    response.field.add(name="games", number=2, type=11, type_name=".rtp.Game", label=3)

    pool = DescriptorPool()
    file_desc = pool.Add(proto_schema)
    response_desc = file_desc.message_types_by_name["Response"]

    return message_factory.GetMessageClass(response_desc)


ProtobufMessage = get_protobuf_message()

latest_games = []


def decode_signed(value):
    if value >= (1 << 63):
        value -= 1 << 64
    return value


def prioritize_games(games):
    sorted_games = sorted(games, key=lambda g: g.get("extra", 0))
    for game in sorted_games:
        extra_val = game.get("extra", 0)
        if extra_val <= -200:
            game["prioridade"] = "🔥 Alta prioridade"
        elif extra_val < 0:
            game["prioridade"] = "⚠️ Média prioridade"
        else:
            game["prioridade"] = "✅ Neutra ou positiva"
    return sorted_games


def has_changes(novos, antigos):
    """Verifica se a lista de jogos foi alterada."""
    mapa_antigo = {g.get("id"): g for g in antigos}
    for jogo in novos:
        jid = jogo.get("id")
        anterior = mapa_antigo.get(jid)
        if anterior is None:
            return True
        if jogo.get("rtp") != anterior.get("rtp") or jogo.get("extra") != anterior.get(
            "extra"
        ):
            return True
    return False


def fetch_games_data():
    if DEBUG_REQUESTS:
        print("\n[DEBUG] >>> Enviando Requisição <<<")
        print(f"[DEBUG] URL: {url}")
        print(f"[DEBUG] Headers: {headers}")
        print(f"[DEBUG] Data (bytes): {data}")
        print(f"[DEBUG] SSL Verify: {VERIFY_SSL}")

    response = requests.post(
        url, headers=headers, data=data, verify=VERIFY_SSL, timeout=REQUEST_TIMEOUT
    )

    if DEBUG_REQUESTS:
        print("\n[DEBUG] >>> Enviando Requisição Semanal <<<")
        print(f"[DEBUG] Data Semanal (bytes): {data_weekly}")

    response_weekly = requests.post(
        url,
        headers=headers,
        data=data_weekly,
        verify=VERIFY_SSL,
        timeout=REQUEST_TIMEOUT,
    )

    if DEBUG_REQUESTS:
        print("\n[DEBUG] <<< Recebendo Resposta >>>")
        print(f"[DEBUG] Status Code: {response.status_code}")
        print(f"[DEBUG] Response Content (raw bytes): {response.content}\n")
        print("\n[DEBUG] <<< Recebendo Resposta Semanal >>>")
        print(f"[DEBUG] Status Code: {response_weekly.status_code}")
        print(f"[DEBUG] Response Content (raw bytes): {response_weekly.content}\n")

    decoded_message = ProtobufMessage()
    decoded_message.ParseFromString(response.content)
    games = MessageToDict(decoded_message).get("games", [])

    decoded_weekly = ProtobufMessage()
    decoded_weekly.ParseFromString(response_weekly.content)
    games_weekly = MessageToDict(decoded_weekly).get("games", [])
    week_map = {g["id"]: g for g in games_weekly}

    for game in games:
        extra = game.get("extra")
        if extra is not None:
            game["extra"] = decode_signed(int(extra))
            game["rtp_status"] = "down" if game["extra"] < 0 else "up"
        else:
            game["rtp_status"] = "neutral"

        week = week_map.get(game["id"])
        game["rtp_semana"] = week.get("rtp") if week else None
        game["extra_semana"] = (
            decode_signed(int(week["extra"])) if week and week.get("extra") else None
        )

        if game["extra_semana"] is None:
            game["status_semana"] = "neutral"
        elif game["extra_semana"] < 0:
            game["status_semana"] = "down"
        else:
            game["status_semana"] = "up"

    if DEBUG_REQUESTS:
        print("[DEBUG] <<< Mensagem Decodificada (JSON) >>>")
        print(games)

    return games


def fetch_games_by_name(names: list[str]):
    results = []
    for name in names:
        body = b"\x02\x10\x19\x12" + len(name).to_bytes(1, "little") + name.encode()

        if DEBUG_REQUESTS:
            print("\n[DEBUG] >>> Enviando Busca RTP <<<")
            print(f"[DEBUG] URL: {search_url}")
            print(f"[DEBUG] Nome: {name}")
            print(f"[DEBUG] Headers: {headers}")
            print(f"[DEBUG] Data (bytes): {body}")
            print(f"[DEBUG] SSL Verify: {VERIFY_SSL}")

        try:
            resp = requests.post(
                search_url,
                headers=headers,
                data=body,
                verify=VERIFY_SSL,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()

            decoded = ProtobufMessage()
            decoded.ParseFromString(resp.content)
            games = MessageToDict(decoded).get("games", [])
            for game in games:
                extra = game.get("extra")
                if extra is not None:
                    game["extra"] = decode_signed(int(extra))
                    game["rtp_status"] = "down" if game["extra"] < 0 else "up"
                else:
                    game["rtp_status"] = "neutral"
            results.extend(games)

            if DEBUG_REQUESTS:
                print("[DEBUG] <<< Resposta Busca RTP >>>")
                print(f"[DEBUG] Status Code: {resp.status_code}")
                print(f"[DEBUG] Conteúdo JSON: {games}\n")
        except requests.RequestException as exc:
            if DEBUG_REQUESTS:
                print("[DEBUG] Erro na busca RTP")
                print(exc)
    return results


def search_local(names: list[str]):
    queries = [str(n).lower() for n in names]
    global latest_games
    if not latest_games:
        latest_games = fetch_games_data()
    return [g for g in latest_games if any(q in g["name"].lower() for q in queries)]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/melhores")
def melhores():
    return render_template("melhores.html")


@app.route("/historico")
def historico():
    return render_template("historico.html")


@app.route("/historico-registros")
def historico_registros():
    """Página de histórico em formato de grade."""
    return render_template("historico_grid.html")


@app.route("/registro-extra")
def registro_extra():
    """Página que exibe jogos filtrados pela média de unidades."""
    return render_template("registro_extra.html")


@app.route("/api/games")
def games():
    global latest_games
    latest_games = fetch_games_data()
    return jsonify(latest_games)


@app.route("/api/melhores")
def api_melhores():
    global latest_games
    latest_games = fetch_games_data()
    return jsonify(prioritize_games(latest_games))


@app.route("/api/history")
def api_history():
    period = request.args.get("period", "daily")
    game_id = request.args.get("game_id")
    name = request.args.get("name")
    try:
        gid = int(game_id) if game_id is not None else None
    except ValueError:
        return jsonify([]), 400
    try:
        return jsonify(db.query_history(period, game_id=gid, name=name))
    except ValueError:
        return jsonify([]), 400


@app.route("/api/history/games")
def api_history_games():
    """Lista jogos disponíveis no histórico."""
    return jsonify(db.list_games())


@app.route("/api/game-history")
def api_game_history():
    gid = request.args.get("game_id", type=int)
    if gid is None:
        return jsonify([]), 400
    return jsonify(db.game_history(gid))


@app.route("/api/history/records")
def api_history_records():
    """Retorna registros brutos do historico."""
    start = request.args.get("start")
    end = request.args.get("end")
    gid = request.args.get("game_id")
    name = request.args.get("name")
    provider = request.args.get("provider")
    extra = request.args.get("extra")
    return jsonify(db.history_records(start, end, gid, name, provider, extra))


@app.route("/api/registro-extra")
def api_registro_extra():
    """Retorna jogos filtrados pela média de unidades."""
    start = request.args.get("dataInicial")
    end = request.args.get("dataFinal")
    extra = request.args.get("extra", type=int)
    if not start or not end or extra is None:
        return jsonify([]), 400
    return jsonify(db.games_by_extra(start, end, extra))


@app.route("/api/search-rtp", methods=["POST"])
def api_search_rtp():
    try:
        names = request.get_json(force=True).get("names", [])
        if not isinstance(names, list):
            return jsonify([])
        games = fetch_games_by_name([str(n) for n in names])
        if not games:
            games = search_local(names)
        return jsonify(games)
    except Exception as exc:
        if DEBUG_REQUESTS:
            print("[DEBUG] Erro no endpoint de busca")
            print(exc)
        return jsonify([])


@app.route("/imagens/<int:game_id>.webp")
def cached_image(game_id):
    file_path = os.path.join(IMAGE_CACHE_DIR, f"{game_id}.webp")
    if not os.path.exists(file_path):
        remote_url = f"https://cgg.bet.br/static/v1/casino/game/0/{game_id}/big.webp"
        try:
            resp = requests.get(remote_url, verify=VERIFY_SSL, timeout=10)
            resp.raise_for_status()
            with open(file_path, "wb") as img_file:
                img_file.write(resp.content)
        except requests.RequestException:
            abort(404)
    response = send_file(
        file_path,
        mimetype="image/webp",
        max_age=86400,
    )
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@socketio.on("connect")
def handle_connect():
    if latest_games:
        emit("games_update", latest_games)


def background_fetch():
    global latest_games
    while True:
        try:
            novos = fetch_games_data()
            if has_changes(novos, latest_games):
                latest_games = novos
                db.insert_games(latest_games)
                socketio.emit("games_update", latest_games)
        finally:
            socketio.sleep(RTP_UPDATE_INTERVAL)


@app.route("/api/last-winners")
def last_winners():
    winners_url = "https://cgg.bet.br/casinogo/widgets/last-winners"
    winners_headers = headers.copy()
    winners_headers["accept"] = "application/json"

    try:
        if DEBUG_REQUESTS:
            print("\n[DEBUG] >>> Enviando Requisição Últimos Vencedores <<<")
            print(f"[DEBUG] URL: {winners_url}")
            print(f"[DEBUG] Headers: {winners_headers}")
            print(f"[DEBUG] SSL Verify: {VERIFY_SSL}")

        response = requests.post(
            winners_url,
            headers=winners_headers,
            verify=VERIFY_SSL,
            timeout=WINNERS_TIMEOUT,
        )
        response.raise_for_status()

        if DEBUG_REQUESTS:
            print("\n[DEBUG] <<< Resposta Últimos Vencedores >>>")
            print(f"[DEBUG] Status Code: {response.status_code}")
            print(f"[DEBUG] Conteúdo JSON: {response.text}\n")

        return jsonify(response.json())
    except requests.RequestException as exc:
        if DEBUG_REQUESTS:
            print("[DEBUG] Erro na requisição de últimos vencedores")
            print(exc)
        return (
            jsonify({"erro": "Falha ao buscar últimos vencedores"}),
            500,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--insecure", action="store_true", help="Desativa verificação SSL"
    )
    args, _ = parser.parse_known_args()
    if args.insecure:
        VERIFY_SSL = False

    socketio.start_background_task(background_fetch)
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    socketio.run(
        app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug_mode
    )
