# 🧲 Option Magnets

Monitor casero de **imanes de open interest**, **GEX** y **volúmenes inusuales**
en opciones, con datos públicos (yfinance / Yahoo Finance). Guarda un snapshot
por día y te deja ver cómo se **construyen o deshacen** los imanes en el tiempo —
que es justo lo que Nasdaq en línea NO te muestra.

## Qué hace

- **collect.py** — baja la cadena completa de opciones de tus tickers, calcula
  delta/gamma/GEX y guarda un snapshot con fecha en `options.db` (SQLite).
- **analyze.py** — funciones de análisis (imanes, inusuales, GEX, evolución de OI).
- **dashboard.py** — dashboard visual (Streamlit) con 4 vistas:
  1. Imanes: OI por strike (calls arriba, puts abajo), con el spot marcado.
  2. Perfil GEX: dónde los dealers amortiguan (imán de reposo) o aceleran.
  3. Volúmenes inusuales: Vol/OI alto = aperturas frescas, con filtros.
  4. Evolución del imán: cuánto creció/cayó el OI por strike entre dos días.

## Instalación (local)

```bash
pip install -r requirements.txt
```

## Uso

```bash
# 1) Recolectar un snapshot (córrelo después del cierre, ~4:15pm ET)
python collect.py META            # o varios:  python collect.py META NVDA AAPL

# 2) Ver el dashboard
streamlit run dashboard.py
```

La primera corrida crea `options.db`. Cada corrida agrega un snapshot nuevo.
Necesitas **al menos 2 días** de snapshots para ver la vista de "evolución del imán".

> ¿Solo quieres probar el dashboard sin conexión? Corre `python seed_demo.py`
> para sembrar 3 días de datos sintéticos, y luego `streamlit run dashboard.py`.
> (Borra `options.db` antes de empezar a recolectar datos reales.)

## Notas importantes sobre los datos

- El **Open Interest** (tus imanes) se actualiza **una vez al día**. Con una
  corrida diaria basta para imanes. Corre más seguido solo si quieres seguir el
  **volumen** intradía.
- Yahoo entrega datos con ~15 min de retraso. Suficiente para imanes; no sirve
  para flujo en tiempo real tipo Unusual Whales (eso necesita el feed OPRA, caro).
- La **dirección** del volumen (comprado en ask vs vendido en bid) NO viene en
  yfinance. Vol/OI alto te marca aperturas frescas, pero no si son compra o venta.
  Esa es la pieza que UW tiene y esta herramienta no. Para el 80% del valor
  (imanes + aperturas OTM), no la necesitas.

## Automatización GRATIS en la nube

### Opción A — GitHub Actions (recomendada, gratis)
1. Sube esta carpeta a un repo de GitHub.
2. Copia `github_action_example.yml` a `.github/workflows/collect.yml`.
3. Listo: corre solo de lunes a viernes tras el cierre y guarda `options.db`
   actualizado en el repo. Puedes correrlo a mano desde la pestaña *Actions*.

### Opción B — Dashboard online gratis (Streamlit Community Cloud)
1. Con el repo ya en GitHub, entra a **share.streamlit.io**, conéctalo y apunta
   a `dashboard.py`. Te da una URL pública gratis.
2. Combínalo con la Opción A: la Action actualiza `options.db` en el repo, y el
   dashboard en Streamlit Cloud lo lee. Tienes recolección + visualización, todo
   gratis, sin tu PC encendido.

### Otras opciones de scheduling gratis
- **PythonAnywhere** (free tier): permite 1 tarea programada diaria.
- **Deta Space / Railway / Render**: cron jobs con capa gratuita (revisa límites).
- **Tu propia PC**: `cron` (Mac/Linux) o Task Scheduler (Windows).

## Ideas para extender

- Alertas: si el Δ OI de un strike supera un umbral, manda un mensaje a Telegram
  (API gratis) o email.
- Más tickers en la watchlist (edita `collect.py` o pásalos por línea de comandos).
- Migrar a **Polygon.io** (~$30/mes) cuando quieras OI histórico confiable,
  griegas oficiales y menos rate-limits que Yahoo.
- Guardar el "max pain" por vencimiento (el strike que minimiza el valor total
  de las opciones — otro tipo de imán).

## Descargo

Herramienta educativa. No es asesoría financiera. Los datos de Yahoo pueden traer
huecos o errores; valida antes de operar con esto.

---

## Novedades v2 — vistas tipo GEXBot

El dashboard ahora tiene **3 pestañas**:

1. **🫧 Mapa de burbujas (intradía)** — tipo "Interval Map" de GEXBot. Eje X =
   hora, eje Y = strike, tamaño de burbuja = magnitud de la apuesta (GEX u OI
   neto), color = signo. La línea blanca es el spot. Burbujas grandes y
   persistentes = imanes. **Requiere varios snapshots en el mismo día**: corre
   `collect.py` cada N minutos durante la sesión (ver abajo).

2. **🧱 Muros y gamma** — versión honesta del "Exposure Forecast". Marca el
   **call wall** (resistencia), el **put wall** (soporte) y el perfil de GEX
   horizontal. NO proyecta el futuro con un cono (eso es modelo propietario de
   esas plataformas); te da la estructura real, que es lo accionable.

3. **📊 Imanes / inusuales / evolución** — lo de la v1: OI por strike, tabla de
   Vol/OI alto, y evolución del OI entre días.

### Watchlist configurable
Edita **watchlist.txt** (un ticker por línea). `collect.py` la lee sola.

### Para el mapa intradía: correr varias veces al día
El OI es fijo durante el día, pero el GEX se mueve con el spot. Para poblar el
eje intradía, programa `collect.py` cada 15-30 min en horario de mercado. En la
GitHub Action, cambia el cron a algo como:

```yaml
    - cron: "*/30 13-20 * * 1-5"   # cada 30 min, ~9:30am-4pm ET (en UTC)
```

> Demo: `python seed_intraday.py` siembra un día con 9 timestamps para que veas
> el mapa de burbujas funcionando. Abre **preview_bubble.html** en tu navegador
> para una vista previa sin levantar nada.

### Límite honesto sobre el "cono de pronóstico"
Las imágenes de GEXBot/TrendSpider que proyectan el precio hacia +30m/+1h/+2h
usan un modelo predictivo propietario. Esta herramienta **no** lo replica: te da
la estructura real (muros, gamma, imanes y su evolución), que es el insumo
honesto. Proyectar el precio sería inventar; preferimos no hacerlo.
