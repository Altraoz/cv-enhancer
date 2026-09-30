# Análisis DOM de Computrabajo

URL analizada:

`https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-profesional-de-desarrollo-web-ingenieria-de-sistemas-desarrollador-web-ingeniero-de-sistemas-en-bogota-dc-E8221A02B46EFF6461373E686DCF3405?fgoa=true`

## Hallazgo principal

Computrabajo carga una página de resultados y abre la oferta seleccionada en un panel de detalle. El DOM contiene primero la grilla completa de ofertas y después el detalle de la oferta seleccionada. Si se usa `main.get_text()` o `body.get_text()`, se mezclan ambas zonas.

## Zona que debe ignorarse

- Contenedor `offersGridOfferContainer`.
- Artículos de resultados relacionados.
- Filtros de búsqueda: orden, distancia, fecha, lugar, experiencia, salario, jornada y contrato.
- Bloque `Empleos similares`.
- Información de la empresa, salarios y evaluaciones, salvo que se quiera incluir como contexto opcional.

## Zona de detalle observada

El panel de detalle contiene, en este orden:

1. Título del cargo: `Profesional de Desarrollo Web, Ingeniería de sistemas, Desarrollador web`.
2. Cargo normalizado: `Ingeniero de sistemas`.
3. Empresa: `SUMINISTRAMOS RECURSOS HUMANOS TEMPORALES SUMITEMP S.A.S`.
4. Ubicación: `Bogotá, D.C., Bogotá, D.C.`.
5. Resumen:
   - Contrato a término indefinido.
   - Tiempo Completo.
   - Presencial.
6. Descripción de la oferta.
7. Reto y responsabilidades.
8. Requisitos técnicos y académicos.
9. Condiciones, horario y beneficios.
10. Fuente y enlace de la oferta.

## Estrategia de extracción

El adaptador debe localizar el panel de detalle mediante el título de la oferta seleccionada y extraer únicamente su contenedor padre. No debe tomar el texto global de `main`, `body` ni de la grilla.

La extracción debe apoyarse en este orden de prioridad:

1. Selectores semánticos del panel de detalle y sus encabezados.
2. JSON-LD o metadatos estructurados, si están presentes.
3. Selectores de clases/atributos específicos descubiertos en el HTML.
4. Playwright como respaldo para contenido cargado dinámicamente.

## Validaciones mínimas

El adaptador no debe guardar la oferta si no encuentra:

- título;
- empresa o ubicación;
- descripción con contenido suficiente;
- al menos un requisito o bloque de condiciones.

La siguiente etapa debe implementar `scrape_computrabajo()` y producir campos separados antes de construir `empleo.md`.
