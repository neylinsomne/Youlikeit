"""
ex34 - Gestor unificado de OAuth para YouTube APIs.

Maneja autenticación OAuth 2.0 para múltiples scopes de YouTube:
  - youtube.upload (ex12)
  - yt-analytics.readonly (ex24, ex26)
  - yt-analytics-monetary.readonly (futuro)

Un solo archivo de token con todos los scopes. Si un ejercicio
necesita un scope nuevo, se solicita incremental consent.

También puede usarse como ejercicio para verificar que OAuth funciona:
  python src/main.py ex34 --check
    python src/main.py ex34 --check --persona deep_mind

Uso como módulo:
  from exercises.ex34_oauth_manager import get_youtube_service, get_analytics_service
"""

from __future__ import annotations

import os
from pathlib import Path

from common.config import Settings
from common.logger import build_logger


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPE_ANALYTICS_MONETARY = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"

# Default scopes: upload + analytics read
DEFAULT_SCOPES = [SCOPE_UPLOAD, SCOPE_READONLY, SCOPE_ANALYTICS]


# ---------------------------------------------------------------------------
# Client secrets discovery
# ---------------------------------------------------------------------------

def find_client_secrets() -> Path | None:
    """Look for Google OAuth client_secrets.json in common locations."""
    candidates = [
        Path("client_secrets.json"),
        Path("client_secret.json"),
        Path(os.getenv("GOOGLE_CLIENT_SECRETS", "client_secrets.json")),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _get_token_path(secrets_path: Path, persona: str = "") -> Path:
    """Token file per persona. Falls back to default if no persona."""
    if persona:
        tokens_dir = Path("tokens")
        tokens_dir.mkdir(exist_ok=True)
        return tokens_dir / f"youtube_{persona}.json"
    return secrets_path.parent / "youtube_oauth_token.json"


def _load_credentials(token_path: Path, scopes: list[str]):
    """Load existing credentials from token file."""
    try:
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None

    if not token_path.exists():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        return creds
    except Exception:
        return None


def _has_all_scopes(creds, required_scopes: list[str]) -> bool:
    """Check if credentials have all required scopes."""
    if not creds or not hasattr(creds, "scopes") or not creds.scopes:
        return False
    return all(s in creds.scopes for s in required_scopes)


def authenticate(
    secrets_path: Path | None = None,
    scopes: list[str] | None = None,
    log=None,
    persona: str = "",
):
    """
    Authenticate with Google OAuth 2.0.

    Handles:
      - Loading cached token
      - Refreshing expired token
      - Requesting new token (opens browser)
      - Incremental scope expansion

    Returns authenticated credentials or None.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        if log:
            log.error(
                "Google API libraries not installed. Run:\n"
                "  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )
        return None

    if not secrets_path:
        secrets_path = find_client_secrets()
    if not secrets_path:
        if log:
            log.error("client_secrets.json not found. See SETUP_CUENTAS.md")
        return None

    scopes = scopes or DEFAULT_SCOPES
    token_path = _get_token_path(secrets_path, persona)

    # Try loading existing token
    creds = _load_credentials(token_path, scopes)

    # Check if we need to re-authenticate for new scopes
    needs_reauth = False
    if creds and creds.valid and not _has_all_scopes(creds, scopes):
        if log:
            log.info("Existing token missing scopes. Requesting incremental consent.")
        needs_reauth = True

    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                if log:
                    log.info("Token refreshed.")
            except Exception as e:
                if log:
                    log.warning("Token refresh failed: %s. Re-authenticating.", e)
                needs_reauth = True
        else:
            needs_reauth = True

    if not creds or not creds.valid or needs_reauth:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        if log:
            log.info("New OAuth token saved with scopes: %s", scopes)

    return creds


# ---------------------------------------------------------------------------
# Service builders
# ---------------------------------------------------------------------------

def get_youtube_service(secrets_path: Path | None = None, log=None, persona: str = ""):
    """Get authenticated YouTube Data API v3 service. Persona selects which channel token to use."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        if log:
            log.error("google-api-python-client not installed.")
        return None

    creds = authenticate(
        secrets_path=secrets_path,
        persona=persona,
        scopes=[SCOPE_UPLOAD, SCOPE_READONLY],
        log=log,
    )
    if not creds:
        return None

    return build("youtube", "v3", credentials=creds)


def get_analytics_service(secrets_path: Path | None = None, log=None):
    """Get authenticated YouTube Analytics API service."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        if log:
            log.error("google-api-python-client not installed.")
        return None

    creds = authenticate(
        secrets_path=secrets_path,
        scopes=[SCOPE_READONLY, SCOPE_ANALYTICS],
        log=log,
    )
    if not creds:
        return None

    return build("youtubeAnalytics", "v2", credentials=creds)


def get_both_services(secrets_path: Path | None = None, log=None) -> tuple:
    """Get both YouTube Data and Analytics services with a single token."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        if log:
            log.error("google-api-python-client not installed.")
        return None, None

    creds = authenticate(
        secrets_path=secrets_path,
        scopes=DEFAULT_SCOPES,
        log=log,
    )
    if not creds:
        return None, None

    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    return youtube, analytics


# ---------------------------------------------------------------------------
# Entry point (for verification)
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    check: bool = True,
    persona: str = "",
) -> Path:
    """Verify OAuth setup and list available scopes."""
    log = build_logger("ex34", settings.output_dir / "logs" / "ex34.log")
    report_lines = ["ex34 - OAuth Manager Report", "=" * 50, ""]

    # 1. Find client secrets
    secrets = find_client_secrets()
    if secrets:
        report_lines.append(f"Client secrets: {secrets}")
        log.info("Client secrets found: %s", secrets)
    else:
        report_lines.append("Client secrets: NOT FOUND")
        report_lines.append("")
        report_lines.append("Setup:")
        report_lines.append("  1. Go to https://console.cloud.google.com")
        report_lines.append("  2. Enable YouTube Data API v3 AND YouTube Analytics API")
        report_lines.append("  3. Create OAuth 2.0 credentials (Desktop app)")
        report_lines.append("  4. Download as client_secrets.json in project root")
        log.error("No client_secrets.json found")

        report_path = settings.output_dir / "logs" / "ex34_oauth_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        return report_path

    # 2. Check existing token
    token_path = _get_token_path(secrets, persona)
    if persona:
        report_lines.append(f"Persona: {persona}")

    if check:
        report_lines.append("")
        report_lines.append("OAuth check: running authentication flow...")
        creds_check = authenticate(
            secrets_path=secrets,
            scopes=DEFAULT_SCOPES,
            log=log,
            persona=persona,
        )
        if creds_check and getattr(creds_check, "valid", False):
            report_lines.append("OAuth check: OK")
        else:
            report_lines.append("OAuth check: FAILED")

    if token_path.exists():
        report_lines.append(f"Token file: {token_path} (exists)")

        creds = _load_credentials(token_path, DEFAULT_SCOPES)
        if creds:
            report_lines.append(f"Token valid: {creds.valid}")
            report_lines.append(f"Token expired: {creds.expired if hasattr(creds, 'expired') else 'unknown'}")
            report_lines.append(f"Scopes: {creds.scopes if hasattr(creds, 'scopes') else 'unknown'}")

            # Check which scopes we have
            for scope in DEFAULT_SCOPES:
                has = scope in (creds.scopes or []) if hasattr(creds, 'scopes') and creds.scopes else False
                icon = "+" if has else "-"
                report_lines.append(f"  [{icon}] {scope}")
        else:
            report_lines.append("Token file exists but could not load credentials")
    else:
        report_lines.append(f"Token file: {token_path} (not created yet)")
        report_lines.append("Run ex34 --check, ex12 or ex24 to trigger OAuth consent flow")

    # 3. Check if Google API libraries are installed
    try:
        import googleapiclient  # noqa: F401
        report_lines.append("")
        report_lines.append("Google API libraries: INSTALLED")
    except ImportError:
        report_lines.append("")
        report_lines.append("Google API libraries: NOT INSTALLED")
        report_lines.append("  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")

    report_path = settings.output_dir / "logs" / "ex34_oauth_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info("OAuth report saved to %s", report_path)
    return report_path
