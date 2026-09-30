"""Valida la extracción de una oferta sin crear archivos ni generar el CV."""
from __future__ import annotations

import argparse
import sys

from scrape_job import scrape_job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL pública de la oferta")
    parser.add_argument("--browser", action="store_true", help="Fuerza el uso de navegador")
    args = parser.parse_args()

    data = scrape_job(args.url, use_browser=args.browser)
    errors = []
    if not data.get("title", "").strip():
        errors.append("falta el título")
    if len(data.get("body", "").strip()) < 100:
        errors.append("la descripción tiene menos de 100 caracteres")
    if not data.get("description", "").strip():
        errors.append("faltan empresa y/o ubicación")

    if errors:
        print("Validación fallida:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Validación correcta")
    print(f"Título: {data['title']}")
    print(f"Resumen: {data['description']}")
    print(f"Caracteres extraídos: {len(data['body'])}")
    for key in ["contract", "workday", "modality", "requirements", "schedule", "benefits"]:
        if data.get(key):
            print(f"{key}: detectado")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
