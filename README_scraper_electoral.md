# Scraper de Resultados Electorales - Congreso 2026

## Descripción

Este scraper está diseñado para extraer resultados electorales de las elecciones al Congreso de la República 2026 (Cámara y Senado) por mesa de votación, calcular correlaciones entre votos de candidatos a Cámara y votos de Juan Camilo Velez Londoño al Senado, y determinar el costo por voto basado en inversiones de campaña.

## Características

- ✅ Extracción de resultados por mesa de votación (formularios E-14)
- ✅ Soporte para múltiples fuentes de datos (API, CSV, E-14 escaneados)
- ✅ Correlación entre votos de Cámara y Senado por mesa
- ✅ Cálculo de costo por voto
- ✅ Generación de CSV con resultados detallados y resumen
- ✅ Manejo robusto de errores y logging

## Requisitos

```bash
pip install playwright pandas requests asyncio
playwright install chromium
```

## Estructura del Proyecto

```
Web_Scrapping/
├── scraper_resultados_electorales_congreso.py  # Script principal
├── config_candidatos.json                       # Configuración de candidatos
├── info_para_scrpping_costo_por_voto_juan.txt  # Información de referencia
└── README_scraper_electoral.md                 # Esta documentación
```

## Configuración

### 1. Editar `config_candidatos.json`

Agregar las inversiones reales de cada candidato:

```json
{
  "inversiones": {
    "Rigo Vega Cartago": 50000000,
    "Adriana Daraviña": 30000000,
    ...
  }
}
```

### 2. Ajustar configuración del scraper

En `config_candidatos.json` puedes modificar:
- `headless`: Modo sin interfaz gráfica (true/false)
- `timeout_pagina`: Tiempo de espera para cargar páginas
- `delay_entre_requests`: Pausa entre solicitudes (evitar sobrecarga)

## Uso

### Ejecución básica

```bash
python scraper_resultados_electorales_congreso.py
```

### Ejecución programada (después del 8 de marzo de 2026)

El scraper detectará automáticamente cuando los resultados estén disponibles y comenzará la extracción.

## Estrategia de Scraping

Dado que los resultados aún no están publicados, el scraper implementa una estrategia multi-método:

### Método 1: API REST (más rápido)
- Intenta detectar endpoints de API de la Registraduría
- Extrae datos en formato JSON
- Procesa resultados estructurados

### Método 2: Descarga de CSV
- Busca archivos CSV publicados por la Registraduría o CEDAE
- Procesa datos tabulares directamente

### Método 3: Formularios E-14 (más completo)
- Extrae datos de formularios E-14 escaneados
- Permite obtener resultados por mesa individual
- Más lento pero más detallado

## Estructura de Datos de Salida

### CSV Detallado (`resultados_costo_por_voto.csv`)

| Columna | Descripción |
|---------|-------------|
| departamento | Departamento (VALLE, RISARALDA, CALDAS) |
| municipio | Municipio |
| puesto_votacion | Puesto de votación |
| mesa | Número de mesa |
| candidato_camara | Nombre del candidato a Cámara |
| votos_camara | Votos obtenidos por el candidato en esta mesa |
| votos_senado_juan | Votos de Juan al Senado en esta mesa |
| ratio_correlacion | Ratio entre votos Cámara y Senado |
| inversion_candidato | Inversión del candidato |
| costo_por_voto | Costo por voto del candidato |

### CSV Resumen (`resultados_costo_por_voto_resumen.csv`)

| Columna | Descripción |
|---------|-------------|
| candidato_camara | Nombre del candidato |
| votos_camara | Total de votos obtenidos |
| votos_senado_juan | Total de votos correlacionados con Juan |
| inversion | Inversión total |
| costo_por_voto | Costo promedio por voto |
| costo_por_voto_correlacionado | Costo por voto correlacionado |
| aporte_relativo | Porcentaje de aporte a la campaña de Juan |

## Análisis de Correlación

El scraper calcula la correlación entre votos de candidatos a Cámara y votos de Juan al Senado por mesa de votación. Esto permite identificar:

1. **Candidatos más efectivos**: Quienes generan más votos correlacionados
2. **Costo por voto**: Eficiencia de inversión por candidato
3. **Aporte relativo**: Contribución porcentual de cada candidato a la campaña

## URLs Esperadas (cuando se publiquen)

El scraper buscará automáticamente en estas URLs:

- `https://e14_congreso_2026.registraduria.gov.co/`
- `https://congreso2026.registraduria.gov.co/`
- `https://escrutinios2026.registraduria.gov.co/`
- `https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/resultados/`
- `https://wapp.registraduria.gov.co/electoral/2026/congreso-de-la-republica/escrutinios/`

## Logging

El scraper genera logs en:
- Consola (salida estándar)
- Archivo `scraper_electoral.log`

Niveles de log:
- `INFO`: Progreso general
- `WARNING`: Advertencias (ej: resultados no disponibles)
- `ERROR`: Errores críticos
- `DEBUG`: Información detallada de depuración

## Manejo de Errores

El scraper incluye manejo robusto de errores:
- Reintentos automáticos en caso de fallos de red
- Validación de datos antes de procesar
- Continuación del proceso aunque falle una mesa individual
- Logging detallado de errores

## Consideraciones Importantes

1. **Fecha de Ejecución**: Los resultados estarán disponibles después del 8 de marzo de 2026
2. **Rate Limiting**: El scraper incluye delays entre requests para evitar sobrecargar los servidores
3. **Datos Sensibles**: Las inversiones deben ser proporcionadas manualmente en el archivo de configuración
4. **Variaciones de Nombres**: El scraper maneja variaciones en los nombres de candidatos (tildes, abreviaciones)

## Próximos Pasos

1. **Después del 8 de marzo de 2026**:
   - Ejecutar el scraper para detectar URLs activas
   - Verificar estructura de datos publicados
   - Ajustar selectores HTML si es necesario

2. **Agregar Inversiones**:
   - Completar el campo `inversiones` en `config_candidatos.json`
   - Validar que los nombres coincidan exactamente

3. **Validación de Resultados**:
   - Comparar resultados con datos oficiales
   - Verificar correlaciones calculadas
   - Ajustar algoritmos si es necesario

## Troubleshooting

### Error: "No se encontraron URLs activas"
- **Causa**: Los resultados aún no están publicados
- **Solución**: Esperar hasta después del 8 de marzo de 2026

### Error: "Timeout esperando página"
- **Causa**: Conexión lenta o servidor sobrecargado
- **Solución**: Aumentar `timeout_pagina` en configuración

### Error: "No se encontraron datos en E-14"
- **Causa**: Estructura HTML diferente a la esperada
- **Solución**: Inspeccionar página real y ajustar selectores

## Contacto y Soporte

Para problemas o mejoras, revisar los logs en `scraper_electoral.log` y ajustar la configuración según sea necesario.
