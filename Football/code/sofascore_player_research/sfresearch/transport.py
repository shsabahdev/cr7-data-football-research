"""HTTP transport.

Sofascore blocks plain HTTP clients at the TLS-fingerprint level, so the real
transport uses curl_cffi to present a Chrome fingerprint (the same approach as
pysofascore / scrapling). Tests inject a fake transport instead.
"""
from __future__ import annotations

from typing import Protocol

BASE = "https://api.sofascore.com/api/v1"


class Transport(Protocol):
    def get(self, path: str) -> tuple[int, dict | None]:
        """Return (http_status, parsed_json_or_None). Status 0 = network error."""


class CurlTransport:
    """Fast, no browser. Try other fingerprints with --impersonate if blocked."""

    def __init__(self, impersonate: str = "chrome", timeout: int = 30):
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "Missing dependency. Run: pip install -r requirements.txt"
            ) from exc
        self.last_detail = ""
        self._session = curl_requests.Session(impersonate=impersonate, timeout=timeout)

    def get(self, path: str) -> tuple[int, dict | None]:
        try:
            resp = self._session.get(
                BASE + path,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://www.sofascore.com/",
                },
            )
        except Exception as exc:
            self.last_detail = f"network error: {exc}"[:300]
            return 0, None
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code != 200:
            h = resp.headers
            self.last_detail = (
                f"server={h.get('server')} cf-mitigated={h.get('cf-mitigated')} "
                f"body={resp.text[:200]!r}"
            )
        return resp.status_code, data


class PlaywrightTransport:
    """Real Chromium. Slower, but passes browser checks plain HTTP clients fail.

    Requests are made with fetch() inside a page on www.sofascore.com, so they
    carry the browser's own TLS fingerprint and cookies. Visible by default
    (headless browsers are detected more often).
    """

    def __init__(self, headless: bool = False, timeout_ms: int = 45000):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "Run: pip install playwright && python -m playwright install chromium"
            ) from exc
        self.last_detail = ""
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._page = self._browser.new_page()
        self._page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=timeout_ms)
        self._page.wait_for_timeout(4000)  # let any browser check finish

    def get(self, path: str) -> tuple[int, dict | None]:
        import json

        try:
            result = self._page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {headers: {'Accept': 'application/json'}});
                    return {status: r.status, text: await r.text()};
                }""",
                BASE + path,
            )
        except Exception as exc:
            self.last_detail = f"browser error: {exc}"[:300]
            return 0, None
        status, text = result["status"], result["text"]
        if status != 200:
            self.last_detail = f"body={text[:200]!r}"
        try:
            data = json.loads(text)
        except Exception:
            data = None
        return status, data

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()
