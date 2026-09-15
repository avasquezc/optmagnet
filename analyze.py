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
    """Call wall (mayor call OI) y put wall (mayor put OI) — los muros."""
    calls = df[df.type == "C"].groupby("strike")["open_interest"].sum()
    puts = df[df.type == "P"].groupby("strike")["open_interest"].sum()
    call_wall = calls.idxmax() if len(calls) and calls.max() > 0 else None
    put_wall = puts.idxmax() if len(puts) and puts.max() > 0 else None
    # zero gamma aprox: strike donde el GEX neto cruza de negativo a positivo
    return {"call_wall": call_wall, "put_wall": put_wall}


def bubble_map_data(ticker, snap_date, expiration=None, metric="gex"):
    """
    Datos para el mapa de burbujas tipo imagen 3: para cada timestamp del día,
    magnitud (gex u oi) por strike + spot. Devuelve un DataFrame largo.
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
        else:  # oi
            g = d.groupby("strike").apply(
                lambda x: (x[x.type=="C"]["open_interest"].sum()
                           - x[x.type=="P"]["open_interest"].sum())
            ).reset_index(name="magnitude")
        g["ts"] = ts
        g["spot"] = spot
        frames.append(g[["ts", "strike", "magnitude", "spot"]])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
