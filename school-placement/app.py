"""Локальный HTTP-интерфейс. Запуск: python school-placement/app.py."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from model import MATRIX, load_model, rank_variants, read_blocks, result_payload, validate_placements

HERE = Path(__file__).resolve().parent


def make_server(host="127.0.0.1", port=8765, matrix_path=MATRIX):
    blocks = read_blocks()
    model, error = None, None
    try:
        model = load_model(blocks, matrix_path)
    except (ValueError, OSError) as exc:
        error = str(exc) if Path(matrix_path).exists() else (
            "Нет исходной матрицы времени практики 2: school-placement/input/accessibility_matrix.csv.gz. "
            "Карта показывает сохранённые показатели; сценарии заблокированы. Инструкция восстановления — в README."
        )
    # Просмотр исходных данных доступен даже при отсутствующей матрице. Это не воспроизведение расчёта.
    baseline = model.payload(model.baseline) if model else result_payload(blocks, blocks, blocks)
    geometry = json.loads(blocks[["geometry"]].to_crs(4326).to_json())
    for feature, block_id in zip(geometry["features"], blocks.index):
        feature["properties"] = {"block_id": int(block_id)}
    busy = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/data":
                self.send_json({"ready": model is not None, "error": error,
                                "geometry": geometry, "baseline": baseline, "geometry_crs": "EPSG:4326"})
            elif self.path in ("/", "/index.html", "/style.css", "/main.js",
                               "/vendor/leaflet/leaflet.js", "/vendor/leaflet/leaflet.css"):
                name = "index.html" if self.path == "/" else self.path[1:]
                body = (HERE / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", {".html": "text/html; charset=utf-8",
                                                  ".css": "text/css", ".js": "text/javascript"}[Path(name).suffix])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json({"error": "Страница не найдена."}, 404)

        def do_POST(self):
            # Без CORS и с проверкой Origin: сторонняя страница не запускает локальный расчёт.
            if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
                self.send_json({"error": "Недопустимый источник запроса."}, 403)
                return
            if self.path not in ("/api/calculate", "/api/search"):
                self.send_json({"error": "Неизвестная операция."}, 404)
                return
            if model is None:
                self.send_json({"error": error}, 409)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("Слишком большой или пустой запрос.")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Ожидается объект запроса.")
                if self.path == "/api/calculate":
                    placements = validate_placements(data.get("placements"), blocks.index)
                else:
                    capacity = data.get("capacity")
                    validate_placements([{"block_id": int(blocks.index[0]), "capacity": capacity}], blocks.index)
            except (ValueError, TypeError) as exc:
                self.send_json({"error": str(exc)}, 400)
                return
            if not busy.acquire(blocking=False):
                self.send_json({"error": "Идёт другой расчёт. Дождитесь его завершения."}, 409)
                return
            try:
                if self.path == "/api/calculate":
                    self.send_json(model.payload(model.calculate(placements)))
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    variants = []
                    for variant in model.search(capacity):
                        variants.append(variant)
                        self.wfile.write((json.dumps({"progress": len(variants), "total": len(blocks),
                                                      "variant": variant}, ensure_ascii=False) + "\n").encode())
                        self.wfile.flush()
                    self.wfile.write((json.dumps({"done": rank_variants(variants, len(blocks))},
                                                 ensure_ascii=False) + "\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                if self.path == "/api/calculate":
                    self.send_json({"error": "Расчёт не выполнен: " + str(exc)}, 500)
                else:
                    # Заголовки потока уже отправлены. Клиент не примет оборванный поток за полный перебор.
                    self.wfile.write((json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n").encode())
            finally:
                busy.release()

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = make_server(port=args.port)
    print(f"Откройте http://127.0.0.1:{server.server_port} — остановка Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
