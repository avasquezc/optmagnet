"""
dashboard.py — Dashboard integrado.  Corre con:  streamlit run dashboard.py
Vistas: mapa de burbujas intradía, muros+gamma, e imanes/inusuales/evolución.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyze as A
from gh_trigger import trigger_collection
from zoneinfo import ZoneInfo

CHILE_TZ = ZoneInfo("America/Santiago")  # maneja UTC-3/UTC-4 automáticamente

def to_chile(ts_series):
    """Convierte timestamps a hora de Chile, tolerante a formatos mixtos
    (naive viejos y UTC nuevos). Los naive se asumen en UTC."""
    # format="mixed" + utc=True maneja tanto '2026-09-15T20:30:00' como
    # '2026-09-15T20:30:00+00:00' en la misma columna sin reventar.
    t = pd.to_datetime(ts_series, utc=True, format="mixed", errors="coerce")
    return t.dt.tz_convert(CHILE_TZ)

st.set_page_config(page_title="Option Magnets", layout="wide")

# --- Cabecera con botón de actualización ---
hcol1, hcol2 = st.columns([4, 1])
hcol1.title("🧲 Option Magnets")
with hcol2:
    st.write("")  # espaciador
    if st.button("🔄 Actualizar datos", use_container_width=True,
                 help="Dispara la recolección en GitHub Actions"):
        with st.spinner("Disparando recolección..."):
            ok, msg = trigger_collection()
        (st.success if ok else st.error)(msg)

with st.sidebar:
    st.header("ℹ️ Cómo funciona")
    st.markdown(
        "- Los datos se recolectan solos cada 30 min en horario de mercado "
        "(vía GitHub Actions).\n"
        "- El botón **Actualizar datos** fuerza una recolección ahora.\n"
        "- Para cambiar los tickers, edita `watchlist.txt` en el repo.\n"
        "- El OI se actualiza 1 vez al día; el GEX se mueve con el spot intradía."
    )

tickers = A.list_tickers()
if not tickers:
    st.warning("No hay datos. Corre `python collect.py` (o `python seed_intraday.py` para demo).")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
ticker = c1.selectbox("Ticker", tickers)
dates = A.list_snap_dates(ticker)
snap_date = c2.selectbox("Fecha", dates)
exps = A.list_expirations(ticker, snap_date)
expiration = c3.selectbox("Vencimiento", exps if exps else ["—"])
metric = c4.selectbox("Métrica del mapa", ["gex", "oi", "volume"],
                      format_func=lambda m: {"gex":"GEX (gamma)","oi":"OI neto",
                                             "volume":"Volumen"}[m])

tss = A.list_timestamps(ticker, snap_date)
df_last = A.load_ts(ticker, tss[-1], expiration) if tss else A.load(ticker, snap_date, expiration)
spot = A.spot_of(df_last)
if spot:
    st.metric("Spot (último snapshot del día)", f"${spot:,.2f}")
lo, hi = (spot * 0.9, spot * 1.12) if spot else (0, 1)


# --- Leyenda explicativa de las métricas ---
with st.expander("📖 ¿Qué significa cada métrica? (léeme)"):
    st.markdown("""
**GEX (Gamma Exposure)** — mide la *pared de gamma* de los dealers en cada strike.
Se calcula con gamma × open interest × spot². Es máximo cerca del spot.
→ **Úsalo para:** ver dónde el precio tiende a *reposar* (GEX+ alto = imán de reposo,
los dealers amortiguan) o a *acelerar* (GEX−). Cambia poco intradía.

**OI neto (Open Interest neto)** — call OI menos put OI por strike. Es el *dinero
asentado*: contratos que se quedaron abiertos, acumulados día tras día.
→ **Úsalo para:** identificar el *imán estructural* — dónde el mercado tiene más
posición puesta. Se actualiza 1 vez al día, así que su evolución interesante es
**entre días** (pestaña de evolución).

**Volumen** — contratos negociados *hoy* en cada strike (calls en verde, puts en rojo).
Es *flujo fresco*, no posición asentada.
→ **Úsalo para:** cazar las *apuestas nuevas del día* — es la métrica que más cambia
intradía y la que mejor aprovecha el eje temporal. Mucho volumen donde hay poco OI =
apertura fresca (posible nuevo imán construyéndose).

**Regla rápida:** OI/GEX = *dónde está el dinero asentado* (imán lento).
Volumen = *dónde está entrando el flujo hoy* (apuesta rápida).
""")

tab1, tab2, tab3 = st.tabs(["🫧 Mapa de burbujas (intradía)",
                            "🧱 Muros y gamma", "📊 Imanes / inusuales / evolución"])

with tab1:
    st.caption("📖 Esta vista muestra la **evolución en el tiempo**. Es la *película*: "
               "cómo cambia el posicionamiento durante el día. Con métrica=Volumen ves "
               "entrar el flujo fresco strike por strike. Burbuja = magnitud; línea blanca = spot.")
    bm = A.bubble_map_data(ticker, snap_date, expiration, metric=metric)
    if bm.empty:
        st.info("Necesitas varios timestamps intradía en este día (corre collect.py "
                "varias veces al día, o usa la demo intradía).")
    else:
        bm = bm[(bm.strike >= lo) & (bm.strike <= hi)].copy()
        bm["abs_mag"] = bm["magnitude"].abs()
        maxmag = bm["abs_mag"].max() or 1
        bm["size"] = 6 + 40 * (bm["abs_mag"] / maxmag)
        bm["hora"] = to_chile(bm["ts"]).dt.strftime("%H:%M")
        fig = go.Figure()

        if metric == "volume":
            # calls verde, puts rojo (Opción A)
            for side, color, name in (("C", "#2ecc71", "Vol calls"),
                                      ("P", "#e74c3c", "Vol puts")):
                sub = bm[bm["side"] == side]
                if len(sub):
                    fig.add_trace(go.Scatter(
                        x=sub["hora"], y=sub["strike"], mode="markers",
                        marker=dict(size=sub["size"], color=color,
                                    line=dict(width=0), opacity=0.65),
                        text=sub["magnitude"].round(0),
                        hovertemplate=name+" %{text}<br>hora %{x}<br>strike %{y}<extra></extra>",
                        name=name))
        else:
            # gex / oi neto: verde positivo, rojo negativo
            bm["color"] = bm["magnitude"].apply(lambda v: "#2ecc71" if v >= 0 else "#e74c3c")
            fig.add_trace(go.Scatter(
                x=bm["hora"], y=bm["strike"], mode="markers",
                marker=dict(size=bm["size"], color=bm["color"], line=dict(width=0), opacity=0.75),
                text=bm["magnitude"].round(0),
                hovertemplate="hora %{x}<br>strike %{y}<br>mag %{text}<extra></extra>",
                name="magnitud"))

        spot_line = bm.drop_duplicates("ts")[["hora", "spot"]]
        fig.add_trace(go.Scatter(
            x=spot_line["hora"], y=spot_line["spot"], mode="lines+markers",
            line=dict(color="white", width=2), name="spot"))
        fig.update_layout(height=560, xaxis_title="Hora", yaxis_title="Strike",
                          plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                          font_color="white", legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        if metric == "volume":
            st.caption("🟢 verde = volumen de calls · 🔴 rojo = volumen de puts. "
                       "Burbuja grande donde el OI es chico = apuesta fresca del día.")

with tab2:
    st.caption("📖 Esta vista mide el **régimen de volatilidad** vía GEX (gamma). "
               "Te dice si el precio está en zona donde tiende a *quedarse quieto* "
               "o a *acelerar*. Distinto de la pestaña de imanes (que mide dónde está el dinero).")
    if df_last.empty:
        st.info("Sin datos.")
    else:
        lv = A.gamma_levels(df_last, snap_date)
        cA, cB, cC = st.columns(3)
        cA.metric("Pico de gamma (imán de reposo)",
                  f"{int(lv['gex_peak'])}" if lv['gex_peak'] else "—")
        cB.metric("Gamma flip (cambio de régimen)",
                  f"{lv['gamma_flip']:.0f}" if lv['gamma_flip'] else "—")
        cC.metric("Spot", f"${spot:,.2f}" if spot else "—")

        gex = A.gex_recalc_at_spot(df_last, spot, snap_date)
        gexw = gex[(gex.strike >= lo) & (gex.strike <= hi)]
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in gexw.gex]
        fig = go.Figure()
        fig.add_bar(y=gexw.strike, x=gexw.gex, orientation="h", marker_color=colors)
        fig.add_hline(y=spot, line_dash="dash", line_color="white",
                      annotation_text=f"spot {spot:.0f}", annotation_font_color="white")
        if lv["gamma_flip"]:
            fig.add_hline(y=lv["gamma_flip"], line_color="#f1c40f", line_width=3,
                          annotation_text="⚡ GAMMA FLIP",
                          annotation_font_color="#f1c40f")
        if lv["gex_peak"]:
            fig.add_hline(y=lv["gex_peak"], line_color="#9b59b6", line_width=2,
                          line_dash="dot", annotation_text="🧲 pico gamma",
                          annotation_font_color="#9b59b6")
        fig.update_layout(height=560, xaxis_title="GEX neto (verde=+, rojo=−)",
                          yaxis_title="Strike", plot_bgcolor="#0e1117",
                          paper_bgcolor="#0e1117", font_color="white")
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
- **Barras verdes (GEX+)**: dealers amortiguan → el precio tiende a reposar. Zona estable.
- **Barras rojas (GEX−)**: dealers aceleran → los movimientos se amplifican. Zona volátil.
- **⚡ Gamma flip (amarillo)**: la frontera. Si el spot está *encima*, régimen estable; si cae *debajo*, la volatilidad se dispara.
- **🧲 Pico de gamma (morado)**: el strike que más atrae al precio a reposar.
""")

with tab3:
    st.caption("📖 Esta vista mide **dónde está el dinero asentado** (open interest). "
               "Es el *mapa del terreno*: dónde el mercado tiene más posición acumulada "
               "y hacia dónde gravita el precio. Cambia lento (1 vez al día).")
    st.subheader("Imanes — OI por strike")
    mag = A.magnet_table(df_last)
    magw = mag[(mag.strike >= lo) & (mag.strike <= hi)]
    fig = go.Figure()
    fig.add_bar(x=magw.strike, y=magw.call_oi, name="Call OI", marker_color="#2ecc71")
    fig.add_bar(x=magw.strike, y=-magw.put_oi, name="Put OI", marker_color="#e74c3c")
    if spot:
        fig.add_vline(x=spot, line_dash="dash", line_color="white")
    fig.update_layout(barmode="relative", height=340, xaxis_title="Strike",
                      yaxis_title="OI", legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Volúmenes inusuales (Vol/OI alto)")
    cc1, cc2 = st.columns(2)
    min_ratio = cc1.slider("Vol/OI mínimo", 2.0, 30.0, 5.0, 0.5)
    min_vol = cc2.slider("Volumen mínimo", 100, 5000, 500, 100)
    dfall = A.load_ts(ticker, tss[-1]) if tss else A.load(ticker, snap_date)
    unu = A.unusual_volume(dfall, min_ratio, min_vol)
    if len(unu):
        show = unu.copy(); show["vol_oi"] = show["vol_oi"].round(1)
        st.dataframe(show, use_container_width=True, height=260)
    else:
        st.info("Nada supera el umbral.")

    st.subheader("Evolución del imán (multidía)")
    if len(dates) >= 2 and expiration not in ("—", None):
        d1, d2 = st.columns(2)
        date_new = d1.selectbox("Fecha nueva", dates, index=0, key="dn")
        date_old = d2.selectbox("Fecha vieja", dates, index=min(1, len(dates)-1), key="do")
        chg = A.oi_change(ticker, expiration, date_new, date_old)
        if len(chg):
            chgw = chg[(chg.strike >= lo) & (chg.strike <= hi)]
            colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in chgw.delta_oi]
            figc = go.Figure()
            figc.add_bar(x=chgw.strike, y=chgw.delta_oi, marker_color=colors)
            if spot:
                figc.add_vline(x=spot, line_dash="dash", line_color="white")
            figc.update_layout(height=320, xaxis_title="Strike",
                               yaxis_title="Δ OI (verde=creciendo)")
            st.plotly_chart(figc, use_container_width=True)
        else:
            st.info("Sin datos comparables.")
    else:
        st.info("Necesitas ≥2 fechas y un vencimiento específico.")
