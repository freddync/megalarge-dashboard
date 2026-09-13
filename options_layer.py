"""
options_layer.py
----------------
Cadenas de opciones (calls/puts) de los 2 vencimientos mas proximos, con:
  - Open Interest y volumen por strike
  - Delta y Gamma de Black-Scholes (Yahoo no entrega griegas, se calculan aca)
  - GEX (Gamma Exposure) por strike
  - "Walls": los 2 strikes con mayor OI por lado (soportes/resistencias)
  - Cobertura delta: acciones nocionales que un market maker necesita cubrir

Convenciones tomadas del script que ya usa el usuario en Colab:
  - CONTRACT_SIZE = 100, RISK_FREE_RATE = 0.045
  - ventana operativa: strikes entre 75% y 125% del spot
  - T = max(dte, 0.08) / 365  (piso para no dividir por cero el dia del vencimiento)
  - walls = top 2 por openInterest dentro de esa ventana

IMPORTANTE sobre la descarga: Yahoo exige cookie/crumb para las cadenas de
opciones. yfinance lo resuelve solo, pero necesita internet real -- funciona en
tu computador y en Streamlit Community Cloud, no en entornos sin salida directa.
Por eso `fetch_chains` esta aislado del resto: toda la matematica (delta, gamma,
GEX, walls) es pura y testeable sin red.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd

CONTRACT_SIZE = 100
RISK_FREE_RATE = 0.045
STRIKE_WINDOW = 0.25     # +/-25% alrededor del spot
N_EXPIRATIONS = 2        # los 2 vencimientos mas proximos
T_FLOOR_DAYS = 0.08      # piso de dias para T (igual que el script original)


# ---------------------------------------------------------------------------
# Black-Scholes (sin scipy: norm.cdf/pdf con math.erf, identico numericamente
# y evita una dependencia pesada en el deploy)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1(S, K, T, r, sigma):
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def bs_delta(S, K, T, r, sigma, opt_type="call") -> float:
    """Delta de Black-Scholes. En el limite (T<=0 o sigma<=0) devuelve el delta
    degenerado: 1/0 para calls y -1/0 para puts segun este ITM u OTM."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if opt_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _norm_cdf(d1) if opt_type == "call" else _norm_cdf(d1) - 1.0


def bs_gamma(S, K, T, r, sigma) -> float:
    """Gamma de Black-Scholes (igual para calls y puts)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def gex_per_strike(gamma, open_interest, spot, is_call: bool) -> float:
    """GEX en dolares por cada 1% de movimiento del subyacente.

        GEX = Gamma x OI x 100 x S^2 x 0.01

    Convencion estandar de dealer: se asume que los market makers estan LARGOS
    en calls y CORTOS en puts, por lo que el GEX de las calls suma y el de las
    puts resta. Es un supuesto del mercado, no un dato observado.
    """
    sign = 1.0 if is_call else -1.0
    return sign * gamma * open_interest * CONTRACT_SIZE * (spot ** 2) * 0.01


# ---------------------------------------------------------------------------
# Descarga (requiere internet real; yfinance resuelve el crumb de Yahoo)
# ---------------------------------------------------------------------------

def fetch_chains(ticker: str, n_exp: int = N_EXPIRATIONS, today: datetime.date | None = None):
    """Devuelve (spot, [ {exp, dte, calls, puts}, ... ]) para los n vencimientos
    mas proximos. Lanza RuntimeError con un mensaje claro si no hay datos."""
    import yfinance as yf  # import diferido: la app funciona aunque no este instalado

    today = today or datetime.date.today()
    t = yf.Ticker(ticker)

    hist = t.history(period="5d")
    if hist is None or hist.empty:
        raise RuntimeError(f"No hay historial reciente para {ticker}")
    spot = float(hist["Close"].iloc[-1])
    avg_vol_5d = float(hist["Volume"].tail(5).mean())

    expirations = t.options or []
    if not expirations:
        raise RuntimeError(f"{ticker} no tiene cadena de opciones listada en Yahoo")

    chosen = []
    for exp_str in expirations:
        exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if dte >= 0:
            chosen.append((exp_str, dte))
        if len(chosen) == n_exp:
            break

    out = []
    for exp_str, dte in chosen:
        chain = t.option_chain(exp_str)
        out.append({
            "exp": exp_str,
            "dte": dte,
            "calls": chain.calls.copy(),
            "puts": chain.puts.copy(),
        })
    return spot, avg_vol_5d, out


# ---------------------------------------------------------------------------
# Calculo por strike (puro, testeable sin red)
# ---------------------------------------------------------------------------

def _prep_side(df: pd.DataFrame, spot: float, T: float, is_call: bool) -> pd.DataFrame:
    """Normaliza un lado de la cadena y calcula delta, gamma, GEX y cobertura."""
    cols = ["strike", "openInterest", "impliedVolatility"]
    if df is None or df.empty or not all(c in df.columns for c in cols):
        return pd.DataFrame(columns=["strike", "oi", "volume", "iv", "delta", "gamma", "gex", "hedge_shares"])

    d = df.copy()
    d["volume"] = d["volume"] if "volume" in d.columns else 0
    d = d[["strike", "openInterest", "impliedVolatility", "volume"]].copy()
    d = d.dropna(subset=["strike", "openInterest", "impliedVolatility"])
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0)

    # ventana operativa +/-25% del spot
    lo, hi = spot * (1 - STRIKE_WINDOW), spot * (1 + STRIKE_WINDOW)
    d = d[(d["strike"] >= lo) & (d["strike"] <= hi)]
    if d.empty:
        return pd.DataFrame(columns=["strike", "oi", "volume", "iv", "delta", "gamma", "gex", "hedge_shares"])

    opt_type = "call" if is_call else "put"
    rows = []
    for _, r in d.iterrows():
        K = float(r["strike"])
        oi = int(r["openInterest"])
        iv = float(r["impliedVolatility"])
        delta = bs_delta(spot, K, T, RISK_FREE_RATE, iv, opt_type)
        gamma = bs_gamma(spot, K, T, RISK_FREE_RATE, iv)
        rows.append({
            "strike": K,
            "oi": oi,
            "volume": int(r["volume"]),
            "iv": iv,
            "delta": delta,
            "gamma": gamma,
            "gex": gex_per_strike(gamma, oi, spot, is_call),
            # cobertura: acciones nocionales delta-hedged (OI x 100 x |delta|)
            "hedge_shares": int(round(oi * CONTRACT_SIZE * abs(delta))),
        })
    return pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)


def build_levels(spot: float, dte: int, calls_raw: pd.DataFrame, puts_raw: pd.DataFrame):
    """Tabla por strike con OI/volumen/GEX de ambos lados, lista para graficar."""
    T = max(dte, T_FLOOR_DAYS) / 365.0
    calls = _prep_side(calls_raw, spot, T, is_call=True)
    puts = _prep_side(puts_raw, spot, T, is_call=False)

    merged = pd.merge(
        calls.add_prefix("call_").rename(columns={"call_strike": "strike"}),
        puts.add_prefix("put_").rename(columns={"put_strike": "strike"}),
        on="strike", how="outer",
    ).sort_values("strike").reset_index(drop=True)

    for c in ["call_oi", "put_oi", "call_volume", "put_volume", "call_gex", "put_gex"]:
        if c not in merged.columns:
            merged[c] = 0
    merged[["call_oi", "put_oi", "call_volume", "put_volume", "call_gex", "put_gex"]] = \
        merged[["call_oi", "put_oi", "call_volume", "put_volume", "call_gex", "put_gex"]].fillna(0)

    merged["net_gex"] = merged["call_gex"] + merged["put_gex"]
    return calls, puts, merged


def top_walls(side_df: pd.DataFrame, n: int = 2):
    """Los n strikes con mayor Open Interest (los 'muros')."""
    if side_df is None or side_df.empty:
        return []
    top = side_df.sort_values("oi", ascending=False).head(n)
    return top.to_dict("records")


def gamma_flip(levels: pd.DataFrame):
    """Strike donde el GEX acumulado cambia de signo (gamma flip / zero gamma).

    Se recorre el GEX acumulado de menor a mayor strike y se devuelve el primer
    strike donde cruza cero. Si nunca cruza, devuelve None.
    """
    if levels is None or levels.empty:
        return None
    cum = levels["net_gex"].cumsum().values
    strikes = levels["strike"].values
    for i in range(1, len(cum)):
        if (cum[i - 1] < 0 <= cum[i]) or (cum[i - 1] > 0 >= cum[i]):
            # interpolacion lineal entre los dos strikes
            x0, x1 = cum[i - 1], cum[i]
            k0, k1 = strikes[i - 1], strikes[i]
            if x1 == x0:
                return float(k1)
            return float(k0 + (k1 - k0) * (0 - x0) / (x1 - x0))
    return None


def total_gex(levels: pd.DataFrame) -> float:
    if levels is None or levels.empty:
        return 0.0
    return float(levels["net_gex"].sum())


def fmt_qty(n) -> str:
    """Normaliza cantidades a K / M (mismo criterio del script original)."""
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "—"
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{int(n)}"


def fmt_gex(x) -> str:
    """GEX en dolares por 1% de movimiento."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    ax = abs(x)
    sign = "-" if x < 0 else ""
    if ax >= 1e9:
        return f"{sign}${ax/1e9:.2f}B"
    if ax >= 1e6:
        return f"{sign}${ax/1e6:.1f}M"
    if ax >= 1e3:
        return f"{sign}${ax/1e3:.1f}K"
    return f"{sign}${ax:.0f}"
