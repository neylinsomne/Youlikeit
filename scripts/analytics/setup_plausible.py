"""
setup_plausible — verificación de pre-condiciones del stack Plausible.

NO levanta Docker por ti (eso lo hace `docker compose -f
docker-compose.plausible.yml up -d`); chequea que todo lo necesario esté
en su sitio y reporta un checklist accionable.

Comprueba:
  1. docker-compose.plausible.yml existe.
  2. .env.plausible existe y tiene SECRET_KEY_BASE no-placeholder.
  3. Configs de Clickhouse presentes.
  4. (si --health) Plausible responde en /api/health.

Uso:
  python scripts/analytics/setup_plausible.py
  python scripts/analytics/setup_plausible.py --health   # además pega a /api/health
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _check(label: str, ok: bool, hint: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"  [{mark}] {label}")
    if not ok and hint:
        print(f"        ↳ {hint}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--health", action="store_true",
                    help="Además verifica /api/health del Plausible vivo")
    args = ap.parse_args()

    print("═" * 60)
    print("  SETUP PLAUSIBLE · checklist de pre-condiciones")
    print("═" * 60)

    results = []

    compose = ROOT / "docker-compose.plausible.yml"
    results.append(_check("docker-compose.plausible.yml existe", compose.exists(),
                          "falta el stack; ver infra/plausible/README.md"))

    env = ROOT / ".env.plausible"
    env_ok = env.exists()
    results.append(_check(".env.plausible existe", env_ok,
                          "cp .env.plausible.example .env.plausible y rellenar"))

    secret_ok = False
    if env_ok:
        txt = env.read_text(encoding="utf-8", errors="ignore")
        secret_ok = "SECRET_KEY_BASE=" in txt and "__CHANGE_ME__" not in txt
    results.append(_check("SECRET_KEY_BASE configurado (no placeholder)", secret_ok,
                          "generar: python -c \"import secrets,base64; "
                          "print(base64.b64encode(secrets.token_bytes(48)).decode())\""))

    ch_cfg = ROOT / "infra" / "plausible" / "clickhouse" / "config.xml"
    ch_usr = ROOT / "infra" / "plausible" / "clickhouse" / "user-config.xml"
    results.append(_check("Configs de Clickhouse presentes", ch_cfg.exists() and ch_usr.exists()))

    api_key = bool(os.getenv("PLAUSIBLE_API_KEY"))
    _check("PLAUSIBLE_API_KEY en entorno (para Stats API)", api_key,
           "se genera DESPUÉS del primer arranque, en el panel")

    if args.health:
        try:
            from apps.analytics.plausible_client import health_check, _base_url
            ok = health_check()
            _check(f"/api/health en {_base_url()}", ok,
                   "docker compose -f docker-compose.plausible.yml up -d")
        except Exception as e:
            _check("/api/health", False, str(e))

    print("═" * 60)
    hard_ok = all(results)
    print(f"  {'LISTO para levantar' if hard_ok else 'FALTAN pasos (ver ✗ arriba)'}")
    print("═" * 60)
    return 0 if hard_ok else 1


if __name__ == "__main__":
    sys.exit(main())
