"""
analyze.py — Funciones de análisis sobre los snapshots guardados.
Las usa el dashboard, pero también puedes importarlas en un notebook.
"""
import sqlite3
import pandas as pd

DB_PATH = "options.db"


def _conn():
    return sqlite3.connect(DB_PATH)


def list_tickers():
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT ticker FROM snapshots ORDER BY ticker")]


def list_snap_dates(ticker):
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT snap_date FROM snapshots WHERE ticker=? ORDER BY snap_date DESC",
            (ticker,))]


def list_expirations(ticker, snap_date):
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT expiration FROM snapshots WHERE ticker=? AND snap_date=? "
            "ORDER BY expiration", (ticker, snap_date))]


def load(ticker, snap_date, expiration=None):
    q = "SELECT * FROM snapshots WHERE ticker=? AND snap_date=?"
    params = [ticker, snap_date]
    if expiration:
        q += " AND expiration=?"
        params.append(expiration)
    with _conn() as c:
        df = pd.read_sql_query(q, c, params=params)
    return df


def spot_of(df):
    return float(df["spot"].iloc[0]) if len(df) else None


def magnet_table(df):
    """OI por strike (call, put, total) — el pico es el imán."""
    piv = df.pivot_table(index="strike", columns="type",
                         values="open_interest", aggfunc="sum", fill_value=0)
    piv = piv.rename(columns={"C": "call_oi", "P": "put_oi"})
    for col in ("call_oi", "put_oi"):
        if col not in piv:
            piv[col] = 0
    piv["total_oi"] = piv["call_oi"] + piv["put_oi"]
    return piv.reset_index().sort_values("strike")


def unusual_volume(df, min_ratio=5.0, min_vol=500):
    """Filas con Vol/OI alto = aperturas frescas candidatas."""
    d = df.copy()
    d["vol_oi"] = d["volume"] / d["open_interest"].replace(0, pd.NA)
    d = d[(d["vol_oi"] >= min_ratio) & (d["volume"] >= min_vol)]
    cols = ["expiration", "type", "strike", "volume", "open_interest",
            "vol_oi", "last", "iv", "delta"]
    return d[cols].sort_values("vol_oi", ascending=False)


def gex_profile(df):
    """GEX neto por strike (calls positivos, puts negativos ya vienen signed)."""
    g = df.groupby("strike")["gex"].sum().reset_index()
    return g.sort_values("strike")


def oi_change(ticker, expiration, date_new, date_old):
    """Variación de OI por strike entre dos fechas: imanes construyéndose/deshaciéndose."""
    a = load(ticker, date_old, expiration)
    b = load(ticker, date_new, expiration)
    if a.empty or b.empty:
        return pd.DataFrame()
    ga = a[a.type == "C"].groupby("strike")["open_interest"].sum()
    gb = b[b.type == "C"].groupby("strike")["open_interest"].sum()
    out = pd.DataFrame({"oi_old": ga, "oi_new": gb}).fillna(0)
    out["delta_oi"] = out["oi_new"] - out["oi_old"]
    return out.reset_index().sort_values("delta_oi", ascending=False)


# ---------------------------------------------------------------------------
# NUEVO: soporte intradía y vistas tipo GEXBot
# ---------------------------------------------------------------------------
import math
from scipy.stats import norm
RISK_FREE = 0.04


def list_timestamps(ticker, snap_date):
    """Todos los timestamps (corridas) de un día — para el eje intradía."""
    with _conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT ts FROM snapshots WHERE ticker=? AND snap_date=? "
            "ORDER BY ts", (ticker, snap_date))]


def load_ts(ticker, ts, expiration=None):
    """Carga un snapshot por timestamp exacto (una corrida intradía)."""
    q = "SELECT * FROM snapshots WHERE ticker=? AND ts=?"
    params = [ticker, ts]
    if expiration:
        q += " AND expiration=?"
        params.append(expiration)
    with _conn() as c:
        return pd.read_sql_query(q, c, params=params)


def _gamma_at(spot, strike, t_years, iv):
    if t_years <= 0 or not iv or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    try:
        d1 = (math.log(spot / strike) + (RISK_FREE + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
        return norm.pdf(d1) / (spot * iv * math.sqrt(t_years))
    except (ValueError, ZeroDivisionError):
        return 0.0


def gex_recalc_at_spot(df, spot_override, snap_date):
    """
    Recalcula el GEX por strike usando un spot dado (para intradía: el OI es fijo
    del día, pero el GEX cambia con el spot). Devuelve GEX neto por strike.
    """
    import datetime as dt
    today = dt.date.fromisoformat(snap_date)
    out = {}
    for _, r in df.iterrows():
        exp = dt.date.fromisoformat(r["expiration"])
        t_years = max((exp - today).days, 0) / 365.0
        g = _gamma_at(spot_override, r["strike"], t_years, r["iv"])
        sign = 1.0 if r["type"] == "C" else -1.0
        gex = sign * g * (r["open_interest"] or 0) * 100 * spot_override**2 * 0.01
        out[r["strike"]] = out.get(r["strike"], 0.0) + gex
    g = pd.DataFrame({"strike": list(out.keys()), "gex": list(out.values())})
    return g.sort_values("strike")


def walls(df):
    """Call wall = mayor call OI POR ENCIMA del spot (resistencia).
       Put wall = mayor put OI POR DEBAJO del spot (soporte)."""
    spot = float(df["spot"].iloc[0]) if len(df) else None
    calls = df[df.type == "C"].groupby("strike")["open_interest"].sum()
    puts = df[df.type == "P"].groupby("strike")["open_interest"].sum()
    # call wall: solo strikes >= spot
    if spot is not None:
        calls_above = calls[calls.index >= spot]
        puts_below = puts[puts.index <= spot]
    else:
        calls_above, puts_below = calls, puts
    call_wall = calls_above.idxmax() if len(calls_above) and calls_above.max() > 0 else None
    put_wall = puts_below.idxmax() if len(puts_below) and puts_below.max() > 0 else None
    return {"call_wall": call_wall, "put_wall": put_wall}


def bubble_map_data(ticker, snap_date, expiration=None, metric="gex", volume_mode="new"):
    """
    Datos para el mapa de burbujas. metric: 'gex', 'oi' o 'volume'.
    Para 'volume' incluye columna 'side' (C/P) para colorear por tipo.
    volume_mode (solo aplica a metric='volume'):
      - 'new': volumen NUEVO por franja (delta vs corrida anterior). Detecta flujo fresco.
      - 'cumulative': volumen acumulado tal cual lo reporta la fuente.
    """
    tss = list_timestamps(ticker, snap_date)
    frames = []
    for ts in tss:
        d = load_ts(ticker, ts, expiration)
        if d.empty:
            continue
        spot = float(d["spot"].iloc[0])
        if metric == "gex":
            g = gex_recalc_at_spot(d, spot, snap_date)
            g["magnitude"] = g["gex"]
            g["side"] = "net"
        elif metric == "volume":
            g = d.groupby(["strike", "type"])["volume"].sum().reset_index()
            g = g.rename(columns={"volume": "magnitude", "type": "side"})
        else:  # oi neto
            g = d.groupby("strike").apply(
                lambda x: (x[x.type=="C"]["open_interest"].sum()
                           - x[x.type=="P"]["open_interest"].sum())
            ).reset_index(name="magnitude")
            g["side"] = "net"
        g["ts"] = ts
        g["spot"] = spot
        frames.append(g[["ts", "strike", "magnitude", "spot", "side"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)

    # Volumen NUEVO por franja: delta contra la corrida anterior, por strike+side.
    if metric == "volume" and volume_mode == "new":
        out = out.sort_values("ts")
        # volumen previo por (strike, side)
        out["prev"] = out.groupby(["strike", "side"])["magnitude"].shift(1)
        # primera corrida del día: no hay previo -> el acumulado ES lo nuevo hasta ese punto
        out["delta"] = out["magnitude"] - out["prev"].fillna(0)
        # deltas negativos = dato sucio de la fuente (el volumen no puede bajar). Los anulamos.
        out["delta"] = out["delta"].clip(lower=0)
        out["magnitude"] = out["delta"]
        out = out.drop(columns=["prev", "delta"])
    return out


def gamma_levels(df, snap_date):
    """
    Niveles clave de gamma para la pestaña de régimen de volatilidad:
    - gamma_flip: strike donde el GEX neto acumulado cruza de - a + (o el más cercano).
      Por encima: dealers amortiguan (estable). Por debajo: aceleran (volátil).
    - gex_peak: strike con mayor GEX positivo = imán de reposo real.
    """
    spot = float(df["spot"].iloc[0]) if len(df) else None
    g = gex_recalc_at_spot(df, spot, snap_date) if spot else gex_profile(df)
    g = g.sort_values("strike").reset_index(drop=True)
    if g.empty:
        return {"gamma_flip": None, "gex_peak": None}

    # pico de gamma positiva
    pos = g[g["gex"] > 0]
    gex_peak = pos.loc[pos["gex"].idxmax(), "strike"] if len(pos) else None

    # gamma flip: primer strike (de abajo hacia arriba) donde el gex pasa de <=0 a >0
    flip = None
    vals = g["gex"].values
    strikes = g["strike"].values
    for i in range(1, len(vals)):
        if vals[i - 1] <= 0 and vals[i] > 0:
            # interpola linealmente entre los dos strikes para el cruce
            x0, x1 = strikes[i - 1], strikes[i]
            y0, y1 = vals[i - 1], vals[i]
            flip = x0 + (x1 - x0) * (0 - y0) / (y1 - y0) if (y1 - y0) else x1
            break
    return {"gamma_flip": flip, "gex_peak": gex_peak}


def load_price_history(ticker, snap_date):
    """Velas intradía del subyacente para un día. Vacío si no hay."""
    with _conn() as c:
        try:
            return pd.read_sql_query(
                "SELECT * FROM price_history WHERE ticker=? AND snap_date=? ORDER BY bar_time",
                c, params=[ticker, snap_date])
        except Exception:
            return pd.DataFrame()


def heatmap_data(ticker, snap_date, expiration=None, volume_mode="new"):
    """
    Datos para el heatmap de volumen + burbujas grandes.
    Devuelve un DataFrame largo con: ts, strike, vol_call, vol_put, vol_total, net
    (net = vol_call - vol_put, para el color divergente).
    Respeta volume_mode ('new' = flujo por franja, 'cumulative' = acumulado).
    """
    tss = list_timestamps(ticker, snap_date)
    frames = []
    for ts in tss:
        d = load_ts(ticker, ts, expiration)
        if d.empty:
            continue
        spot = float(d["spot"].iloc[0])
        piv = d.pivot_table(index="strike", columns="type", values="volume",
                            aggfunc="sum", fill_value=0).reset_index()
        for col in ("C", "P"):
            if col not in piv:
                piv[col] = 0
        piv = piv.rename(columns={"C": "vol_call", "P": "vol_put"})
        piv["ts"] = ts
        piv["spot"] = spot
        frames.append(piv[["ts", "strike", "vol_call", "vol_put", "spot"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).sort_values("ts")

    # modo 'new': delta por franja para cada (strike) en call y put por separado
    if volume_mode == "new":
        for col in ("vol_call", "vol_put"):
            out[col + "_prev"] = out.groupby("strike")[col].shift(1)
            out[col] = (out[col] - out[col + "_prev"].fillna(0)).clip(lower=0)
            out = out.drop(columns=[col + "_prev"])

    out["vol_total"] = out["vol_call"] + out["vol_put"]
    out["net"] = out["vol_call"] - out["vol_put"]
    return out
