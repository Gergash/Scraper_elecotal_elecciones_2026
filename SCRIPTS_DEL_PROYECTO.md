# Scripts del proyecto Web_Scrapping – listado y utilidad

## 1. Scripts ejecutables (punto de entrada)

| # | Script | Utilidad | Resultado típico al ejecutarlo |
|---|--------|----------|-------------------------------|
| 1 | **`ejecutar_todo.py`** | Orquestador: lanza en paralelo el runner de URLs, la comparativa Conservador, el scraper de mesas E-14 y el scraper de divulgación E14. | Varios CSVs y HTML en `backup/`: comparativa, resultados_mesas_*.csv, divulgacion_e14_*.csv; opcionalmente descargas E14 en `e14_descargas/`. Proceso largo y pesado (varios navegadores). |
| 2 | **`ejecutar_scraper.py`** | Runner paralelo: abre las 4 URLs de `config_candidatos.json` en pestañas, en loop busca `party-detail-row`, guarda HTML en `backup/`. | Archivos HTML/guardados por ciclo en `backup/`. Solo aporta en páginas que tengan ese selector. |
| 3 | **`ejecutar_comparativa.py`** | Comparativa Senado: consulta resultados.registraduria (Senado), expande Partido Conservador, extrae votos por candidato y los append en CSV. Modo periódico o una sola consulta. | `backup/comparativa.csv` con columnas CANDIDATO, VOTOS, HORA_DE_LA_CONSULTA (serie temporal para Juan Camilo y lista). |
| 4 | **`ejecutar_scraper_mesas.py`** | Scraper jerárquico de mesas: en actas-e14 navega Corporación → Departamento → Municipio → Zona → Puesto → Mesa; extrae votos Cámara y Senado por mesa. | `backup/resultados_mesas_*.csv` y `backup/progreso_mesas.json`. Reanudable. |
| 5 | **`scraper_resultados_electorales_congreso.py`** | Punto de entrada del flujo “resultados electorales”: (1) extrae votos Cámara del Partido Conservador por cada municipio de VALLE, RISARALDA y CALDAS en resultados.registraduria; (2) luego corre detección de URLs, correlación y costo por voto. | `backup/resultados_camara_conservador_por_municipio.csv` (solo candidatos de la lista); opcionalmente CSVs de correlación/costo por voto. |
| 6 | **`scraper_lista_conservador.py`** | Lee HTML de la fila `party-detail-row` (archivo o stdin), parsea candidatos y votos, compara con Juan Camilo Vélez y puede guardar comparativa. | Salida en consola (posición JCV, votos, top 5); opcionalmente append en CSV comparativa. No navega por sí solo. |
| 7 | **`scraper_estado_mesas_e14.py`** | Scraper de estado de mesas E14: en actas-e14 recorre Corporación → Departamento → Municipio → Zona → Puesto y extrae estado de mesas (Senado y Cámara) para Valle, Caldas y Risaralda. | `estado_mesas_e14.csv` y `estado_mesas_e14.json` en el directorio de ejecución. |
| 8 | **`scraper_puestos_votacion.py`** | Extrae información de puestos de votación desde wapp.registraduria (Congreso 2026) para VALLE, RISARALDA y CALDAS. | `puestos_votacion.csv` (departamento, municipio, puesto, dirección, etc.). |
| 9 | **`ejemplo_uso_scraper.py`** | Ejemplo/demo: valida config, carga inversiones, instancia `ScraperResultadosElectorales` y ejecuta scraping (o datos simulados). | Demostración en consola; no está pensado para producción. |
| 10 | **`utilidades_scraper.py`** (como script) | Valida `config_candidatos.json` (estructura, candidatos, inversiones) e imprime OK o lista de errores. | Solo salida en consola (validación). |
| 11 | **`script_twitter_candidato_Yamil.py`** | Script específico: login en X/Twitter y scrapeo de timeline de un usuario (ej. JMilei). Usa credenciales en código. | CSV con tweets (ej. `tweets_JMilei.csv`). Fuera del flujo electoral principal. |
| 12 | **`ejecutar_camara_senado_paralelo.py`** | Ejecuta en paralelo `scraper_resultados_camara` y `scraper_resultados_senado`: extrae votos Cámara (lista candidatos) y Senado (solo Juan Camilo Vélez) por municipio en VALLE, RISARALDA y CALDAS. | `backup/resultados_camara_conservador_por_municipio.csv` y `backup/resultados_senado_conservador_por_municipio.csv`. |

---

## 2. Módulos ejecutables con `python -m`

Estos se invocan como módulo y tienen su propio `if __name__ == "__main__"`:

| # | Invocación | Utilidad | Resultado típico |
|---|------------|----------|------------------|
| 12 | **`python -m scrapper.scraper_resultados_camara`** | Mismo flujo Cámara por municipio que usa `scraper_resultados_electorales_congreso`: resultados.registraduria → Cámara → cada municipio VALLE/RISARALDA/CALDAS → Partido Conservador. Sin filtro por defecto (todos los candidatos del partido). | `backup/resultados_camara_conservador_por_municipio.csv` (sobrescrito). |
| 13 | **`python -m scrapper.scraper_divulgacion_e14`** | Divulgación E14: home divulgacione14congreso → menú SENADO/CAMARA, páginas 01/03/04, tabla por departamento (VALLE, CALDAS, RISARALDA); opcionalmente entra a cada departamento y descarga E14. | `backup/divulgacion_e14_*.csv` y, si descarga activa, `backup/e14_descargas/`. |
| 14 | **`python -m scrapper.scraper_resultados_senado`** | Senado por municipio: resultados.registraduria → Senado (0/00/0) → departamento → municipio → Partido Conservador. Solo extrae votos de Juan Camilo Vélez. | `backup/resultados_senado_conservador_por_municipio.csv`. |

---

## 3. Módulos sin `__main__` (solo importables)

- **`scrapper/runner_paralelo.py`** – Lógica del runner (loop por URLs, extracción `party-detail-row`). Usado por `ejecutar_scraper.py` y por `ejecutar_todo.py`.
- **`scrapper/comparativa_conservador.py`** – Lógica comparativa Senado (expandir Conservador, extraer candidatos, guardar CSV). Usado por `ejecutar_comparativa.py` y por `ejecutar_todo.py`.
- **`scrapper/scraper_mesas.py`** – Navegación jerárquica mesas y extracción votos. Usado por `ejecutar_scraper_mesas.py` y por `ejecutar_todo.py`.
- **`scrapper/scraper_divulgacion_e14.py`** – Lógica divulgación E14. Usado por `ejecutar_todo.py` y vía `python -m`.
- **`scrapper/scraper_resultados_camara.py`** – Lógica Cámara por municipio. Usado por `scrapper/main.py` (y por tanto por `scraper_resultados_electorales_congreso.py`) y vía `python -m`.
- **`scrapper/lista_conservador.py`** – Parseo HTML lista Conservador y comparación JCV. Usado por comparativa y por `scraper_lista_conservador.py`.
- **`scrapper/scraper.py`** – Clase `ScraperResultadosElectorales` (detección URLs, API, E-14, correlación, costo por voto). Usado por `scrapper/main.py` y por `ejemplo_uso_scraper.py`.
- **`scrapper/main.py`** – Flujo principal del “scraper resultados electorales” (Cámara por municipio + ejecutar_scraping_completo). Invocado por `scraper_resultados_electorales_congreso.py`.
- **`scrapper/config.py`** – Carga de `config_candidatos.json`. Usado por casi todos.
- **`scrapper/utils.py`** – Logger y helpers. Usado por varios.

---

## 4. Resultado de ejecutar “todos” los scripts

No hay un único comando que ejecute literalmente todos; si se lanzan uno tras otro (o en paralelo donde aplique), el efecto global sería:

### Archivos y datos generados

- **`backup/comparativa.csv`** – Votos lista Conservador al Senado en el tiempo (varias ejecuciones de comparativa).
- **`backup/resultados_mesas_*.csv`** – Votos por mesa (Cámara y Senado) en VALLE, RISARALDA, CALDAS desde actas-e14.
- **`backup/progreso_mesas.json`** – Progreso del scraper de mesas (reanudación).
- **`backup/divulgacion_e14_*.csv`** – Avance por departamento (Esperados, Publicados, Avances, Faltantes) en divulgación E14.
- **`backup/e14_descargas/`** – PDFs E14 por corporación y departamento (si se ejecuta divulgación con descarga).
- **`backup/resultados_camara_conservador_por_municipio.csv`** – Votos a Cámara (Partido Conservador) por departamento y municipio; con el flujo de `scraper_resultados_electorales_congreso.py` o del módulo Cámara, filtrado a la lista de candidatos objetivo.
- **`backup/resultados_senado_conservador_por_municipio.csv`** – Votos al Senado (solo Juan Camilo Vélez, Partido Conservador) por departamento y municipio; generado por `scraper_resultados_senado.py` o `ejecutar_camara_senado_paralelo.py`.
- **`backup/`** – Diversos HTML o archivos guardados por el runner paralelo (según URLs y estructura de cada página).
- **`estado_mesas_e14.csv`**, **`estado_mesas_e14.json`** – Estado de mesas E14 (si se ejecuta `scraper_estado_mesas_e14.py`).
- **`puestos_votacion.csv`** – Puestos de votación (si se ejecuta `scraper_puestos_votacion.py`).
- **`tweets_*.csv`** – Tweets del script de X/Twitter (si se ejecuta y se completa login).
- Posibles CSVs de correlación/costo por voto en el directorio de ejecución (según `scraper.py` / `main`).

### Consideraciones

1. **`ejecutar_todo.py`** ya agrupa runner, comparativa, mesas y divulgación en paralelo; ejecutarlo **y además** por separado `ejecutar_scraper.py`, `ejecutar_comparativa.py`, `ejecutar_scraper_mesas.py` duplicaría trabajo y podría generar archivos mezclados o sobrescritos.
2. **Scraper de Cámara por municipio** se ejecuta con **`scraper_resultados_electorales_congreso.py`** (recomendado para generar `resultados_camara_conservador_por_municipio.csv` con la lista de candidatos) o con **`python -m scrapper.scraper_resultados_camara`** (mismo CSV, todos los candidatos Conservador por defecto).
3. **Scraper de divulgación E14** se ejecuta dentro de `ejecutar_todo.py` o con **`python -m scrapper.scraper_divulgacion_e14`**.
4. Ejecutar “todos” los scripts a la vez (varios procesos) abriría muchos navegadores y podría saturar recursos o provocar bloqueos; es mejor correr el orquestador **`ejecutar_todo.py`** una vez y, por separado y cuando convenga, **`scraper_resultados_electorales_congreso.py`**, **`scraper_estado_mesas_e14.py`**, **`scraper_puestos_votacion.py`** y el script de Twitter si se necesita.

---

## 5. Resumen por objetivo

- **Solo comparativa Senado (lista Conservador):** `ejecutar_comparativa.py` → `backup/comparativa.csv`.
- **Solo votos por mesa (actas E-14):** `ejecutar_scraper_mesas.py` → `backup/resultados_mesas_*.csv`.
- **Solo avance divulgación E14 (y opcional descarga E14):** `python -m scrapper.scraper_divulgacion_e14` o tarea dentro de `ejecutar_todo.py`.
- **Solo votos Cámara por municipio (lista de candidatos):** `scraper_resultados_electorales_congreso.py` → `backup/resultados_camara_conservador_por_municipio.csv`.
- **Solo votos Senado por municipio (Juan Camilo Vélez):** `python -m scrapper.scraper_resultados_senado` → `backup/resultados_senado_conservador_por_municipio.csv`.
- **Cámara y Senado en paralelo:** `python ejecutar_camara_senado_paralelo.py` → ambos CSVs.
- **Todo el monitoreo junto (sin Cámara por municipio):** `ejecutar_todo.py`.
- **Validar configuración:** `python utilidades_scraper.py` o usar `validar_configuracion()` desde otro script.
