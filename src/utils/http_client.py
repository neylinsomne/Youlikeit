"""Shared HTTP client with retry, session pooling, and rate limit handling.

Usage:
    from utils.http_client import api_get, api_post, get_session

    # Simple GET with retry + backoff
    data = api_get("https://api.example.com/data", params={"q": "test"})

    # POST with retry
    data = api_post("https://api.example.com/submit", json={"key": "val"})

    # Reuse session for multiple calls to same host
    session = get_session("tmdb")
    resp = session.get("https://api.themoviedb.org/3/movie/550")
"""

import logging
import time
from threading import Lock

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session pool (one per host/service)
# ---------------------------------------------------------------------------

_sessions: dict[str, requests.Session] = {}
_sessions_lock = Lock()


def get_session(name: str = "default", max_retries: int = 3) -> requests.Session:
    """Get or create a named session with connection pooling and retry adapter.

    Sessions are reused across calls to the same service, keeping TCP
    connections alive and reducing latency.
    """
    with _sessions_lock:
        if name not in _sessions:
            session = requests.Session()
            retry_strategy = Retry(
                total=max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"],
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,
                pool_maxsize=20,
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({
                "User-Agent": "YouLikeIt-Pipeline/1.0",
            })
            _sessions[name] = session
        return _sessions[name]


# ---------------------------------------------------------------------------
# Rate limit tracking
# ---------------------------------------------------------------------------

_rate_limits: dict[str, float] = {}
_rate_lock = Lock()


def _check_rate_limit(service: str, min_interval: float = 0.0):
    """Enforce minimum interval between calls to the same service."""
    if min_interval <= 0:
        return
    with _rate_lock:
        last_call = _rate_limits.get(service, 0)
        elapsed = time.time() - last_call
        if elapsed < min_interval:
            wait = min_interval - elapsed
            time.sleep(wait)
        _rate_limits[service] = time.time()


def _handle_rate_limit_headers(resp: requests.Response, service: str):
    """Check response headers for rate limit info and wait if needed."""
    remaining = resp.headers.get("X-RateLimit-Remaining")
    retry_after = resp.headers.get("Retry-After")

    if retry_after:
        try:
            wait = float(retry_after)
            log.warning(f"[{service}] Rate limited. Waiting {wait:.0f}s (Retry-After header)")
            time.sleep(wait)
        except ValueError:
            pass

    if remaining is not None:
        try:
            rem = int(remaining)
            if rem <= 2:
                reset = resp.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, float(reset) - time.time())
                    if wait > 0 and wait < 300:
                        log.warning(f"[{service}] Rate limit low ({rem} left). Waiting {wait:.0f}s")
                        time.sleep(wait)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# High-level API functions
# ---------------------------------------------------------------------------

# Known service rate limits (seconds between calls)
SERVICE_RATE_LIMITS = {
    "jikan": 0.4,       # 3 req/s
    "anilist": 0.2,
    "animechan": 0.5,
    "opensubtitles": 0.25,  # 40 req/10s
    "tmdb": 0.05,       # generous limit
    "omdb": 0.1,
    "trakt": 0.05,
    "gemini": 6.0,      # 10 req/min
    "groq": 2.0,        # 30 req/min
    "pytrends": 2.0,
    "fandom": 0.3,
    "youtube": 0.1,
}


def _detect_service(url: str) -> str:
    """Detect which service a URL belongs to for rate limiting."""
    url_lower = url.lower()
    for service in SERVICE_RATE_LIMITS:
        if service in url_lower:
            return service
    if "jikan.moe" in url_lower:
        return "jikan"
    if "graphql.anilist" in url_lower:
        return "anilist"
    if "generativelanguage.googleapis" in url_lower:
        return "gemini"
    if "googleapis.com/youtube" in url_lower:
        return "youtube"
    if "fandom.com" in url_lower:
        return "fandom"
    return "default"


def api_get(
    url: str,
    params: dict = None,
    timeout: int = 15,
    service: str = "",
    max_retries: int = 3,
    **kwargs,
) -> dict | list | None:
    """GET request with retry, rate limiting, and session pooling.

    Returns parsed JSON or None on failure.
    """
    svc = service or _detect_service(url)
    session = get_session(svc, max_retries)

    min_interval = SERVICE_RATE_LIMITS.get(svc, 0)
    _check_rate_limit(svc, min_interval)

    try:
        resp = session.get(url, params=params, timeout=timeout, **kwargs)
        _handle_rate_limit_headers(resp, svc)

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 5))
            log.warning(f"[{svc}] 429 rate limited. Waiting {retry_after}s")
            time.sleep(retry_after)
            resp = session.get(url, params=params, timeout=timeout, **kwargs)

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        return resp.text if resp else None
    except requests.exceptions.RequestException as e:
        log.warning(f"[{svc}] GET {url[:80]} failed: {e}")
        return None


def api_post(
    url: str,
    json: dict = None,
    data=None,
    timeout: int = 20,
    service: str = "",
    max_retries: int = 3,
    **kwargs,
) -> dict | list | None:
    """POST request with retry, rate limiting, and session pooling."""
    svc = service or _detect_service(url)
    session = get_session(svc, max_retries)

    min_interval = SERVICE_RATE_LIMITS.get(svc, 0)
    _check_rate_limit(svc, min_interval)

    try:
        resp = session.post(url, json=json, data=data, timeout=timeout, **kwargs)
        _handle_rate_limit_headers(resp, svc)

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 5))
            log.warning(f"[{svc}] 429 rate limited. Waiting {retry_after}s")
            time.sleep(retry_after)
            resp = session.post(url, json=json, data=data, timeout=timeout, **kwargs)

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        return resp.text if resp else None
    except requests.exceptions.RequestException as e:
        log.warning(f"[{svc}] POST {url[:80]} failed: {e}")
        return None


def download_file(
    url: str,
    output_path: str,
    timeout: int = 30,
    service: str = "",
) -> bool:
    """Download a file with streaming and retry."""
    svc = service or _detect_service(url)
    session = get_session(svc)

    try:
        resp = session.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        log.warning(f"[{svc}] Download {url[:60]} failed: {e}")
        return False
