"""
collect.py — Descarga la cadena de opciones y guarda un snapshot en SQLite.

Corre esto una vez al día (idealmente después del cierre del mercado, ~4:15pm ET)
o cada N minutos si quieres seguir el volumen intradía. El Open Interest (los
"imanes") solo cambia una vez al día, así que 1 corrida diaria basta para imanes;
corre más seguido solo si quieres vigilar volumen fresco.

Uso:
    python collect.py                # usa la watchlist por defecto (META)
    python collect.py META NVDA AAPL # varios tickers
"""

import sys
import sqlite3
import datetime as dt
import math

import yfinance as yf
import pandas as pd
from scipy.stats import norm

DB_PATH = "options.db"
WATCHLIST_FILE = "watchlist.txt"


def load_watchlist():
    """Lee watchlist.txt; si no existe, usa META."""
    try:
        with open(WATCHLIST_FILE) as f:
            tickers = [ln.strip().upper() for ln in f
                       if ln.strip() and not ln.strip().startswith("#")]
        return tickers or ["META"]
    except FileNotFoundError:
        return ["META"]

# Tasa libre de riesgo aproximada para el cálculo de griegas (ajústala si quieres).
RISK_FREE = 0.04


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            ts            TEXT,     -- timestamp de la corrida (ISO)
            snap_date     TEXT,     -- fecha de la corrida (YYYY-MM-DD)
            ticker        TEXT,
            spot          REAL,
            expiration    TEXT,     -- fecha de vencimiento
            type          TEXT,     -- 'C' o 'P'
            strike        REAL,
            last          REAL,
            bid           REAL,
            ask           REAL,
            volume        INTEGER,
            open_interest INTEGER,
            iv            REAL,
            delta         REAL,
            gamma         REAL,
            gex           REAL      -- gamma exposure de esa fila (signed)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snap
        ON snapshots (ticker, snap_date, expiration, strike, type)
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Griegas (Black-Scholes) — para GEX y para tener delta/gamma consistentes
# ---------------------------------------------------------------------------
def bs_greeks(spot, strike, t_years, iv, opt_type, r=RISK_FREE):
    """Devuelve (delta, gamma). Robusto ante valores degenerados."""
    if t_years <= 0 or iv is None or iv <= 0 or spot <= 0 or strike <= 0:
        return (None, None)
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
        gamma = norm.pdf(d1) / (spot * iv * math.sqrt(t_years))
        if opt_type == "C":
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1.0
        return (delta, gamma)
    except (ValueError, ZeroDivisionError):
        return (None, None)


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def fetch_ticker(ticker):
    """Devuelve (spot, lista_de_filas). Lista vacía si algo falla."""
    tk = yf.Ticker(ticker)

    # Spot: intenta varias vías porque Yahoo a veces cambia el campo.
    spot = None
    try:
        fi = tk.fast_info
        spot = fi.get("last_price") or fi.get("lastPrice")
    except Exception:
        pass
    if spot is None:
        try:
            spot = tk.history(period="1d")["Close"].iloc[-1]
        except Exception:
            print(f"  [!] No pude obtener el spot de {ticker}, lo salto.")
            return (None, [])

    try:
        expirations = tk.options
    except Exception as e:
        print(f"  [!] No pude obtener vencimientos de {ticker}: {e}")
        return (spot, [])

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    rows = []

    for exp in expirations:
        try:
            chain = tk.option_chain(exp)
        except Exception as e:
            print(f"  [!] Falló la cadena {ticker} {exp}: {e}")
            continue

        exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
        t_years = max((exp_date - today).days, 0) / 365.0

        for opt_type, df in (("C", chain.calls), ("P", chain.puts)):
            for _, r in df.iterrows():
                strike = _num(r.get("strike"))
                if strike is None or strike <= 0:
                    continue  # fila sin strike válido, la saltamos
                iv = r.get("impliedVolatility", None)
                iv = float(iv) if iv == iv and iv is not None else None  # NaN check
                oi = _int(r.get("openInterest"))
                vol = _int(r.get("volume"))

                delta, gamma = bs_greeks(spot, strike, t_years, iv, opt_type)

                # GEX de la fila: gamma * OI * 100 * spot^2 * 0.01, con signo
                # (calls +, puts -). Es la convención estándar de "dealer gamma".
                gex = None
                if gamma is not None:
                    sign = 1.0 if opt_type == "C" else -1.0
                    gex = sign * gamma * oi * 100 * spot * spot * 0.01

                rows.append((
                    now.isoformat(timespec="seconds"),
                    today.isoformat(),
                    ticker,
                    round(float(spot), 4),
                    exp,
                    opt_type,
                    strike,
                    _num(r.get("lastPrice")),
                    _num(r.get("bid")),
                    _num(r.get("ask")),
                    vol,
                    oi,
                    round(iv, 6) if iv is not None else None,
                    round(delta, 6) if delta is not None else None,
                    round(gamma, 8) if gamma is not None else None,
                    round(gex, 2) if gex is not None else None,
                ))

    return (spot, rows)


def _num(x):
    try:
        if x is None or x != x:
            return None
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def _int(x):
    """Convierte a int de forma segura: NaN, None o vacío -> 0."""
    try:
        if x is None or x != x:   # x != x detecta NaN
            return 0
        return int(x)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    watchlist = sys.argv[1:] or load_watchlist()
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total = 0
    for ticker in watchlist:
        print(f"[*] Descargando {ticker} ...")
        spot, rows = fetch_ticker(ticker)
        if not rows:
            print(f"    sin datos para {ticker}")
            continue
        conn.executemany(
            """INSERT INTO snapshots VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
        total += len(rows)
        print(f"    spot={spot:.2f}  filas guardadas={len(rows)}")

    conn.close()
    print(f"[OK] Total filas: {total}. Guardado en {DB_PATH}")


if __name__ == "__main__":
    main()
