"""
dashboard.py — Option Magnets. Corre con:  streamlit run dashboard.py
Compara dos tickers (Ticker 1 / Ticker 2) emparejados por métrica en cada pestaña.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyze as A
from gh_trigger import trigger_collection
from zoneinfo import ZoneInfo

CHILE_TZ = ZoneInfo("America/Santiago")  # maneja UTC-3/UTC-4 automáticamente


def to_chile(ts_series):
    """Convierte timestamps a hora de Chile, tolerante a formatos mixtos."""
    t = pd.to_datetime(ts_series, utc=True, format="mixed", errors="coerce")
    return t.dt.tz_convert(CHILE_TZ)


st.set_page_config(page_title="Option Magnets", layout="wide")

# ---- Cabecera con botón ----
hcol1, hcol2 = st.columns([4, 1])
hcol1.title("🧲 Option Magnets")
with hcol2:
    st.write("")
    if st.button("🔄 Actualizar datos", use_container_width=True,
                 help="Dispara la recolección en GitHub Actions"):
        with st.spinner("Disparando recolección..."):
            ok, msg = trigger_collection()
        (st.success if ok else st.error)(msg)

with st.sidebar:
    st.header("ℹ️ Cómo funciona")
    st.markdown(
        "- Los datos se recolectan solos cada 30 min en horario de mercado.\n"
        "- El botón **Actualizar datos** fuerza una recolección ahora.\n"
        "- Compara dos tickers: elige **Ticker 1** y **Ticker 2** arriba.\n"
        "- Para cambiar la lista, edita `watchlist.txt` en el repo."
    )

# ---- Selectores globales: Ticker 1, Ticker 2, fecha, vencimiento, métrica ----
tickers = A.list_tickers()
if not tickers:
    st.warning("No hay datos. Corre `python collect.py` (o `seed_intraday.py` para demo).")
    st.stop()

NONE = "— Ninguno —"
c1, c2, c3, c4, c5 = st.columns(5)
# Ticker 1 por defecto META si existe
t1_default = tickers.index("META") if "META" in tickers else 0
ticker1 = c1.selectbox("Ticker 1", tickers, index=t1_default)
# Ticker 2 por defecto QQQ si existe, con opción Ninguno
t2_opts = [NONE] + tickers
t2_default = t2_opts.index("QQQ") if "QQQ" in tickers else 0
ticker2 = c2.selectbox("Ticker 2", t2_opts, index=t2_default)
ticker2 = None if ticker2 == NONE else ticker2

# Fecha y vencimiento: usamos las del Ticker 1 como referencia común
dates = A.list_snap_dates(ticker1)
snap_date = c3.selectbox("Fecha", dates)
exps = A.list_expirations(ticker1, snap_date)
expiration = c4.selectbox("Vencimiento", exps if exps else ["—"])
metric = c5.selectbox("Métrica del mapa", ["gex", "oi", "volume"],
                      format_func=lambda m: {"gex": "GEX (gamma)", "oi": "OI neto",
                                             "volume": "Volumen"}[m])

# ---- Leyenda de métricas ----
with st.expander("📖 ¿Qué significa cada métrica? (léeme)"):
    st.markdown("""
**GEX (Gamma Exposure)** — pared de gamma de los dealers (gamma × OI × spot²). Máximo cerca del spot.
→ **Para:** ver dónde el precio *reposa* (GEX+ alto) o *acelera* (GEX−). Cambia poco intradía.

**OI neto** — call OI menos put OI. El *dinero asentado*, acumulado día a día.
→ **Para:** el *imán estructural* — dónde el mercado tiene más posición. Su evolución interesante es entre días.

**Volumen** — contratos negociados *hoy* (calls verde, puts rojo). *Flujo fresco*.
→ **Para:** cazar *apuestas nuevas del día*. Mucho volumen donde hay poco OI = apertura fresca.

**Regla:** OI/GEX = dónde está el dinero asentado (imán lento). Volumen = flujo entrando hoy (apuesta rápida).
""")


# ===========================================================================
# Funciones de render por métrica (reciben un ticker, dibujan su bloque)
# ===========================================================================
def _window(spot):
    return (spot * 0.9, spot * 1.12) if spot else (0, 1)


def render_bubble(ticker, key):
    import numpy as np
    tss = A.list_timestamps(ticker, snap_date)
    df_last = A.load_ts(ticker, tss[-1], expiration) if tss else A.load(ticker, snap_date, expiration)
    spot = A.spot_of(df_last)
    st.markdown(f"**{ticker}** · spot ${spot:,.2f}" if spot else f"**{ticker}**")
    vol_mode = st.session_state.get("_vol_mode", "new")

    # ---- Precio y volumen de la acción (común a todas las métricas) ----
    ph = A.load_price_history(ticker, snap_date)
    price_max = (ph["volume"].max() if not ph.empty and ph["volume"].max() else 1)

    fig = go.Figure()

    if metric == "volume":
        # ===== HEATMAP divergente + burbujas grandes =====
        hm = A.heatmap_data(ticker, snap_date, expiration, volume_mode=vol_mode)
        if hm.empty:
            st.info(f"Sin timestamps intradía para {ticker} en este día.")
            return
        lo, hi = _window(spot)
        hm = hm[(hm.strike >= lo) & (hm.strike <= hi)].copy()
        hm["dt"] = to_chile(hm["ts"])

        # --- Capa 1: heatmap. Color = net (calls - puts), intensidad = |net| ---
        # Construimos matriz strike x tiempo con el valor 'net'.
        pivot = hm.pivot_table(index="strike", columns="dt", values="net", aggfunc="sum", fill_value=0)
        # escala de color simétrica robusta (percentil 95 del |net|, sin 1ª franja)
        ts_cols = list(pivot.columns)
        if len(ts_cols) > 1:
            pool = hm[hm["dt"] != ts_cols[0]]["net"].abs()
        else:
            pool = hm["net"].abs()
        cmax = pool.quantile(0.95) if len(pool) else hm["net"].abs().max()
        cmax = cmax or 1
        fig.add_trace(go.Heatmap(
            z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
            zmid=0, zmin=-cmax, zmax=cmax,
            colorscale=[[0, "#c0392b"], [0.5, "#0e1117"], [1, "#27ae60"]],
            showscale=False, hoverongaps=False,
            hovertemplate="strike %{y}<br>%{x}<br>net %{z}<extra></extra>", name="heatmap"))

        # --- Capa 2: burbujas SOLO para el 15% más alto (p85) por volumen total ---
        big_pool = hm[hm["dt"] != ts_cols[0]]["vol_total"] if len(ts_cols) > 1 else hm["vol_total"]
        thr = big_pool.quantile(0.85) if len(big_pool) else 0
        big = hm[hm["vol_total"] >= max(thr, 1)].copy()
        if len(big):
            # Tamaño calibrado SOLO dentro del grupo de grandes, para maximizar el
            # contraste entre mediana / grande / muy grande. Usamos el mín y máx de las
            # grandes como extremos, con raíz cuadrada (contraste parejo) y rango amplio.
            vmin = big["vol_total"].min()
            vmax = big["vol_total"].quantile(0.97) or vmin  # recorta outlier extremo
            span = (vmax - vmin) or 1
            norm = ((big["vol_total"].clip(upper=vmax) - vmin) / span).clip(0, 1)
            # raíz cuadrada para que el crecimiento sea perceptible; rango 14→60
            big["size"] = 14 + 46 * np.sqrt(norm)
            # color por dirección dominante de esa celda
            big["color"] = np.where(big["net"] >= 0, "#2ecc71", "#e74c3c")
            fig.add_trace(go.Scatter(
                x=big["dt"], y=big["strike"], mode="markers",
                marker=dict(size=big["size"], color=big["color"], opacity=0.85,
                            line=dict(width=1, color="white")),
                name="apuesta grande", text=big["vol_total"].round(0),
                hovertemplate="VOL %{text}<br>strike %{y}<br>%{x}<extra></extra>"))
    else:
        # ===== GEX / OI neto: burbujas como antes =====
        bm = A.bubble_map_data(ticker, snap_date, expiration, metric=metric, volume_mode=vol_mode)
        if bm.empty:
            st.info(f"Sin timestamps intradía para {ticker} en este día.")
            return
        lo, hi = _window(spot)
        bm = bm[(bm.strike >= lo) & (bm.strike <= hi)].copy()
        bm["abs_mag"] = bm["magnitude"].abs()
        ts_sorted = sorted(bm["ts"].unique())
        pool = bm[bm["ts"] != ts_sorted[0]]["abs_mag"] if len(ts_sorted) > 1 else bm["abs_mag"]
        cap = (pool.quantile(0.95) if len(pool) else bm["abs_mag"].max()) or 1
        capped = bm["abs_mag"].clip(upper=cap)
        bm["size"] = 6 + 34 * (np.log1p(capped) / (np.log1p(cap) or 1))
        bm["dt"] = to_chile(bm["ts"])
        bm["color"] = bm["magnitude"].apply(lambda v: "#2ecc71" if v >= 0 else "#e74c3c")
        fig.add_trace(go.Scatter(x=bm["dt"], y=bm["strike"], mode="markers",
            marker=dict(size=bm["size"], color=bm["color"], opacity=0.75), name="magnitud",
            text=bm["magnitude"].round(0),
            hovertemplate="%{x}<br>strike %{y}<br>mag %{text}<extra></extra>"))

    # ---- Precio real + volumen de acción (todas las métricas) ----
    if not ph.empty:
        ph = ph.copy()
        ph["dt"] = to_chile(ph["bar_time"])
        fig.add_trace(go.Bar(x=ph["dt"], y=ph["volume"], name="Vol acción",
            marker_color="rgba(120,140,170,0.22)", yaxis="y2",
            hovertemplate="vol acción %{y}<br>%{x}<extra></extra>"))
        fig.add_trace(go.Scatter(x=ph["dt"], y=ph["close"], mode="lines",
            line=dict(color="white", width=2), name="precio",
            hovertemplate="precio %{y:.2f}<br>%{x}<extra></extra>"))

    fig.update_layout(height=460, yaxis_title="Strike",
        xaxis=dict(title="Hora", type="date", tickformat="%H:%M"),
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="white",
        legend=dict(orientation="h"), margin=dict(t=10, b=10),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Vol acción",
                    rangemode="tozero", range=[0, price_max * 3]))
    st.plotly_chart(fig, use_container_width=True, key=f"bubble_{key}")


def render_gamma(ticker, key):
    tss = A.list_timestamps(ticker, snap_date)
    df_last = A.load_ts(ticker, tss[-1], expiration) if tss else A.load(ticker, snap_date, expiration)
    spot = A.spot_of(df_last)
    if df_last.empty or not spot:
        st.info(f"Sin datos para {ticker}.")
        return
    lv = A.gamma_levels(df_last, snap_date)
    st.markdown(f"**{ticker}** · spot ${spot:,.2f} · "
                f"flip {lv['gamma_flip']:.0f} · pico {int(lv['gex_peak']) if lv['gex_peak'] else '—'}"
                if lv['gamma_flip'] else f"**{ticker}** · spot ${spot:,.2f}")
    lo, hi = _window(spot)
    gex = A.gex_recalc_at_spot(df_last, spot, snap_date)
    gexw = gex[(gex.strike >= lo) & (gex.strike <= hi)]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in gexw.gex]
    fig = go.Figure()
    fig.add_bar(y=gexw.strike, x=gexw.gex, orientation="h", marker_color=colors)
    fig.add_hline(y=spot, line_dash="dash", line_color="white",
                  annotation_text=f"spot {spot:.0f}", annotation_font_color="white")
    if lv["gamma_flip"]:
        fig.add_hline(y=lv["gamma_flip"], line_color="#f1c40f", line_width=3,
                      annotation_text="⚡ flip", annotation_font_color="#f1c40f")
    if lv["gex_peak"]:
        fig.add_hline(y=lv["gex_peak"], line_color="#9b59b6", line_width=2, line_dash="dot",
                      annotation_text="🧲 pico", annotation_font_color="#9b59b6")
    fig.update_layout(height=420, xaxis_title="GEX neto", yaxis_title="Strike",
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="white",
        margin=dict(t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, key=f"gamma_{key}")


def render_magnets(ticker, key):
    tss = A.list_timestamps(ticker, snap_date)
    df_last = A.load_ts(ticker, tss[-1], expiration) if tss else A.load(ticker, snap_date, expiration)
    spot = A.spot_of(df_last)
    if df_last.empty:
        st.info(f"Sin datos para {ticker}.")
        return
    w = A.walls(df_last)
    st.markdown(f"**{ticker}** · spot ${spot:,.2f} · "
                f"call wall {int(w['call_wall']) if w['call_wall'] else '—'} · "
                f"put wall {int(w['put_wall']) if w['put_wall'] else '—'}")
    lo, hi = _window(spot)
    mag = A.magnet_table(df_last)
    magw = mag[(mag.strike >= lo) & (mag.strike <= hi)]
    fig = go.Figure()
    fig.add_bar(x=magw.strike, y=magw.call_oi, name="Call OI", marker_color="#2ecc71")
    fig.add_bar(x=magw.strike, y=-magw.put_oi, name="Put OI", marker_color="#e74c3c")
    if spot:
        fig.add_vline(x=spot, line_dash="dash", line_color="white")
    fig.update_layout(barmode="relative", height=340, xaxis_title="Strike", yaxis_title="OI",
        legend=dict(orientation="h"), plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        font_color="white", margin=dict(t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, key=f"mag_{key}")
    # tabla de inusuales
    dfall = A.load_ts(ticker, tss[-1]) if tss else A.load(ticker, snap_date)
    unu = A.unusual_volume(dfall, 5.0, 500)
    if len(unu):
        show = unu.copy(); show["vol_oi"] = show["vol_oi"].round(1)
        st.dataframe(show, use_container_width=True, height=200)
    else:
        st.caption("Sin volúmenes inusuales (Vol/OI≥5, vol≥500).")


def paired(render_fn):
    """Dibuja render_fn para Ticker 1 y Ticker 2 (si hay), en columnas del mismo tamaño."""
    if ticker2:
        col1, col2 = st.columns(2)
        with col1:
            render_fn(ticker1, "t1")
        with col2:
            render_fn(ticker2, "t2")
    else:
        render_fn(ticker1, "t1")


# ===========================================================================
# Pestañas
# ===========================================================================
tab1, tab2, tab3 = st.tabs(["🫧 Mapa de burbujas (intradía)",
                            "🧱 Muros y gamma", "📊 Imanes / inusuales"])

with tab1:
    st.caption("📖 **La película**: evolución en el tiempo. Con métrica=Volumen ves entrar el "
               "flujo fresco. Los dos tickers, mismo tamaño, para comparar la evolución horaria.")
    if metric == "volume":
        vol_mode = st.radio("Modo de volumen", ["new", "cumulative"], horizontal=True,
            format_func=lambda m: "🆕 Nuevo por franja (flujo fresco)" if m == "new"
                                  else "Σ Acumulado del día",
            help="'Nuevo por franja' muestra cuánto volumen entró desde la corrida anterior — "
                 "detecta flujo fresco y evita la distorsión del acumulado sucio de la fuente.")
    else:
        vol_mode = "new"
    st.session_state["_vol_mode"] = vol_mode
    paired(render_bubble)

with tab2:
    st.caption("📖 **El clima**: régimen de volatilidad vía GEX. ⚡ Gamma flip = frontera "
               "estable/volátil. 🧲 Pico = imán de reposo. Verde = amortigua, rojo = acelera.")
    paired(render_gamma)

with tab3:
    st.caption("📖 **El terreno**: dónde está el dinero asentado (OI). Call wall = resistencia, "
               "put wall = soporte. La tabla lista los volúmenes inusuales (aperturas frescas).")
    paired(render_magnets)
