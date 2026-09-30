"""Extrae una oferta pública y la guarda como ofertas/<nombre>/empleo.md."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Reservadas para la futura etapa de extracción/normalización con IA.
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
SCRAPER_MODEL = os.getenv("SCRAPER_MODEL", "")


def normalize_with_scraper_model(data: dict[str, str]) -> dict[str, str]:
    """Limpia y estructura la oferta usando exclusivamente la API del scraper."""
    if not SCRAPER_API_KEY:
        raise RuntimeError("Falta SCRAPER_API_KEY en .env")
    if not SCRAPER_MODEL:
        raise RuntimeError("Falta SCRAPER_MODEL en .env")

    prompt = f"""Organiza esta oferta laboral extraída de Computrabajo.
Devuelve únicamente JSON válido, sin Markdown ni comentarios, con estas claves:
title, company, location, contract, workday, modality, requirements, schedule, benefits, body.
Conserva únicamente información presente en el texto. No inventes datos.

Datos extraídos:
{data}
"""
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{SCRAPER_MODEL}:generateContent",
        params={"key": SCRAPER_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=120,
    )
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        normalized = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("El modelo del scraper no devolvió JSON válido.") from exc
    if not isinstance(normalized, dict) or not normalized.get("title") or not normalized.get("body"):
        raise RuntimeError("El modelo del scraper devolvió una oferta incompleta.")
    return {key: str(normalized.get(key, "")) for key in data}


def clean_text(value: str) -> str:
    """Normaliza espacios sin destruir la separación entre párrafos."""
    lines = []
    for line in value.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n\n".join(lines)


def normalize_job_text(value: str) -> str:
    """Limpia ruido común de páginas de empleo y conserva listas legibles."""
    noise = re.compile(
        r"^(apply now|apply|easy apply|save job|share|sign in|login|register|cookie|accept cookies|"
        r"see more|show more|show less|report job|skip to main content)$",
        re.IGNORECASE,
    )
    normalized = []
    for raw_line in value.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or noise.fullmatch(line):
            continue
        line = re.sub(r"^[•●▪◦]s*", "- ", line)
        if line in normalized:
            continue
        normalized.append(line)

    paragraphs = []
    current = []
    for line in normalized:
        if line.startswith("- "):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(line)
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def scrape_public_page(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        element.decompose()

    title = ""
    title_tag = soup.find("meta", property="og:title") or soup.find("title")
    if title_tag:
        title = title_tag.get("content", "") if title_tag.name == "meta" else title_tag.get_text(" ", strip=True)

    description_tag = soup.find("meta", attrs={"name": "description"})
    description = description_tag.get("content", "") if description_tag else ""
    main = soup.find("main") or soup.find("article") or soup.body
    body = normalize_job_text(main.get_text("\n", strip=True) if main else "")

    return {
        "title": clean_text(title),
        "description": clean_text(description),
        "body": body,
    }


def first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            value = clean_text(element.get_text(" ", strip=True))
            if value:
                return value
    return ""


def scrape_linkedin(url: str) -> dict[str, str]:
    """Extrae campos habituales de una oferta pública de LinkedIn."""
    data = scrape_public_page(url)
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    soup = BeautifulSoup(response.text, "html.parser")
    data["title"] = first_text(soup, [
        "h1.top-card-layout__title",
        "h1.job-details-jobs-unified-top-card__job-title",
        "meta[property='og:title']",
    ]) or data["title"]
    company = first_text(soup, [
        ".topcard__org-name-link",
        ".top-card-layout__card a[data-tracking-control-name='public_jobs_topcard-org-name']",
        ".job-details-jobs-unified-top-card__company-name",
    ])
    location = first_text(soup, [
        ".topcard__flavor--bullet",
        ".top-card-layout__card .topcard__flavor",
        ".job-details-jobs-unified-top-card__bullet",
    ])
    if company or location:
        data["description"] = "\n".join(value for value in [company, location] if value)
    description = first_text(soup, [
        ".description__text",
        ".show-more-less-html__markup",
        ".jobs-description__content",
    ])
    if description:
        data["body"] = normalize_job_text(description)
    return data


def extract_indeed_html(html: str, url: str) -> dict[str, str]:
    """Extrae una oferta de Indeed a partir del HTML ya descargado."""
    soup = BeautifulSoup(html, "html.parser")
    title = first_text(soup, [
        "h1[data-testid='jobsearch-JobInfoHeader-title']",
        "h1.jobsearch-JobInfoHeader-title",
        "h1",
        "meta[property='og:title']",
    ])
    description = first_text(soup, [
        "div#jobDescriptionText",
        "[data-testid='jobDescriptionText']",
        ".jobsearch-jobDescriptionText",
    ])
    company = first_text(soup, [
        "div[data-testid='inlineHeader-companyName']",
        "[data-company-name='true']",
        ".jobsearch-InlineCompanyRating div",
    ])
    location = first_text(soup, [
        "div[data-testid='inlineHeader-companyLocation']",
        "[data-testid='job-location']",
        ".jobsearch-JobInfoHeader-subtitle div",
    ])
    if not title:
        title_tag = soup.find("meta", property="og:title") or soup.find("title")
        if title_tag:
            title = title_tag.get("content", "") if title_tag.name == "meta" else title_tag.get_text(" ", strip=True)
    if not description:
        main = soup.find("main") or soup.find("article") or soup.body
        description = main.get_text("\n", strip=True) if main else ""
    return {
        "title": clean_text(title),
        "description": "\n".join(value for value in [company, location] if value),
        "body": normalize_job_text(description),
        "company": company,
        "location": location,
    }


def scrape_indeed_with_browser(url: str) -> dict[str, str]:
    """Carga Indeed con un navegador normal cuando su endpoint HTTP responde 403."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Indeed bloqueó la descarga HTTP. Instala Playwright para usar el controlador de Indeed.") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_500)
            html = page.content()
            browser.close()
    except Exception as exc:
        raise RuntimeError(f"No se pudo cargar la oferta de Indeed con el navegador: {exc}") from exc

    data = extract_indeed_html(html, url)
    if len(data["body"]) < 100:
        raise RuntimeError("Indeed no entregó el contenido de la oferta; puede requerir verificación o estar bloqueando el acceso.")
    return data


def scrape_indeed(url: str) -> dict[str, str]:
    """Extrae una oferta de Indeed por HTTP y usa navegador como respaldo ante 403."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = extract_indeed_html(response.text, response.url)
        if len(data["body"]) >= 100:
            return data
    except requests.HTTPError as exc:
        if not exc.response or exc.response.status_code != 403:
            raise RuntimeError(f"Indeed no permitió descargar la oferta: {exc}") from exc
        print("Indeed respondió 403; intentando con el controlador de navegador...", flush=True)
    except requests.RequestException as exc:
        print(f"No se pudo descargar Indeed por HTTP ({exc}); intentando con el controlador de navegador...", flush=True)

    return scrape_indeed_with_browser(url)


def scrape_computrabajo(url: str) -> dict[str, str]:
    """Extrae el panel de detalle de una oferta de Computrabajo.

    Computrabajo muestra la oferta seleccionada junto con una grilla de resultados
    y recomendaciones. Por eso esta fuente se procesa con navegador y se recorta
    desde la última aparición del título hasta el bloque de información empresarial.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Computrabajo requiere Playwright. Instala las dependencias del proyecto.") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_500)
            title_candidates = page.locator("h1, h2").all_text_contents()
            body_text = page.locator("body").inner_text()
            browser.close()
    except Exception as exc:
        raise RuntimeError(f"No se pudo cargar la oferta de Computrabajo: {exc}") from exc

    title = next(
        (
            clean_text(value)
            for value in title_candidates
            if value.strip() and "ofertas de trabajo" not in value.lower()
        ),
        "Oferta laboral",
    )
    normalized_body = re.sub(r"\s+", " ", body_text).strip()
    lower_body = normalized_body.lower()
    description_position = lower_body.find("descripción de la oferta")
    if description_position < 0:
        raise RuntimeError("No se encontró el bloque de descripción de la oferta.")

    # El detalle aparece después de la grilla. El último "Resumen" antes de
    # la descripción es una ancla más estable que el título, que también aparece
    # en la tarjeta de resultados.
    summary_position = lower_body.rfind("resumen", 0, description_position)
    if summary_position < 0:
        summary_position = description_position
    normalized_title = re.sub(r"\s+", " ", title).strip()
    title_position = lower_body.rfind(normalized_title.lower(), 0, summary_position)
    detail_start = title_position if title_position >= 0 else summary_position
    detail = normalized_body[detail_start:]
    detail = re.sub(
        r"\s*(Resumen|Descripción de la oferta|¿Cuál será tu reto\?|¿Qué buscamos\?|Ofrecemos|Horario|Beneficios|¿Quieres asumir este reto\?|Requerimientos|Acerca de)\s*",
        r"\n\1\n",
        detail,
        flags=re.IGNORECASE,
    )
    company_marker = re.search(r"\nAcerca de\s+", detail, flags=re.IGNORECASE)
    if company_marker:
        detail = detail[: company_marker.start()]
    detail = normalize_job_text(detail)

    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    company = ""
    location = ""
    for index, line in enumerate(lines[:12]):
        if "Bogotá" in line or "Medellín" in line or "Cali" in line or "Colombia" in line:
            location = line
        if "evaluaciones" not in line.lower() and line != title and index > 0:
            if not company and ("S.A.S" in line or "SAS" in line or "empresa" in line.lower()):
                company = line

    def section_between(start: str, end_markers: list[str]) -> str:
        lower_detail = detail.lower()
        start_index = lower_detail.find(start.lower())
        if start_index < 0:
            return ""
        value = detail[start_index + len(start):]
        lower_value = value.lower()
        end_indexes = [lower_value.find(marker.lower()) for marker in end_markers]
        end_indexes = [index for index in end_indexes if index >= 0]
        if end_indexes:
            value = value[: min(end_indexes)]
        return value.strip()

    summary_lines = detail.split("Resumen", 1)[1].split("Descripción de la oferta", 1)[0] if "Resumen" in detail else ""
    contract = "Contrato a término indefinido" if "Contrato a término indefinido" in summary_lines else ""
    workday = "Tiempo Completo" if "Tiempo Completo" in summary_lines else ""
    modality = "Presencial" if "Presencial" in summary_lines else ("Remoto" if "Remoto" in summary_lines else "")
    requirements = section_between("¿Qué buscamos?", ["Ofrecemos", "Horario", "Beneficios"])
    schedule = section_between("Horario", ["Beneficios", "¿Quieres asumir este reto?", "Requerimientos"])
    benefits = section_between("Beneficios", ["¿Quieres asumir este reto?", "Requerimientos"])
    requirements_list = section_between("Requerimientos", ["Imprimir", "Denunciar empleo"])
    description = detail
    if "Descripción de la oferta" in detail:
        description = detail.split("Descripción de la oferta", 1)[1].strip()
    data = {
        "title": title,
        "description": "\n".join(value for value in [company, location] if value),
        "body": description,
        "company": company,
        "location": location,
        "contract": contract,
        "workday": workday,
        "modality": modality,
        "requirements": requirements,
        "schedule": schedule,
        "benefits": benefits,
        "requirements_list": requirements_list,
    }
    if len(data["body"]) < 100:
        raise RuntimeError("Computrabajo no devolvió suficiente contenido en el panel de detalle.")
    print(f"Normalizando oferta con el modelo del scraper ({SCRAPER_MODEL})...", flush=True)
    normalized = normalize_with_scraper_model(data)
    print("Modelo del scraper finalizado correctamente.", flush=True)
    return normalized


def scrape_with_browser(url: str) -> dict[str, str]:
    """Carga la página con Chromium para sitios cuyo contenido depende de JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("La página requiere navegador. Instala Playwright con 'pip install -r requirements.txt'.") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2_000)
            html = page.content()
            browser.close()
    except Exception as exc:
        raise RuntimeError(f"No se pudo cargar la oferta con el navegador: {exc}") from exc

    soup = BeautifulSoup(html, "html.parser")
    title = first_text(soup, ["h1", "meta[property='og:title']"])
    main = soup.find("main") or soup.find("article") or soup.body
    body = normalize_job_text(main.get_text("\n", strip=True) if main else "")
    return {"title": title, "description": "", "body": body}


def scrape_job(url: str, use_browser: bool = False) -> dict[str, str]:
    host = urlparse(url).netloc.lower()
    if "computrabajo.com" in host:
        print("Usando adaptador de Computrabajo...")
        data = scrape_computrabajo(url)
    elif "linkedin.com" in host:
        print("Usando adaptador de LinkedIn...")
        data = scrape_linkedin(url)
    elif "indeed.com" in host:
        print("Usando adaptador de Indeed...")
        data = scrape_indeed(url)
    else:
        print("Usando extractor genérico...")
        data = scrape_public_page(url)
    if use_browser or len(data["body"]) < 100:
        print("Contenido insuficiente; intentando con navegador...")
        browser_data = scrape_with_browser(url)
        if len(browser_data["body"]) > len(data["body"]):
            data = browser_data
    return data


def build_markdown(url: str, data: dict[str, str]) -> str:
    title = data["title"] or "Oferta laboral"
    description = data["description"]
    body = data["body"]
    sections = [f"# {title}"]
    if description:
        sections.append(f"## Resumen\n\n{description}")
    structured_fields = [
        ("Empresa", data.get("company", "")),
        ("Ubicación", data.get("location", "")),
        ("Contrato", data.get("contract", "")),
        ("Jornada", data.get("workday", "")),
        ("Modalidad", data.get("modality", "")),
    ]
    structured_fields = [(label, value) for label, value in structured_fields if value]
    if structured_fields:
        sections.append("## Información principal\n\n" + "\n".join(f"- **{label}:** {value}" for label, value in structured_fields))
    for heading, key in [
        ("Requisitos técnicos", "requirements"),
        ("Horario", "schedule"),
        ("Beneficios", "benefits"),
        ("Requerimientos", "requirements_list"),
    ]:
        if data.get(key):
            sections.append(f"## {heading}\n\n{data[key]}")
    sections.append(f"## Texto extraído de la oferta\n\n{body}")
    sections.append(f"## Fuente\n\n{url}")
    return "\n\n".join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL pública de la oferta laboral")
    parser.add_argument("--name", required=True, help="Nombre de la carpeta de salida, por ejemplo publicis")
    parser.add_argument("--date", dest="offer_date", help="Fecha en formato DD-MM-YYYY; por defecto usa la fecha actual")
    parser.add_argument("--browser", action="store_true", help="Usa Chromium para páginas dinámicas")
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("La URL debe comenzar por http:// o https://")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        raise ValueError("El nombre solo puede contener letras, números, guiones y guiones bajos.")
    if args.offer_date:
        try:
            offer_date = datetime.strptime(args.offer_date, "%d-%m-%Y").date()
        except ValueError as exc:
            raise ValueError("La fecha debe tener formato DD-MM-YYYY, por ejemplo 30-09-2026.") from exc
    else:
        offer_date = date.today()

    project_root = Path(__file__).parent
    date_dir = offer_date.strftime("%d-%m-%Y")
    output_dir = project_root / "ofertas" / date_dir / args.name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "empleo.md"

    print(f"Extrayendo oferta desde {parsed.netloc}...")
    data = scrape_job(args.url, use_browser=args.browser)
    if len(data["body"]) < 100:
        raise RuntimeError("La página no contiene suficiente texto público para construir empleo.md.")
    output_path.write_text(build_markdown(args.url, data), encoding="utf-8")
    print(f"Oferta guardada en: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.RequestException as exc:
        print(f"Error al descargar la página: {exc}")
        raise SystemExit(1)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
