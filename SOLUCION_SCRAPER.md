# Solución: Scraper de Resultados Electorales

## Problema

Se necesita hacer web scraping de los resultados electorales públicos de las elecciones al Congreso de la República 2026 para:
1. Extraer resultados por mesa de votación de candidatos a Cámara en Valle, Risaralda y Caldas
2. Correlacionar estos resultados con los votos de Juan Camilo Velez Londoño al Senado
3. Calcular el costo por voto basado en inversiones de campaña
4. Identificar qué candidatos aportaron más a la campaña

**Desafío**: Los resultados aún no están publicados (elecciones el 8 de marzo de 2026).

## Solución Implementada

Se ha creado un sistema de scraping modular y flexible que:

### ✅ Características Principales

1. **Detección Automática de URLs**: El scraper detecta automáticamente dónde se publican los resultados cuando estén disponibles
2. **Múltiples Métodos de Extracción**:
   - API REST (más rápido)
   - Descarga de CSV (intermedio)
   - Formularios E-14 escaneados (más completo, por mesa)
3. **Correlación Inteligente**: Compara votos de Cámara y Senado por mesa de votación
4. **Cálculo de Métricas**: Costo por voto, aporte relativo, eficiencia de inversión
5. **Exportación Completa**: CSV detallado, CSV resumen, reporte de texto, Excel

### 📁 Archivos Creados

```
Web_Scrapping/
├── scraper_resultados_electorales_congreso.py  # Script principal
├── config_candidatos.json                       # Configuración (candidatos, inversiones)
├── utilidades_scraper.py                        # Funciones auxiliares
├── ejemplo_uso_scraper.py                       # Ejemplos de uso
├── requirements.txt                             # Dependencias
├── README_scraper_electoral.md                  # Documentación completa
└── SOLUCION_SCRAPER.md                          # Este archivo
```

## Estrategia de Implementación

### Fase 1: Preparación (Antes del 8 de marzo)

El scraper está diseñado para:
- ✅ Detectar automáticamente cuando los resultados estén disponibles
- ✅ Intentar múltiples métodos de extracción
- ✅ Manejar diferentes estructuras de datos
- ✅ Validar configuración antes de ejecutar

### Fase 2: Ejecución (Después del 8 de marzo)

Cuando los resultados estén publicados:
1. El scraper detectará las URLs activas
2. Extraerá datos usando el método más eficiente disponible
3. Procesará resultados por mesa de votación
4. Calculará correlaciones y métricas
5. Generará reportes completos

### Fase 3: Análisis

Los CSV generados incluyen:
- **Detalle por mesa**: Cada mesa de votación con votos de Cámara y Senado
- **Resumen por candidato**: Métricas agregadas y costo por voto
- **Reporte de texto**: Análisis ejecutivo y top candidatos

## Configuración Requerida

### 1. Instalar Dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar Inversiones

Editar `config_candidatos.json` y agregar las inversiones reales:

```json
{
  "inversiones": {
    "Rigo Vega Cartago": 50000000,
    "Adriana Daraviña": 30000000,
    ...
  }
}
```

### 3. Ejecutar Scraper

```bash
python scraper_resultados_electorales_congreso.py
```

## Estructura de Datos de Salida

### CSV Detallado (`resultados_costo_por_voto.csv`)

| Campo | Descripción |
|-------|-------------|
| departamento | VALLE, RISARALDA o CALDAS |
| municipio | Municipio del puesto de votación |
| puesto_votacion | Identificador del puesto |
| mesa | Número de mesa |
| candidato_camara | Nombre del candidato a Cámara |
| votos_camara | Votos obtenidos en esta mesa |
| votos_senado_juan | Votos de Juan al Senado en esta mesa |
| ratio_correlacion | Ratio entre votos Cámara/Senado |
| inversion_candidato | Inversión del candidato |
| costo_por_voto | Costo por voto calculado |

### CSV Resumen (`resultados_costo_por_voto_resumen.csv`)

| Campo | Descripción |
|-------|-------------|
| candidato_camara | Nombre del candidato |
| votos_camara | Total de votos |
| votos_senado_juan | Total de votos correlacionados |
| inversion | Inversión total |
| costo_por_voto | Costo promedio por voto |
| costo_por_voto_correlacionado | Costo por voto correlacionado |
| aporte_relativo | % de aporte a la campaña |

## Ventajas de esta Solución

1. **Flexibilidad**: Funciona con múltiples fuentes de datos
2. **Robustez**: Manejo de errores y reintentos automáticos
3. **Escalabilidad**: Puede procesar miles de mesas de votación
4. **Mantenibilidad**: Código modular y bien documentado
5. **Preparación**: Listo para ejecutar cuando los resultados estén disponibles

## Próximos Pasos

1. **Antes del 8 de marzo**:
   - ✅ Completar inversiones en `config_candidatos.json`
   - ✅ Validar configuración con `python utilidades_scraper.py`
   - ✅ Probar con datos simulados usando `ejemplo_uso_scraper.py`

2. **Después del 8 de marzo**:
   - Ejecutar el scraper principal
   - Verificar que detecta las URLs correctamente
   - Ajustar selectores HTML si la estructura es diferente
   - Validar resultados con datos oficiales

3. **Análisis**:
   - Revisar CSV generados
   - Analizar costo por voto por candidato
   - Identificar candidatos más efectivos
   - Generar visualizaciones adicionales si es necesario

## Notas Técnicas

- El scraper usa **Playwright** para manejar JavaScript y contenido dinámico
- Incluye **delays** entre requests para evitar sobrecargar servidores
- Genera **logs** detallados en `scraper_electoral.log`
- Maneja **variaciones de nombres** de candidatos (tildes, abreviaciones)
- Soporta **múltiples formatos** de datos (JSON, CSV, HTML)

## Preguntas Frecuentes

**P: ¿Qué pasa si los resultados tienen una estructura diferente?**
R: El scraper intenta múltiples métodos y puede ajustarse fácilmente. Los logs indicarán qué método funcionó.

**P: ¿Cuánto tiempo tarda el scraping?**
R: Depende del método usado. API: minutos, CSV: minutos, E-14: horas (miles de mesas).

**P: ¿Puedo ejecutarlo antes del 8 de marzo?**
R: Sí, pero solo detectará que los resultados no están disponibles. Puedes probar con datos simulados.

**P: ¿Necesito conocimientos técnicos avanzados?**
R: No, solo editar el JSON de configuración y ejecutar el script. La documentación está completa.

## Contacto y Soporte

- Revisar logs en `scraper_electoral.log` para diagnóstico
- Validar configuración con `python utilidades_scraper.py`
- Consultar `README_scraper_electoral.md` para documentación completa


