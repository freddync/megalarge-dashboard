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

    hist = t.history(period="10d")
    closes = hist["Close"].dropna() if hist is not None and not hist.empty else pd.Series(dtype=float)
    # Yahoo a veces entrega la última fila con Close vacío (sesión en curso o recién
    # cerrada). Se usa el último cierre válido; si no hay, el precio de fast_info.
    spot = float(closes.iloc[-1]) if len(closes) else float("nan")
    if not math.isfinite(spot) or spot <= 0:
        try:
            spot = float(t.fast_info["last_price"])
        except Exception:
            spot = float("nan")
    if not math.isfinite(spot) or spot <= 0:
        raise RuntimeError(f"No se pudo obtener el precio actual de {ticker}")
    vols = hist["Volume"].dropna() if hist is not None and not hist.empty else pd.Series(dtype=float)
    vols = vols[vols > 0]
    avg_vol_5d = float(vols.tail(5).mean()) if len(vols) else 0.0

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
    for c in ["strike", "openInterest", "impliedVolatility", "volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["strike"])
    # Fuera de horario Yahoo a veces entrega OI vacío en algunos strikes o IV ~0
    # (sin bid/ask). No se descartan: OI faltante = 0, e IV inválida se reemplaza
    # por la mediana de las IV válidas del mismo lado (o 30% si no hay ninguna).
    d["openInterest"] = d["openInterest"].fillna(0)
    d["volume"] = d["volume"].fillna(0)
    iv_ok = d["impliedVolatility"].where(d["impliedVolatility"] > 0.01)
    iv_fill = float(iv_ok.median()) if iv_ok.notna().any() else 0.30
    d["impliedVolatility"] = iv_ok.fillna(iv_fill)

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


# ---------------------------------------------------------------------------
# Velas horarias de la ultima semana y comportamiento del precio en cada muro
# ---------------------------------------------------------------------------

INTRADAY_RANGE = "5d"          # ultima semana habil
INTRADAY_INTERVAL = "60m"      # velas de 1 hora
WALL_ZONE_PCT = 1.5            # zona de "contacto" alrededor del strike, en % del strike
APPROACH_ZONE_MULT = 4         # "Acercandose" solo si esta a menos de 4 zonas del muro
APPROACH_LOOKBACK = 7          # ~1 sesion de velas horarias para medir la tendencia

_YAHOO_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}


def fetch_intraday(ticker: str) -> pd.DataFrame:
    """Velas de 1 hora de los ultimos 5 dias habiles (solo sesion regular).

    Usa la API de graficos de Yahoo (no necesita crumb). El indice queda en hora
    de Nueva York, sin zona horaria, para que Plotly lo dibuje tal cual.
    """
    import requests  # viene con yfinance

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": INTRADAY_RANGE, "interval": INTRADAY_INTERVAL, "includePrePost": "false"}
    r = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=20)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result") or []
    if not res or not res[0].get("timestamp"):
        raise RuntimeError(f"Yahoo no devolvio velas horarias para {ticker}")
    res = res[0]
    q = res["indicators"]["quote"][0]
    idx = (pd.to_datetime(res["timestamp"], unit="s", utc=True)
             .tz_convert("America/New_York").tz_localize(None))
    df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                       "Close": q["close"], "Volume": q["volume"]}, index=idx)
    df = df.dropna(subset=["Close"])
    # Yahoo agrega un "tick" de cierre a las 16:00 sin volumen: no es una vela
    df = df[~((df.index.hour == 16) & (df.index.minute == 0))]
    df.index.name = "Date"
    return df


def classify_wall(bars: pd.DataFrame, strike: float, zone_pct: float = WALL_ZONE_PCT) -> dict:
    """Clasifica como se ha movido el precio respecto a un muro en la ultima semana.

    Estados (se evalúan en este orden):
      - "Rompió ↑/↓": la semana empezo de un lado del strike y ahora cierra del otro.
      - "Probando":    toco la zona del muro y sigue dentro de ella.
      - "Rebotando":   toco la zona y ya se alejo al menos media zona desde el punto
                       mas cercano (tambien cuenta una perforacion falsa que volvio).
      - "Acercándose": no lo ha tocado, esta a menos de 4 zonas y la distancia se
                       redujo respecto a ~1 sesion atras.
      - "Lejos":       nada de lo anterior.

    Devuelve dict con estado, distancia actual (% firmado, + = precio sobre el muro),
    distancia minima de la semana (%, >= 0) y un detalle legible.
    """
    if bars is None or bars.empty or not strike:
        return {"estado": "Sin datos", "dist": None, "min_dist": None, "detalle": ""}

    close = bars["Close"].astype(float)
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    dist_now = (last / strike - 1) * 100
    side_first = 1 if first >= strike else -1
    side_now = 1 if last >= strike else -1

    if side_first != side_now:
        arrow = "↑" if side_now > 0 else "↓"
        return {"estado": f"Rompió {arrow}", "dist": dist_now, "min_dist": 0.0,
                "detalle": f"empezó la semana {'sobre' if side_first > 0 else 'bajo'} el strike "
                           f"y ahora está {abs(dist_now):.1f}% {'sobre' if side_now > 0 else 'bajo'}"}

    # distancia mas cercana alcanzada con mechas (lado del precio): si el precio esta
    # sobre el muro, lo que se acerca es el minimo; si esta bajo, el maximo
    if side_now > 0:
        extremes = (bars["Low"].astype(float) / strike - 1) * 100
        closest = extremes.min()
    else:
        extremes = (1 - bars["High"].astype(float) / strike) * 100
        closest = extremes.min()
    min_dist = max(float(closest), 0.0)   # < 0 = perforo con mecha y volvio
    pierced = float(closest) < 0
    touched = float(closest) <= zone_pct
    abs_now = abs(dist_now)

    if touched and abs_now <= zone_pct:
        return {"estado": "Probando", "dist": dist_now, "min_dist": min_dist,
                "detalle": f"está a {abs_now:.1f}% del muro, dentro de la zona de ±{zone_pct:g}%"}
    if touched and abs_now - min_dist >= zone_pct / 2:
        extra = " (perforó con mecha y volvió)" if pierced else ""
        return {"estado": "Rebotando", "dist": dist_now, "min_dist": min_dist,
                "detalle": f"llegó a {min_dist:.1f}% del muro{extra} y se alejó a {abs_now:.1f}%"}

    lb = min(APPROACH_LOOKBACK, len(close) - 1)
    if lb > 0:
        dist_prev = abs(float(close.iloc[-1 - lb]) / strike - 1) * 100
        if abs_now < dist_prev and abs_now <= zone_pct * APPROACH_ZONE_MULT:
            return {"estado": "Acercándose", "dist": dist_now, "min_dist": min_dist,
                    "detalle": f"pasó de {dist_prev:.1f}% a {abs_now:.1f}% en la última sesión"}

    return {"estado": "Lejos", "dist": dist_now, "min_dist": min_dist,
            "detalle": f"a {abs_now:.1f}% del muro"}


# ---------------------------------------------------------------------------
# Perfil de volumen (volumen de ACCIONES por nivel de precio) y consumo de muros
# ---------------------------------------------------------------------------

def _spread_volume(bars: pd.DataFrame, edges: np.ndarray) -> np.ndarray:
    """Reparte el volumen de cada vela uniformemente entre su mínimo y su máximo,
    acumulándolo en los tramos de precio definidos por `edges`."""
    out = np.zeros(len(edges) - 1)
    lows = bars["Low"].astype(float).values
    highs = bars["High"].astype(float).values
    vols = bars["Volume"].fillna(0).astype(float).values
    for lo, hi, v in zip(lows, highs, vols):
        if not v or not np.isfinite(lo) or not np.isfinite(hi):
            continue
        if hi <= lo:  # vela sin rango: todo el volumen en su tramo
            i = np.clip(np.searchsorted(edges, lo, side="right") - 1, 0, len(out) - 1)
            out[i] += v
            continue
        overlap = np.clip(np.minimum(edges[1:], hi) - np.maximum(edges[:-1], lo), 0, None)
        out += v * overlap / (hi - lo)
    return out


def volume_profile(bars: pd.DataFrame, y_lo: float, y_hi: float, n_bins: int = 60) -> pd.DataFrame:
    """Perfil de volumen de la semana: columnas price (centro del tramo), lo, hi, volume."""
    edges = np.linspace(y_lo, y_hi, n_bins + 1)
    vol = _spread_volume(bars, edges)
    return pd.DataFrame({"lo": edges[:-1], "hi": edges[1:],
                         "price": (edges[:-1] + edges[1:]) / 2, "volume": vol})


def zone_volume(bars: pd.DataFrame, strike: float, zone_pct: float = WALL_ZONE_PCT) -> float:
    """Acciones transadas durante la semana dentro de la zona ±zone_pct% del strike."""
    z = zone_pct / 100
    return float(_spread_volume(bars, np.array([strike * (1 - z), strike * (1 + z)]))[0])
