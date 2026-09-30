"""Punto único de entrada para scraping y generación de CV."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")


def validate_arguments(url: str, name: str, offer_date: str | None) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("La URL debe comenzar por http:// o https://")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(
            "El nombre solo puede contener letras, números, guiones y guiones bajos."
        )
    if offer_date:
        try:
            datetime.strptime(offer_date, "%d-%m-%Y")
        except ValueError as exc:
            raise ValueError(
                "La fecha debe tener formato DD-MM-YYYY, por ejemplo 30-09-2026."
            ) from exc


def run_scraper(url: str, name: str, offer_date: str | None, use_browser: bool) -> Path:
    command = [sys.executable, str(PROJECT_ROOT / "scrape_job.py"), url, "--name", name]
    if offer_date:
        command.extend(["--date", offer_date])
    if use_browser:
        command.append("--browser")

    print("Paso 1/2: extrayendo y validando la oferta...")
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError("El scraping terminó con errores; el pipeline se detuvo.")

    folder_date = offer_date or date.today().strftime("%d-%m-%Y")
    job_path = PROJECT_ROOT / "ofertas" / folder_date / name / "empleo.md"
    if not job_path.exists():
        raise RuntimeError(f"El scraper terminó sin crear el archivo esperado: {job_path}")
    if len(job_path.read_text(encoding="utf-8").strip()) < 100:
        raise RuntimeError(f"El archivo generado está vacío o es insuficiente: {job_path}")
    return job_path


def validate_generated_artifacts(offer_folder: Path, mode: str) -> Path:
    output_folder = offer_folder / "data"
    content_path = output_folder / "contenido_adaptado.json"
    tex_path = output_folder / "cv_carlos_urresty.tex"

    if not content_path.exists():
        raise RuntimeError(f"No se generó el JSON adaptado: {content_path}")
    try:
        content = json.loads(content_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"El JSON generado no es válido: {exc.msg}") from exc
    if not isinstance(content, dict) or not content.get("nombre") or not content.get("perfil"):
        raise RuntimeError("El JSON generado no contiene los campos mínimos del CV.")

    if not tex_path.exists() or tex_path.stat().st_size < 100:
        raise RuntimeError(f"No se generó un archivo LaTeX válido: {tex_path}")
    tex = tex_path.read_text(encoding="utf-8")
    if "\\documentclass" not in tex or "\\end{document}" not in tex:
        raise RuntimeError("El archivo LaTeX generado está incompleto.")

    if mode == "full":
        pdf_path = offer_folder / "cv_carlos_urresty.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size < 100:
            raise RuntimeError(f"No se generó un PDF válido: {pdf_path}")
        return pdf_path
    return tex_path


def run_cv_compiler(job_path: Path, provider: str, generate_only: bool, dry_run: bool) -> Path | None:
    offer_folder = job_path.parent
    if dry_run and generate_only:
        raise ValueError("--dry-run y --generate-only no se pueden usar al mismo tiempo.")
    command = [sys.executable, str(PROJECT_ROOT / "cv_compiler.py"), str(offer_folder), "--provider", provider]
    if generate_only:
        command.append("--generate-only")
    if dry_run:
        command.append("--dry-run")

    print("Paso 2/2: generando el CV adaptado...")
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError("La generación del CV terminó con errores.")

    if dry_run:
        request_path = offer_folder / "data" / "solicitud_generacion.txt"
        if not request_path.exists():
            raise RuntimeError("La solicitud de generación no fue creada.")
        return None
    return validate_generated_artifacts(offer_folder, "tex" if generate_only else "full")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL pública de la oferta laboral")
    parser.add_argument("--name", required=True, help="Nombre de la empresa/carpeta")
    parser.add_argument("--date", dest="offer_date", help="Fecha DD-MM-YYYY")
    parser.add_argument("--browser", action="store_true", help="Usa Chromium para páginas dinámicas")
    parser.add_argument("--provider", choices=["deepseek", "gemini"], default=None)
    parser.add_argument("--generate-only", action="store_true", help="Genera JSON y LaTeX sin compilar el PDF")
    parser.add_argument("--dry-run", action="store_true", help="Prepara la solicitud sin llamar al proveedor de IA")
    args = parser.parse_args()

    validate_arguments(args.url, args.name, args.offer_date)
    job_path = run_scraper(args.url, args.name, args.offer_date, args.browser)
    print(f"Scraping completado correctamente: {job_path.resolve()}")
    provider = args.provider or os.getenv("LLM_PROVIDER", "deepseek")
    result_path = run_cv_compiler(job_path, provider, args.generate_only, args.dry_run)
    if result_path:
        print(f"Pipeline completado correctamente: {result_path.resolve()}")
    else:
        print("Pipeline completado correctamente: solicitud de generación preparada.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
