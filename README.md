# CV Compiler

CV Compiler genera CV personalizados en PDF a partir de una oferta laboral.

Gemini adapta el contenido del CV, pero el diseño visual está controlado por una plantilla LaTeX fija. Gemini no genera LaTeX.

## Cómo funciona

```text
URL de oferta
       |
       v
scrape_job.py → ofertas/DD-MM-YYYY/empresa/empleo.md
       |
       v
data/cv.md + empleo.md + data/prompt.txt
                    |
                    v
              Gemini devuelve JSON
                    |
                    v
             Python valida el JSON
                    |
                    v
        latex_template.tex recibe el contenido
                    |
                    v
              MiKTeX genera el PDF
```

El programa analiza la oferta, prioriza experiencias relevantes, usa palabras clave ATS respaldadas por el CV, evita inventar información y genera un documento de una o dos páginas según el contenido.

## Estructura

```text
Compiler/
├── cv_compiler.py
├── latex_template.tex
├── requirements.txt
├── .env
├── data/
│   ├── cv.md                 # CV maestro reutilizable
│   └── prompt.txt            # Instrucciones para Gemini
└── ofertas/
    └── DD-MM-YYYY/
        └── empresa/
        ├── empleo.md        # Oferta laboral
        ├── cv_adaptado.pdf   # Resultado final
        └── data/             # Archivos técnicos generados
            ├── contenido_adaptado.json
            ├── cv_adaptado.tex
            └── cv_adaptado.log
```

## Configuración

Crear `.env` en la raíz:

```env
CV_API_KEY=tu_api_key_para_cv
CV_MODEL=gemini-3.1-flash-lite
SCRAPER_API_KEY=tu_api_key_para_scraper
SCRAPER_MODEL=tu_modelo_para_scraper
LLM_PROVIDER=gemini
LLM_MAX_ATTEMPTS=5
```

El generador del CV usa `CV_API_KEY` y `CV_MODEL`. El scraper HTTP actual no necesita API; `SCRAPER_API_KEY` y `SCRAPER_MODEL` quedan reservadas para la futura etapa de extracción con IA. Las API keys no deben compartirse ni subirse al repositorio.

## Instalación

```powershell
cd C:\Carlos\CV\Compiler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

También se necesita MiKTeX con `pdflatex`.
Para páginas dinámicas, instala además Chromium para Playwright:

```powershell
playwright install chromium
```

## Crear una oferta desde una URL

El punto de entrada unificado del proyecto es `pipeline.py`. Ejecuta el scraping,
valida `empleo.md` y luego genera automáticamente el CV:

```powershell
python pipeline.py "URL_DE_LA_OFERTA" --name empresa
```

Por defecto genera el PDF completo usando el proveedor configurado en `LLM_PROVIDER`.
También se puede indicar explícitamente:

```powershell
python pipeline.py "URL_DE_LA_OFERTA" --name empresa --provider gemini
```

Para ofertas que dependen de JavaScript:

```powershell
python pipeline.py "URL_DE_LA_OFERTA" --name empresa --browser
```

Para probar solo la preparación de la solicitud o generar LaTeX sin compilar:

```powershell
python pipeline.py "URL_DE_LA_OFERTA" --name empresa --dry-run
python pipeline.py "URL_DE_LA_OFERTA" --name empresa --generate-only
```

El pipeline solo informa éxito si valida el JSON, el documento LaTeX y, en el modo
normal, la existencia de un PDF con contenido. Si cualquiera de estas validaciones
falla, el proceso termina con error y no presenta el resultado como terminado.

El scraper descarga una oferta pública y crea automáticamente la carpeta de la empresa con la fecha actual:

```powershell
python scrape_job.py "https://www.linkedin.com/jobs/view/123456789" --name empresa --browser
```

También funciona con Indeed y usa un extractor genérico para otros sitios:

```powershell
python scrape_job.py "https://www.indeed.com/viewjob?jk=..." --name empresa
```

Las ofertas de `computrabajo.com` usan automáticamente su adaptador especializado:

```powershell
python pipeline.py "https://co.computrabajo.com/ofertas-de-trabajo/oferta..." --name empresa
```

El adaptador de Computrabajo carga el panel de detalle con Playwright y no usa el
extractor genérico de resultados. LinkedIn, Indeed y otros dominios mantienen sus
adaptadores o comportamiento actual.

Para validar una oferta sin crear `empleo.md` ni llamar a la API del CV:

```powershell
python validate_scraper.py "URL_DE_LA_OFERTA"
```

El validador comprueba título, resumen, descripción mínima y campos estructurados.
Se recomienda probarlo con varias ofertas de Computrabajo antes de usar el pipeline.

El resultado queda en:

```text
ofertas\30-09-2026\empresa\empleo.md
```

La fecha se puede especificar manualmente:

```powershell
python scrape_job.py "URL_DE_LA_OFERTA" --name empresa --date 30-09-2026
```

Usa `--browser` cuando la página dependa de JavaScript, requiera Chromium para mostrar el contenido o el extractor normal obtenga muy poco texto. El scraper no automatiza inicios de sesión ni intenta evadir CAPTCHAs o bloqueos.

## Uso normal

Activar el entorno virtual:

```powershell
cd C:\Carlos\CV\Compiler
.\.venv\Scripts\Activate.ps1
```

Generar contenido y LaTeX sin compilar:

```powershell
python cv_compiler.py ofertas\30-09-2026\empresa --provider gemini --generate-only
```

Generar el PDF completo:

```powershell
python cv_compiler.py ofertas\30-09-2026\empresa --provider gemini
```

El PDF queda en:

```text
ofertas\30-09-2026\empresa\cv_adaptado.pdf
```

## Probar cambios visuales sin llamar a Gemini

Después de generar `contenido_adaptado.json` una vez, se puede modificar `latex_template.tex` y regenerar el PDF sin consumir la API:

```powershell
python cv_compiler.py ofertas\30-09-2026\empresa --template-only
```

## Compilar un LaTeX existente

```powershell
python cv_compiler.py ofertas\30-09-2026\empresa --pdf-only
```

## Crear una nueva oferta

El scraper crea la carpeta automáticamente. Si se crea manualmente, debe seguir esta estructura:

```text
ofertas\30-09-2026\nueva_empresa\empleo.md
```

Ejecutar:

```powershell
python cv_compiler.py ofertas\30-09-2026\nueva_empresa --provider gemini
```

El CV maestro y el prompt se reutilizan automáticamente.

## Reintentos de Gemini

Los errores temporales `429`, `500`, `502`, `503` y `504` se reintentan automáticamente.

- Máximo: 5 intentos.
- Espera entre intentos: 5 segundos.
- Después del quinto fallo, el programa cancela y muestra un resumen.

## Errores de compilación

La consola muestra un resumen limpio. El detalle técnico completo de MiKTeX queda en:

```text
ofertas\ejemplo\data\cv_adaptado.log
```

Errores comunes:

- `No existe el CV maestro`: comprobar `data\cv.md`.
- `No existe el prompt`: comprobar `data\prompt.txt`.
- `Gemini no devolvió JSON válido`: volver a intentar o revisar la respuesta.
- `No se encontró pdflatex`: instalar MiKTeX o agregarlo al `PATH`.

## Archivos que no deben subirse

```text
.env
.venv/
ofertas/*/cv_adaptado.pdf
ofertas/*/data/*.json
ofertas/*/data/*.tex
ofertas/*/data/*.aux
ofertas/*/data/*.log
ofertas/*/data/*.out
```
