"""Genera y compila un CV LaTeX adaptado a una oferta de empleo."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


def clean_latex(text: str) -> str:
    """Quita fences Markdown y texto accidental antes/después del documento."""
    text = re.sub(r"^\s*```(?:latex|tex)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("\\documentclass")
    end = text.rfind("\\end{document}")
    if start == -1 or end == -1:
        raise ValueError("La respuesta no contiene un documento LaTeX completo.")
    document = text[start : end + len("\\end{document}")]
    # Algunos modelos usan comandos de viñeta no disponibles en pdflatex básico.
    document = document.replace(r"\square", r"\textbullet")
    # En texto normal, '&' debe escaparse en LaTeX. Evitamos tocar los ya escapados.
    document = re.sub(r"(?<!\\)&", r"\\&", document)
    return document + "\n"


def parse_content_json(text: str) -> dict:
    """Extrae y valida el contenido estructurado devuelto por el proveedor."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        content = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini no devolvió JSON válido: {exc.msg} (línea {exc.lineno})") from exc

    if not isinstance(content, dict):
        raise ValueError("La respuesta de Gemini debe ser un objeto JSON.")

    required_strings = ["nombre", "cargo", "perfil"]
    for field in required_strings:
        if not isinstance(content.get(field), str):
            raise ValueError(f"El campo '{field}' debe ser una cadena de texto.")

    contact = content.get("contacto")
    if not isinstance(contact, dict):
        raise ValueError("El campo 'contacto' debe ser un objeto JSON.")
    for field in ["telefono", "correo", "sitio_web", "ubicacion"]:
        if not isinstance(contact.get(field), str):
            raise ValueError(f"El campo 'contacto.{field}' debe ser una cadena de texto.")

    list_fields = ["experiencia", "educacion", "habilidades", "idiomas", "certificaciones"]
    for field in list_fields:
        if not isinstance(content.get(field), list):
            raise ValueError(f"El campo '{field}' debe ser una lista.")

    for index, entry in enumerate(content["experiencia"], start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"experiencia[{index}] debe ser un objeto.")
        for field in ["cargo", "empresa", "fechas", "ubicacion"]:
            if not isinstance(entry.get(field), str):
                raise ValueError(f"El campo 'experiencia[{index}].{field}' debe ser texto.")
        if not isinstance(entry.get("logros"), list) or not all(isinstance(item, str) for item in entry["logros"]):
            raise ValueError(f"El campo 'experiencia[{index}].logros' debe ser una lista de textos.")

    for index, entry in enumerate(content["educacion"], start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"educacion[{index}] debe ser un objeto.")
        for field in ["titulo", "institucion", "fecha"]:
            if not isinstance(entry.get(field), str):
                raise ValueError(f"El campo 'educacion[{index}].{field}' debe ser texto.")

    for index, entry in enumerate(content["habilidades"], start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"habilidades[{index}] debe ser un objeto.")
        for field in ["categoria", "items"]:
            if not isinstance(entry.get(field), str):
                raise ValueError(f"El campo 'habilidades[{index}].{field}' debe ser texto.")

    for field in ["idiomas", "certificaciones"]:
        if not all(isinstance(item, str) for item in content[field]):
            raise ValueError(f"Todos los elementos de '{field}' deben ser texto.")

    return content


def latex_escape(value: str) -> str:
    """Escapa texto dinámico para que pueda insertarse de forma segura en LaTeX."""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in value)


def render_content(template: str, content: dict) -> str:
    """Rellena la plantilla fija con contenido ya validado y escapado."""
    contact = content["contacto"]

    experience_parts = []
    for entry in content["experiencia"]:
        bullets = "\n".join(f"  \\item {latex_escape(item)}" for item in entry["logros"])
        bullets_block = f"\\begin{{itemize}}\n{bullets}\n\\end{{itemize}}" if bullets else ""
        experience_parts.append(
            "\\cventry{" + latex_escape(entry["cargo"]) + "}{" +
            latex_escape(entry["fechas"]) + "}{" +
            latex_escape(entry["empresa"]) + "}{" +
            latex_escape(entry["ubicacion"]) + "}{" + bullets_block + "}"
        )

    education = "\n".join(
        "\\cveducation{" + latex_escape(entry["titulo"]) + "}{" +
        latex_escape(entry["institucion"]) + "}{" +
        latex_escape(entry["fecha"]) + "}"
        for entry in content["educacion"]
    )

    skills = "\n".join(
        "\\textbf{" + latex_escape(entry["categoria"]) + ":} " + latex_escape(entry["items"]) + "\\par"
        for entry in content["habilidades"]
    )

    languages = "\n".join(
        f"\\textbullet\\ {latex_escape(item)}\\par" for item in content["idiomas"]
    )
    certifications = "\n".join(
        f"\\textbullet\\ {latex_escape(item)}\\par" for item in content["certificaciones"]
    )

    replacements = {
        "ZZNOMBREZZ": latex_escape(content["nombre"]),
        "ZZCARGOZZ": latex_escape(content["cargo"]),
        "ZZTELEFONOZZ": latex_escape(contact["telefono"]),
        "ZZCORREOZZ": latex_escape(contact["correo"]),
        "ZZSITIOWEBZZ": latex_escape(contact["sitio_web"]),
        "ZZUBICACIONZZ": latex_escape(contact["ubicacion"]),
        "ZZPERFILZZ": latex_escape(content["perfil"]),
        "ZZEXPERIENCIAZZ": "\n".join(experience_parts),
        "ZZEDUCACIONZZ": education,
        "ZZHABILIDADESZZ": skills,
        "ZZIDIOMASZZ": languages,
        "ZZCERTIFICACIONESZZ": certifications,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def validate_tex(document: str) -> None:
    """Comprueba que el documento tenga la estructura mínima compilable."""
    if "\\documentclass" not in document:
        raise ValueError("El archivo LaTeX no contiene \\documentclass.")
    if "\\begin{document}" not in document:
        raise ValueError("El archivo LaTeX no contiene \\begin{document}.")
    if "\\end{document}" not in document:
        raise ValueError("El archivo LaTeX no contiene \\end{document}.")
    if re.search(r"ZZ[A-Z0-9]+ZZ", document):
        raise ValueError("La plantilla contiene marcadores sin reemplazar.")


def compile_pdf(tex_path: Path, output: Path, pdf_path: Path) -> None:
    """Compila dos pasadas y muestra el log de MiKTeX cuando falla."""
    validate_tex(tex_path.read_text(encoding="utf-8"))
    print("Iniciando compilación del PDF con MiKTeX...", flush=True)
    pdflatex = shutil.which("pdflatex")
    if not pdflatex and sys.platform == "win32":
        candidates = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "MiKTeX/miktex/bin/x64/pdflatex.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/MiKTeX/miktex/bin/x64/pdflatex.exe",
        ]
        pdflatex = next((str(path) for path in candidates if path.exists()), None)
    if not pdflatex:
        pdflatex = "pdflatex"
    try:
        for _ in range(2):
            subprocess.run(
                [pdflatex, "-interaction=nonstopmode", "-halt-on-error",
                 "-file-line-error", "-output-directory", str(output), str(tex_path)],
                check=True,
                capture_output=True,
                text=True,
            )
    except FileNotFoundError as exc:
        raise RuntimeError("No se encontró pdflatex. Instala MiKTeX o agrega su carpeta bin al PATH.") from exc
    except subprocess.CalledProcessError as exc:
        log_path = output / f"{tex_path.stem}.log"
        detail = "Error de compilación LaTeX."
        if log_path.exists():
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            useful_lines = [
                line.strip() for line in log_lines
                if line.strip().startswith("!") or "Undefined control sequence" in line
            ]
            if useful_lines:
                detail = useful_lines[0]
        raise RuntimeError(f"MiKTeX no pudo compilar el CV: {detail}") from exc

    compiled_pdf = output / f"{tex_path.stem}.pdf"
    if not compiled_pdf.exists() or compiled_pdf.stat().st_size == 0:
        raise RuntimeError(f"pdflatex terminó sin generar un PDF válido: {compiled_pdf}")
    if compiled_pdf.resolve() != pdf_path.resolve():
        shutil.copy2(compiled_pdf, pdf_path)
    print("PDF generado correctamente.")


def build_prompt(cv: str, job: str) -> str:
    prompt_path = Path(__file__).with_name("data") / "prompt.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"No existe el prompt: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    return prompt.replace("ZZCVZZ", cv).replace("ZZJOBZZ", job)
"""
El JSON será insertado posteriormente por un programa Python en una plantilla LaTeX fija.
No incluy texto antes ni después del objeto JSON y no uses bloques de código.

Antes de redactar el JSON, analiza internamente la oferta e identifica:
- responsabilidades principales del cargo;
- tecnologías, herramientas y frameworks solicitados;
- competencias técnicas y metodologías;
- nivel de experiencia, idiomas y requisitos académicos;
- palabras clave relevantes para sistemas ATS.

Reglas de adaptación:
1. Conserva únicamente información verdadera y explícita del CV base.
2. No inventes empresas, fechas, cargos, métricas, tecnologías, responsabilidades ni proyectos.
3. Prioriza las experiencias y logros más relacionados con la oferta.
4. Dentro de cada experiencia, ordena primero los logros más relevantes para el cargo objetivo.
5. Puedes reescribir los logros para hacerlos más claros y orientados a resultados, sin cambiar su significado.
6. Usa palabras clave de la oferta únicamente cuando describan algo presente en el CV.
7. Reduce contenido poco relacionado si es necesario, pero no borres experiencia importante solo para forzar una página.
8. Mantén el idioma profesional de la oferta cuando sea apropiado.
9. El resultado puede ocupar una o dos páginas; nunca comprimas el contenido hasta volverlo difícil de leer.
10. El objetivo es posicionar al candidato para esta oferta concreta, no producir un CV genérico.

Devuelve exactamente esta estructura, usando cadenas vacías o listas vacías cuando un dato no exista:
{{
  "nombre": "...",
  "cargo": "...",
  "contacto": {{
    "telefono": "...",
    "correo": "...",
    "sitio_web": "...",
    "ubicacion": "..."
  }},
  "perfil": "...",
  "experiencia": [
    {{
      "cargo": "...",
      "empresa": "...",
      "fechas": "...",
      "ubicacion": "...",
      "logros": ["...", "..."]
    }}
  ],
  "educacion": [
    {{"titulo": "...", "institucion": "...", "fecha": "..."}}
  ],
  "habilidades": [
    {{"categoria": "...", "items": "..."}}
  ],
  "idiomas": ["..."],
  "certificaciones": ["..."]
}}

Ordena la experiencia de la más reciente a la más antigua. No incluyas referencias profesionales salvo que la oferta las solicite.

CV base:
---
{cv}
---

Oferta de empleo:
---
{job}
---
"""


def call_provider(prompt: str, provider: str) -> str:
    if provider == "deepseek":
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("Falta DEEPSEEK_API_KEY en .env")
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                  "messages": [{"role": "system", "content": "Eres un experto en CV y LaTeX."}, {"role": "user", "content": prompt}],
                  "temperature": 0.4},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    if provider == "gemini":
        key = os.getenv("CV_API_KEY")
        if not key:
            raise RuntimeError("Falta CV_API_KEY en .env")
        model = os.getenv("CV_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        max_attempts = min(int(os.getenv("LLM_MAX_ATTEMPTS", "5")), 5)
        retry_delay = 5
        retryable_statuses = {429, 500, 502, 503, 504}

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    url,
                    params={"key": key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=120,
                )
                if response.status_code in retryable_statuses:
                    if attempt == max_attempts:
                        response.raise_for_status()
                    print(f"Error {response.status_code} de Gemini; reintentando en {retry_delay} segundos ({attempt}/{max_attempts})...")
                    time.sleep(retry_delay)
                    continue
                response.raise_for_status()
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except requests.Timeout:
                if attempt == max_attempts:
                    raise RuntimeError(f"Gemini agotó los {max_attempts} intentos por tiempo de espera.")
                print(f"Tiempo de espera agotado; reintentando en {retry_delay} segundos ({attempt}/{max_attempts})...")
                time.sleep(retry_delay)

        raise RuntimeError("Gemini no respondió después de varios intentos.")

    raise ValueError("Proveedor inválido. Usa 'deepseek' o 'gemini'.")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Carpeta de la oferta con cv.md y empleo.md")
    parser.add_argument("--provider", choices=["deepseek", "gemini"], default=os.getenv("LLM_PROVIDER", "deepseek"))
    parser.add_argument("--dry-run", action="store_true", help="Lee los Markdown y guarda la solicitud sin llamar a la API")
    parser.add_argument("--generate-only", action="store_true", help="Genera y guarda el .tex sin compilar el PDF")
    parser.add_argument("--pdf-only", action="store_true", help="Compila el .tex existente sin llamar a la API")
    parser.add_argument("--template-only", action="store_true", help="Regenera el .tex y el PDF desde el JSON existente sin llamar a la API")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    cv_path, job_path = project_root / "data" / "cv.md", args.folder / "empleo.md"
    if not cv_path.exists():
        raise FileNotFoundError(f"No existe el CV maestro: {cv_path}")
    if not job_path.exists():
        raise FileNotFoundError(f"La carpeta de oferta debe contener empleo.md: {job_path}")
    offer_folder = args.folder
    output = offer_folder / "data"
    output.mkdir(parents=True, exist_ok=True)
    tex_path = output / "cv_carlos_urresty.tex"
    content_path = output / "contenido_adaptado.json"
    template_path = Path(__file__).with_name("latex_template.tex")
    pdf_path = offer_folder / "cv_carlos_urresty.pdf"

    if args.pdf_only:
        if not tex_path.exists():
            raise FileNotFoundError(f"No existe el archivo LaTeX: {tex_path}")
        existing_tex = tex_path.read_text(encoding="utf-8")
        repaired_tex = existing_tex.replace(r"\square", r"\textbullet")
        if repaired_tex != existing_tex:
            tex_path.write_text(repaired_tex, encoding="utf-8")
            print("Se corrigieron comandos LaTeX incompatibles en el archivo existente.")
        print(f"Compilando {tex_path.resolve()} sin llamar a la API...")
        compile_pdf(tex_path, output, pdf_path)
        print(f"PDF listo: {pdf_path.resolve()}")
        return 0

    if args.template_only:
        if not content_path.exists():
            raise FileNotFoundError(f"No existe el contenido JSON: {content_path}. Ejecuta primero una generación con Gemini.")
        if not template_path.exists():
            raise FileNotFoundError(f"No existe la plantilla LaTeX: {template_path}")
        content = parse_content_json(content_path.read_text(encoding="utf-8"))
        rendered_tex = render_content(template_path.read_text(encoding="utf-8"), content)
        validate_tex(rendered_tex)
        tex_path.write_text(rendered_tex, encoding="utf-8")
        print(f"LaTeX regenerado desde plantilla: {tex_path.resolve()}")
        compile_pdf(tex_path, output, pdf_path)
        print(f"PDF listo: {pdf_path.resolve()}")
        return 0

    cv_text = cv_path.read_text(encoding="utf-8").strip()
    job_text = job_path.read_text(encoding="utf-8").strip()
    if not cv_text or not job_text:
        raise ValueError("El CV maestro y empleo.md no pueden estar vacíos.")
    prompt = build_prompt(cv_text, job_text)

    if args.dry_run:
        request_path = output / "solicitud_generacion.txt"
        request_path.write_text(prompt, encoding="utf-8")
        print(f"Paso 3 validado. Solicitud guardada en: {request_path.resolve()}")
        return 0

    print(f"Generando contenido estructurado con {args.provider}...", flush=True)
    content = parse_content_json(call_provider(prompt, args.provider))
    print("Generador de IA finalizado correctamente; respuesta validada.", flush=True)
    content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Contenido JSON guardado en: {content_path.resolve()}")
    if not template_path.exists():
        raise FileNotFoundError(f"No existe la plantilla LaTeX: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    rendered_tex = render_content(template, content)
    validate_tex(rendered_tex)
    tex_path.write_text(rendered_tex, encoding="utf-8")
    print(f"LaTeX generado desde plantilla fija: {tex_path.resolve()}")
    if args.generate_only:
        return 0
    compile_pdf(tex_path, output, pdf_path)
    print(f"Listo: {pdf_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "desconocido"
        detail = ""
        if exc.response is not None:
            try:
                detail = exc.response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
        suffix = f": {detail}" if detail else ""
        print(f"Error HTTP {status} del proveedor de IA{suffix}", file=sys.stderr)
        raise SystemExit(1)
    except (RuntimeError, ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
