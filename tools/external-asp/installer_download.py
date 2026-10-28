"""Explicit user-selected HTTP(S) OTA download; source is not authenticated."""
import base64
import contextlib
import hashlib
import os
from pathlib import Path
import re
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from installer_sources import Refusal, digest, require

MAX_BYTES = 2 * 1024**3
SOCKET_TIMEOUT = 30
TOTAL_TIMEOUT = 1800
RESERVE = 64 * 1024**2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url):
    try:
        p = urllib.parse.urlsplit(url)
        require(p.scheme in ("http", "https") and p.hostname ,
                "OTA URL must be HTTP(S), with a host")
        port = p.port
        host = "[" + p.hostname + "]" if ":" in p.hostname else p.hostname
        if port:
            host += ":" + str(port)
        clean = urllib.parse.urlunsplit((p.scheme, host, p.path or "/", p.query, ""))
        headers = {"Accept-Encoding": "identity", "User-Agent": "FrankenASP-I2-S"}
        if p.username is not None:
            credentials = urllib.parse.unquote(p.username) + ":" + urllib.parse.unquote(p.password or "")
            headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
        return urllib.request.Request(clean, headers=headers)
    except (ValueError, UnicodeError) as e:
        raise Refusal("invalid OTA HTTP(S) URL") from e


def download(url, target, max_bytes=MAX_BYTES, timeout=SOCKET_TIMEOUT, total_timeout=TOTAL_TIMEOUT):
    target = Path(target)
    require(not target.exists() and not target.is_symlink(), "download target already exists")
    require(0 < max_bytes <= 8 * 1024**3 and 0 < timeout <= 120 and 0 < total_timeout <= 7200,
            "invalid download size/time bounds")
    partial = target.with_suffix(target.suffix + ".partial")
    # User explicitly permits arbitrary certificates/hostnames, including private servers.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    deadline = time.monotonic() + total_timeout
    response = None
    try:
        for hops in range(6):
            require(time.monotonic() < deadline, "OTA download total timeout")
            req = request(url)
            try:
                response = opener.open(req, timeout=min(timeout, max(.01, deadline - time.monotonic())))
                break
            except urllib.error.HTTPError as e:
                try:
                    require(e.code in (301, 302, 303, 307, 308), "OTA HTTP request failed: status " + str(e.code))
                    require(hops < 5 and e.headers.get("Location"), "OTA redirect limit/missing location")
                    url = urllib.parse.urljoin(req.full_url, e.headers["Location"])
                    # Revalidate every redirect. Never forward old credentials across redirects.
                    request(url)
                finally:
                    e.close()
        require(response is not None, "OTA redirect limit exceeded")
        with response:
            require(response.status == 200, "OTA server must return complete status 200")
            length = response.headers.get("Content-Length")
            if length is not None:
                require(length.isdecimal(), "invalid OTA Content-Length")
                length = int(length)
                require(0 < length <= max_bytes, "OTA body exceeds size limit")
                require(shutil.disk_usage(target.parent).free >= length + RESERVE,
                        "insufficient download storage (OTA plus 64MiB reserve)")
            require(response.headers.get("Content-Encoding", "identity") == "identity",
                    "encoded HTTP body unsupported")
            count = 0
            with partial.open("xb") as f:
                while True:
                    require(time.monotonic() < deadline, "OTA download total timeout")
                    # read1 returns after one socket read, so a trickling response cannot
                    # hold a read(n) indefinitely past the total deadline.
                    raw = response.read1(256 * 1024)
                    if not raw:
                        break
                    count += len(raw)
                    require(count <= max_bytes, "OTA body exceeds size limit")
                    require(shutil.disk_usage(target.parent).free >= len(raw) + RESERVE,
                            "insufficient download storage")
                    f.write(raw)
                require(count > 0 and (length is None or count == length), "interrupted/truncated OTA download")
                f.flush()
                os.fsync(f.fileno())
        os.rename(partial, target)
        return {"bytes": count, "authenticated": False, "tls_certificate_validation": False,
                "stored_locally": True}
    except (OSError, urllib.error.URLError, ValueError) as e:
        if isinstance(e, Refusal):
            raise
        # Exception strings often contain full URLs/userinfo. Deliberately omit them.
        raise Refusal("OTA HTTP(S) download failed: " + type(e).__name__) from None
    finally:
        partial.unlink(missing_ok=True)


@contextlib.contextmanager
def selected_ota(args, parent=None):
    local, url = getattr(args, "ota", None), getattr(args, "ota_url", None)
    require(bool(local) != bool(url), "B requires exactly one --ota or --ota-url")
    expected = getattr(args, "expected_sha256", None)
    if expected:
        require(re.fullmatch("[0-9a-fA-F]{64}", expected), "invalid optional expected SHA256")
    with contextlib.ExitStack() as stack:
        if url:
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=".asp2-download-", dir=parent)))
            folder.chmod(0o700)
            path = folder / "source-ota.zip"
            download(url, path, max_bytes=getattr(args, "download_max_bytes", MAX_BYTES),
                     timeout=getattr(args, "download_timeout", SOCKET_TIMEOUT),
                     total_timeout=getattr(args, "download_total_timeout", TOTAL_TIMEOUT))
        else:
            path = Path(local)
        # Never hash the source unless the owner explicitly requested this comparison.
        if expected:
            require(digest(path).lower() == expected.lower(), "optional expected SHA256 mismatch")
        yield path
