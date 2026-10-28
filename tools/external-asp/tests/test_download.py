#!/usr/bin/env python3
"""Only loopback HTTP/self-signed HTTPS fixtures; never any external OTA."""
import argparse
import contextlib
import http.server
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_installer as f
import installer_download as d
import installer_payload as payload
import installer_sources as sources


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        try:
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/good")
                self.end_headers()
                return
            if self.path == "/loop":
                self.send_response(302)
                self.send_header("Location", "/loop")
                self.end_headers()
                return
            if self.path == "/file":
                self.send_response(302)
                self.send_header("Location", "file:///etc/passwd")
                self.end_headers()
                return
            if self.path == "/sleep":
                time.sleep(.3)
            raw = self.server.body if self.path != "/corrupt" else b"CORRUPT ZIP"
            self.send_response(200)
            if self.path != "/unknown":
                self.send_header("Content-Length", str(len(raw) + (100 if self.path == "/truncated" else 0)))
            self.end_headers()
            if self.path == "/slow":
                for i in range(200):
                    self.wfile.write(raw[:1])
                    self.wfile.flush()
                    time.sleep(.02)
                return
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass


@contextlib.contextmanager
def server(body, context=None):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.daemon_threads = True
    s.body = body
    if context:
        s.socket = context.wrap_socket(s.socket, server_side=True)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        yield ("https" if context else "http") + "://127.0.0.1:" + str(s.server_port)
    finally:
        s.shutdown()
        s.server_close()
        t.join()


class Download(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f.Installer.setUpClass()
        cls.cert_tmp = tempfile.TemporaryDirectory(prefix="asp2-cert-")
        cert = Path(cls.cert_tmp.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=deliberately-wrong-host.invalid", "-keyout", str(cert / "key"),
                        "-out", str(cert / "cert")], check=True, capture_output=True)
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.load_cert_chain(cert / "cert", cert / "key")

    @classmethod
    def tearDownClass(cls):
        f.Installer.tearDownClass()
        cls.cert_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="asp2-http-")
        self.work = Path(self.tmp.name)
        self.fixture = f.Installer()
        self.fixture.work = self.work
        self.body = self.fixture.ota.read_bytes()
        self.target = self.work / "ota.zip"

    def tearDown(self):
        self.tmp.cleanup()

    def test_http_stream_atomic(self):
        with server(self.body) as url:
            r = d.download(url + "/good", self.target)
        self.assertEqual(self.target.read_bytes(), self.body)
        self.assertFalse(r["authenticated"])
        self.assertFalse(self.target.with_suffix(".zip.partial").exists())

    def test_self_signed_wrong_hostname_prepare_without_authority(self):
        with server(self.body, self.context) as url:
            a = self.fixture.args(ota=None, ota_url=url + "/good", source_authority=None, fixture=True)
            payload.prepare(a)
        self.assertTrue(payload.validate(a.output)["installable"])
        self.assertTrue(payload.validate(a.output)["source"]["download_stored_locally"])
        self.assertFalse(list(self.work.glob(".asp2-*")))

    def test_redirect(self):
        with server(self.body) as url:
            d.download(url + "/redirect", self.target)
        self.assertEqual(self.target.read_bytes(), self.body)

    def test_redirect_limit(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "redirect"):
                d.download(url + "/loop", self.target)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_non_http_redirect_blocked(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "HTTP"):
                d.download(url + "/file", self.target)
        self.assertFalse(self.target.exists())

    def test_socket_timeout_cleanup(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "download failed"):
                d.download(url + "/sleep", self.target, timeout=.05)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_total_timeout_trickle_cleanup(self):
        with server(self.body) as url:
            before = time.monotonic()
            with self.assertRaisesRegex(ValueError, "total timeout"):
                d.download(url + "/slow", self.target, total_timeout=.1)
        self.assertLess(time.monotonic() - before, 1.5)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_interrupted_download(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "truncated|failed"):
                d.download(url + "/truncated", self.target)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_oversized_length(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "size limit"):
                d.download(url + "/good", self.target, max_bytes=10)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_oversized_without_length(self):
        with server(self.body) as url:
            with self.assertRaisesRegex(ValueError, "size limit"):
                d.download(url + "/unknown", self.target, max_bytes=10)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_insufficient_free_space(self):
        with server(self.body) as url, patch.object(d.shutil, "disk_usage", return_value=argparse.Namespace(free=0)):
            with self.assertRaisesRegex(ValueError, "storage"):
                d.download(url + "/good", self.target)
        self.assertFalse(self.target.exists())

    def test_corrupt_download_prepare_cleans_everything(self):
        with server(self.body) as url:
            a = self.fixture.args(ota=None, ota_url=url + "/corrupt", source_authority=None, fixture=True)
            with self.assertRaisesRegex(ValueError, "damaged"):
                payload.prepare(a)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_cancellation_sigint_cli_cleans_source_and_stage(self):
        with server(self.body) as url:
            command = [sys.executable, "-B", str(f.TOOLS / "asp2_installer.py"), "prepare",
                       "--mode", sources.BUNDLE, "--ota-url", url + "/slow",
                       "--fixture", "--output", str(self.work / "payload"),
                       "--launcher", str(self.fixture.launcher), "--child", str(self.fixture.child),
                       "--channel-map", str(self.fixture.map), "--mapping-authority", str(self.fixture.mapping_path)]
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not list(self.work.rglob("*.partial")):
                time.sleep(.01)
            p.send_signal(signal.SIGINT)
            out, err = p.communicate(timeout=5)
        self.assertEqual(p.returncode, 130, err)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_credentials_not_in_errors_or_receipts(self):
        with server(self.body) as url:
            url = url.replace("://", "://secret-user:secret-password@")
            a = self.fixture.args(ota=None, ota_url=url + "/good", source_authority=None, fixture=True)
            receipt = payload.prepare(a)
        self.assertNotIn("secret", json.dumps(receipt))
        self.assertNotIn("secret", (a.output / payload.RECEIPT).read_text())

    def test_optional_expected_hash(self):
        with server(self.body) as url:
            a = argparse.Namespace(ota=None, ota_url=url + "/good", expected_sha256="0" * 64)
            with self.assertRaisesRegex(ValueError, "optional expected"):
                with d.selected_ota(a, self.work):
                    pass
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
