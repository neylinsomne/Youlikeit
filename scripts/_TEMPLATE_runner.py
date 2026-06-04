"""Plantilla de runner · clónala a scripts/<dominio>/<accion>.py

Reglas:
- Un runner es DELGADO: parsea args y delega en src/apps/<dominio>/. Cero lógica
  de negocio aquí (esa vive en apps/, testeada en tests/<dominio>/).
- Imports limpios `from apps.<dominio>.<modulo> import …` — el paquete está
  instalado editable (`pip install -e .`), no se usa `sys.path.insert`.
- Para que aparezca en `ylk`, agregá un comando en src/cli/commands/<dominio>.py
  que haga passthrough a este script (ver los existentes).
- Dependencias nuevas → requirements.txt + `docker compose build` (nunca pip suelto).
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    # Consolas Windows (cp1252): forzar UTF-8 en stdout.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="<qué hace este runner>")
    ap.add_argument("--example", default="", help="<flag de ejemplo>")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    args = ap.parse_args()

    # Delegá en la lógica del dominio:
    #   from apps.<dominio>.<modulo> import do_work
    #   result = do_work(example=args.example)
    #   print(json.dumps(result) if args.json else result)
    raise NotImplementedError("Implementá llamando a src/apps/<dominio>/")


if __name__ == "__main__":
    sys.exit(main())
