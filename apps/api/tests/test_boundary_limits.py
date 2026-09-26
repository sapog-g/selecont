"""Regression checks for streaming limits and safe local binding."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selecont.web import RequestBodyLimitMiddleware, FORM_LIMIT


class BoundaryTests(unittest.TestCase):
    def test_chunked_form_limit_stops_receiving_at_limit(self):
        async def check():
            reads, messages = [], []
            async def receive():
                reads.append(1)
                return {"type": "http.request", "body": b"a" * 8192, "more_body": True}
            async def send(message):
                messages.append(message)
            async def app(scope, receive, send):
                while (await receive()).get("more_body"):
                    pass
            wrapped = RequestBodyLimitMiddleware(app, limit=FORM_LIMIT * 10)
            await wrapped({"type": "http", "method": "POST", "path": "/login", "headers": []}, receive, send)
            self.assertEqual(len(reads), 3)
            self.assertEqual(messages[0]["status"], 413)
        asyncio.run(check())

    def test_launcher_defaults_to_loopback_and_allows_explicit_host(self):
        script = Path(__file__).resolve().parents[1] / "scripts/start-one.sh"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            fake.chmod(0o700)
            env = {**os.environ, "PATH": tmp + os.pathsep + os.environ.get("PATH", ""), "SELECONT_DATABASE": "unused", "SELECONT_MEDIA_ROOT": "unused", "SELECONT_SECRET_KEY": "test-only-value-with-at-least-32-bytes"}
            env.pop("SELECONT_BIND_HOST", None)
            for value, expected in ((None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")):
                if value:
                    env["SELECONT_BIND_HOST"] = value
                result = subprocess.run(["sh", str(script)], env=env, check=True, capture_output=True, text=True).stdout.splitlines()
                self.assertEqual(result[result.index("--host") + 1], expected)
