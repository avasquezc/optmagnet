"""
dashboard.py — Dashboard integrado.  Corre con:  streamlit run dashboard.py
Vistas: mapa de burbujas intradía, muros+gamma, e imanes/inusuales/evolución.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import analyze as A
from gh_trigger import trigger_collection

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
metric = c4.selectbox("Métrica del mapa", ["gex", "oi"],
                      format_func=lambda m: "GEX (gamma)" if m == "gex" else "OI neto")

tss = A.list_timestamps(ticker, snap_date)
df_last = A.load_ts(ticker, tss[-1], expiration) if tss else A.load(ticker, snap_date, expiration)
spot = A.spot_of(df_last)
if spot:
    st.metric("Spot (último snapshot del día)", f"${spot:,.2f}")
lo, hi = (spot * 0.9, spot * 1.12) if spot else (0, 1)

tab1, tab2, tab3 = st.tabs(["🫧 Mapa de burbujas (intradía)",
                            "🧱 Muros y gamma", "📊 Imanes / inusuales / evolución"])

with tab1:
    st.caption("Cada burbuja = magnitud de la apuesta en ese strike (tamaño) y signo "
               "(verde positivo, rojo negativo). Línea blanca = spot. Burbujas grandes "
               "y persistentes = imanes.")
    bm = A.bubble_map_data(ticker, snap_date, expiration, metric=metric)
    if bm.empty:
        st.info("Necesitas varios timestamps intradía en este día (corre collect.py "
                "varias veces al día, o usa la demo intradía).")
    else:
        bm = bm[(bm.strike >= lo) & (bm.strike <= hi)].copy()
        bm["abs_mag"] = bm["magnitude"].abs()
        maxmag = bm["abs_mag"].max() or 1
        bm["size"] = 6 + 40 * (bm["abs_mag"] / maxmag)
        bm["color"] = bm["magnitude"].apply(lambda v: "#2ecc71" if v >= 0 else "#e74c3c")
        bm["hora"] = pd.to_datetime(bm["ts"]).dt.strftime("%H:%M")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=bm["hora"], y=bm["strike"], mode="markers",
            marker=dict(size=bm["size"], color=bm["color"], line=dict(width=0), opacity=0.75),
            text=bm["magnitude"].round(0),
            hovertemplate="hora %{x}<br>strike %{y}<br>mag %{text}<extra></extra>",
            name="apuestas"))
        spot_line = bm.drop_duplicates("ts")[["hora", "spot"]]
        fig.add_trace(go.Scatter(
            x=spot_line["hora"], y=spot_line["spot"], mode="lines+markers",
            line=dict(color="white", width=2), name="spot"))
        fig.update_layout(height=560, xaxis_title="Hora", yaxis_title="Strike",
                          plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                          font_color="white", legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    if df_last.empty:
        st.info("Sin datos.")
    else:
        w = A.walls(df_last)
        cA, cB, cC = st.columns(3)
        cA.metric("Call wall (resistencia)", f"{int(w['call_wall'])}" if w['call_wall'] else "—")
        cB.metric("Put wall (soporte)", f"{int(w['put_wall'])}" if w['put_wall'] else "—")
        cC.metric("Spot", f"${spot:,.2f}" if spot else "—")
        gex = A.gex_recalc_at_spot(df_last, spot, snap_date)
        gexw = gex[(gex.strike >= lo) & (gex.strike <= hi)]
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in gexw.gex]
        fig = go.Figure()
        fig.add_bar(y=gexw.strike, x=gexw.gex, orientation="h", marker_color=colors)
        fig.add_hline(y=spot, line_dash="dash", line_color="white",
                      annotation_text=f"spot {spot:.0f}")
        if w["call_wall"]:
            fig.add_hline(y=w["call_wall"], line_color="#2ecc71", annotation_text="call wall")
        if w["put_wall"]:
            fig.add_hline(y=w["put_wall"], line_color="#e74c3c", annotation_text="put wall")
        fig.update_layout(height=560, xaxis_title="GEX neto", yaxis_title="Strike",
                          plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="white")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("GEX positivo (verde) = dealers amortiguan (imán de reposo). "
                   "Cruce a negativo (rojo) = zona de aceleración. Muros = mayor OI call/put.")

with tab3:
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
