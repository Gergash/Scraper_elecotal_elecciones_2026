# Cómo iniciar el scraper

## ¿Qué falta para iniciar el scraper?

### 1. **URL(s) donde está la información**
El scraper necesita la(s) URL(s) exacta(s) donde aparece la sección `party-detail-row` (lista del Partido Conservador al Senado).

**Cómo obtenerla:**
- Abre en el navegador la página donde ves la tabla de resultados
- Copia la URL de la barra de direcciones
- Agrega la URL en `config_candidatos.json` en `urls_scraper`, o pásala por línea de comandos con `--urls URL`

**Ejemplo en config:**
```json
"urls_scraper": [
  "https://resultados.registraduria.gov.co/senado/partido-conservador",
  "https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/"
]
```

### 2. **Playwright instalado**
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. **Dependencias Python**
```bash
cd JCVL/Web_Scrapping
pip install playwright pandas requests
```

---

## Características del scraper

- **Timeout:** 10 segundos por página
- **Paralelo:** Múltiples ventanas/pestañas consultan las URLs al mismo tiempo
- **Loop:** Ejecuta → guarda en `backup` → refresca (pausa 5s) → repite
- **Salida:** Todos los archivos se guardan en la carpeta `backup/`

---

## Cómo ejecutar

### Opción 1: Usando URLs del config
```bash
cd JCVL/Web_Scrapping
python ejecutar_scraper.py
```

### Opción 2: Pasando URLs por línea de comandos
```bash
python ejecutar_scraper.py --urls "https://ejemplo.com/resultados,https://otra-url.com"
```

### Opción 3: Limitar número de ciclos
```bash
python ejecutar_scraper.py --ciclos 5
```

### Opción 4: Ciclos infinitos (Ctrl+C para detener)
```bash
python ejecutar_scraper.py --urls "URL_AQUI"
# Presiona Ctrl+C para detener
```

### Opción 5: Pausa entre ciclos personalizada
```bash
python ejecutar_scraper.py --urls "URL" --pausa 10
```

---

## Estructura de salida en `backup/`

- `ciclo_N_TIMESTAMP_resultado_X.json` – metadatos y comparativa JCV
- `ciclo_N_TIMESTAMP_lista_X.csv` – lista completa de candidatos
- `ciclo_N_TIMESTAMP_resumen.json` – resumen del ciclo

---

## Notas

- Si la página no está publicada o la URL no es correcta, el scraper intentará y registrará que no encontró `party-detail-row`.
- Para que funcione, la página debe contener la tabla con la clase CSS `party-detail-row` (estructura Radix UI).
- El navegador se abre visible (`headless: false` en config). Para ejecutar en segundo plano, edita `configuracion_scraper.headless: true` en `config_candidatos.json`.
