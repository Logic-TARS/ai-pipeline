from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from content_pipeline.script_generation.client import OpenAICompatibleScriptClient
from content_pipeline.settings import Settings


class _Handler(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.received = json.loads(self.rfile.read(length))
        body = json.dumps({"choices": [{"message": {"content": "测试回复。"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return None


def test_openai_compatible_client_against_http_fake() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(
            _env_file=None,
            script_llm_base_url=f"http://127.0.0.1:{server.server_port}/v1",
            script_llm_model="fake-model",
        )
        result = OpenAICompatibleScriptClient(settings).complete(system_prompt="system", user_prompt="user")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert result == "测试回复。"
    assert _Handler.received["model"] == "fake-model"
    assert _Handler.received["messages"][1] == {"role": "user", "content": "user"}
