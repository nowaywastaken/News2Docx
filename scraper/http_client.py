"""Light‑weight HTTP client used by the scraping package."""
from __future__ import annotations
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HttpClient:
    """Simple wrapper around :mod:`requests` with retry support."""

    def __init__(self, retries: int = 3, backoff_factor: float = 0.5) -> None:
        retry = Retry(total=retries, backoff_factor=backoff_factor, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get(self, url: str, timeout: int = 30) -> Optional[str]:
        """Fetch *url* and return the response text or ``None`` on failure."""
        try:
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None
