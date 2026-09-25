"""
data_layer.py
-------------
Capa de datos para el dashboard integrado (Megacap + Large Cap) en Streamlit.
Lee los datos ya bundleados en /data (precios recortados + fundamentales
variacion + company_info.json) -- sin llamadas de red en runtime, para que
la app funcione rapido y sin rate-limit en Streamlit Community Cloud.

Metodologia tecnica: SMA100 o SMA200 (a eleccion del usuario) de Close diario,
con banda +/-1.5 desviaciones estandar del Close (estilo Bollinger), en vez
del VWAP181 que se usaba en los dashboards anteriores.
"""

import os
import json
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRECIOS_DIR = os.path.join(DATA_DIR, "precios")
SEMANAL_DIR = os.path.join(DATA_DIR, "precios_semanal")
FUND_DIR = os.path.join(DATA_DIR, "fundamentales_variacion")
COMPANY_INFO_PATH = os.path.join(DATA_DIR, "company_info.json")

K = 1.5
SMA_WINDOWS = [100, 200]

TABLE_METRICS = ["TotalRevenue", "GrossProfit", "OperatingIncome", "NetIncome", "DilutedEPS",
                  "FreeCashFlow", "CapitalExpenditure", "TotalDebt", "CashAndCashEquivalents",
                  "EBITDA", "DilutedAverageShares"]

FUND_ROWS = [
    ("TotalRevenue", "Ingresos", False),
    ("GrossProfit", "Utilidad bruta", False),
    ("OperatingIncome", "Utilidad operacional", False),
    ("NetIncome", "Utilidad neta", False),
    ("DilutedEPS", "EPS diluido", True),
    ("FreeCashFlow", "Flujo de caja libre", False),
    ("CapitalExpenditure", "CAPEX", False),
    ("TotalDebt", "Deuda total", False),
    ("CashAndCashEquivalents", "Caja y equivalentes", False),
]


SELLO_PATH = os.path.join(DATA_DIR, "_ultima_actualizacion.json")


def load_company_info():
    with open(COMPANY_INFO_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_sello_actualizacion():
    """Cuando se actualizaron los precios por ultima vez.

    Lo escribe el proceso que baja los datos (scripts/refresh_prices.py o
    update_data.py). Si no existe el archivo devuelve None y la app cae a
    mostrar solo la ultima sesion presente en los datos.
    """
    if not os.path.exists(SELLO_PATH):
        return None
    try:
        with open(SELLO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_tickers():
    files = sorted(f[:-4] for f in os.listdir(PRECIOS_DIR) if f.endswith(".csv"))
    return files


def load_price_df(ticker):
    path = os.path.join(PRECIOS_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True).dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    return df if not df.empty else None


# --- Frecuencia: diaria o semanal -------------------------------------------
# La semana se cierra el viernes (W-FRI). El OHLCV se agrega como corresponde:
# apertura de la primera sesión, máximo y mínimo del periodo, cierre de la última
# sesión y volumen sumado.

FREQ_DAILY = "Diaria"
FREQ_WEEKLY = "Semanal"

# periodos equivalentes para los retornos según la frecuencia
RETURN_PERIODS = {
    FREQ_DAILY: {"r1m": 21, "r3m": 63, "r6m": 126, "r1y": 252},
    FREQ_WEEKLY: {"r1m": 4, "r3m": 13, "r6m": 26, "r1y": 52},
}
# cuántas barras equivalen a una semana en cada frecuencia
BARS_PER_WEEK = {FREQ_DAILY: 5, FREQ_WEEKLY: 1}


def resample_weekly(df):
    """Convierte OHLCV diario a semanal (semanas que cierran el viernes)."""
    if df is None or df.empty:
        return df
    out = (df.set_index("Date")
             .resample("W-FRI")
             .agg({"Open": "first", "High": "max", "Low": "min",
                   "Close": "last", "Volume": "sum"})
             .dropna(subset=["Close"])
             .reset_index())
    return out


def load_weekly_df(ticker):
    """Barras semanales pre-generadas (con mucho más historial que el CSV diario,
    que viene recortado). Devuelve None si todavía no se han generado."""
    path = os.path.join(SEMANAL_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True).dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    return df if not df.empty else None


def get_series(ticker, freq=FREQ_DAILY):
    """Serie de precios del ticker en la frecuencia pedida.

    En semanal se usan las barras pre-generadas en /data/precios_semanal (que
    cubren muchos más años, necesarios para una SMA200 semanal). Si no están,
    se cae a agregar el CSV diario, que alcanza para la SMA100 pero deja la
    SMA200 semanal muy corta.
    """
    if freq == FREQ_WEEKLY:
        df = load_weekly_df(ticker)
        if df is not None:
            return df
        daily = load_price_df(ticker)
        if daily is None:
            return None
        df = resample_weekly(daily)
        return df if df is not None and not df.empty else None
    return load_price_df(ticker)


def compute_sma_bands(df, window, k=K):
    """SMA de Close + banda +/-k*std (desviacion estandar del Close, tipo Bollinger).
    A diferencia del VWAP, no pondera por volumen."""
    close = df["Close"]
    sma = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=0)
    up = sma + k * std
    down = sma - k * std
    return sma, up, down


def pct_return(series, periods):
    if len(series) <= periods:
        return None
    a, b = series.iloc[-periods - 1], series.iloc[-1]
    if a == 0 or pd.isna(a) or pd.isna(b):
        return None
    return (b / a - 1) * 100


# ---------------------------------------------------------------------------
# RSI (14 periodos, estándar) y MACD (12/26/9)
# ---------------------------------------------------------------------------
# Son independientes de la SMA a proposito: cada indicador produce su propia
# señal y su propia columna ordenable en el dashboard.

RSI_PERIOD = 14           # RSI estándar de Wilder
RSI_SOBRECOMPRA = 70      # límites clásicos para 14 periodos
RSI_SOBREVENTA = 30

MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9


def compute_rsi(close, period=RSI_PERIOD):
    """RSI con suavizado de Wilder, devuelto como Serie.

    Ojo con la inicializacion: Wilder arranca con la MEDIA SIMPLE de los primeros
    `period` cambios y recien despues aplica el suavizado. Usar directamente
    ewm(alpha=1/period) de pandas arranca con el primer valor y da un resultado
    distinto (en el ejemplo canonico del libro de Wilder daba 50.7 en vez de
    70.5). Con series largas la diferencia se desvanece, pero asi queda correcto
    para cualquier largo.
    """
    delta = close.diff()
    gan = delta.clip(lower=0).to_numpy(dtype=float)
    per = (-delta.clip(upper=0)).to_numpy(dtype=float)
    n = len(close)

    avg_g = np.full(n, np.nan)
    avg_p = np.full(n, np.nan)
    if n > period:
        avg_g[period] = np.nanmean(gan[1:period + 1])
        avg_p[period] = np.nanmean(per[1:period + 1])
        for i in range(period + 1, n):
            avg_g[i] = (avg_g[i - 1] * (period - 1) + gan[i]) / period
            avg_p[i] = (avg_p[i - 1] * (period - 1) + per[i]) / period

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_p > 0, avg_g / avg_p, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + rs)
    # sin perdidas en la ventana -> RSI 100; sin movimiento alguno -> 50 (neutral)
    sin_perdidas = (avg_p == 0)
    rsi = np.where(sin_perdidas & (avg_g > 0), 100.0, rsi)
    rsi = np.where(sin_perdidas & (avg_g == 0), 50.0, rsi)
    return pd.Series(rsi, index=close.index)


def rsi_signal(rsi):
    """Etiqueta del RSI segun los limites 70/30."""
    if rsi is None or pd.isna(rsi):
        return "Sin datos"
    if rsi >= RSI_SOBRECOMPRA:
        return "Sobrecompra"
    if rsi <= RSI_SOBREVENTA:
        return "Sobreventa"
    return "Neutral"


def compute_macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    """MACD clasico: devuelve (linea MACD, linea de señal, histograma)."""
    ema_rapida = close.ewm(span=fast, adjust=False).mean()
    ema_lenta = close.ewm(span=slow, adjust=False).mean()
    macd = ema_rapida - ema_lenta
    señal = macd.ewm(span=signal, adjust=False).mean()
    return macd, señal, macd - señal


def macd_signal(hist_actual, hist_previo):
    """Cuatro estados segun el signo del histograma y hacia donde va.

    El histograma es MACD menos su linea de señal, asi que su signo dice de que
    lado del cruce estamos y su pendiente dice si el movimiento gana o pierde
    fuerza:

      Bajista          histograma negativo y cayendo  -> abajo y empeorando
      Perdiendo fuerza histograma positivo y cayendo  -> SEÑAL DE VENTA
      Pre-cruce        histograma negativo y subiendo -> SEÑAL DE COMPRA
                                                         (se acerca la golden cross)
      Alcista          histograma positivo y subiendo -> tendencia confirmada
    """
    if hist_actual is None or pd.isna(hist_actual) or hist_previo is None or pd.isna(hist_previo):
        return "Sin datos"
    subiendo = hist_actual >= hist_previo
    if hist_actual >= 0:
        return "Alcista" if subiendo else "Perdiendo fuerza"
    return "Pre-cruce" if subiendo else "Bajista"


def zone_signal(close, sma, up, down):
    if pd.isna(sma):
        return "Historial insuficiente para la SMA elegida", None, None
    dist_pct = (close / sma - 1) * 100
    band_width = up - down
    band_pos = (close - down) / band_width if band_width > 0 else 0.5
    if close > up:
        signal = "Sobre banda superior (sobrecomprado / momentum fuerte)"
    elif close < down:
        signal = "Bajo banda inferior (sobrevendido / debilidad)"
    elif close > sma:
        signal = "Sobre SMA, dentro de banda (sesgo alcista moderado)"
    else:
        signal = "Bajo SMA, dentro de banda (sesgo bajista moderado)"
    return signal, dist_pct, band_pos


def short_signal(signal):
    if "insuficiente" in signal:
        return "Sin datos"
    if "Sobre banda superior" in signal:
        return "Sobrecomprado"
    if "Bajo banda inferior" in signal:
        return "Sobrevendido"
    if "Sobre SMA" in signal:
        return "Alcista"
    return "Bajista"


def build_summary(window, company_info, freq=FREQ_DAILY):
    """Resumen tecnico para TODAS las empresas.

    Calcula TRES indicadores independientes, cada uno con su valor numerico y su
    etiqueta, para que en el dashboard se puedan ordenar por separado:
      - SMA `window` con banda +/-1.5 sigma  -> columna "Zona"
      - RSI de 14 periodos (limites 70/30)    -> columna "Señal RSI"
      - MACD 12/26/9 (estado del histograma) -> columna "Señal MACD"
    """
    periods = RETURN_PERIODS.get(freq, RETURN_PERIODS[FREQ_DAILY])
    vol_window = 60 if freq == FREQ_DAILY else 12

    rows = []
    for ticker in list_tickers():
        df = get_series(ticker, freq)
        if df is None or len(df) < 5:
            continue
        cierre = df["Close"]
        sma, up, down = compute_sma_bands(df, window)
        last = df.iloc[-1]
        close = float(last["Close"])
        sma_last = sma.iloc[-1]
        up_last = up.iloc[-1]
        down_last = down.iloc[-1]
        signal, dist_pct, band_pos = zone_signal(close, sma_last, up_last, down_last)

        # --- RSI 14 ---
        rsi_serie = compute_rsi(cierre)
        rsi_val = rsi_serie.iloc[-1] if len(rsi_serie) else None

        # --- MACD 12/26/9 ---
        macd_l, macd_sig, macd_hist = compute_macd(cierre)
        hist_act = macd_hist.iloc[-1] if len(macd_hist) else None
        hist_prev = macd_hist.iloc[-2] if len(macd_hist) > 1 else None
        # el histograma se normaliza por el precio para poder comparar empresas
        # de muy distinto valor nominal entre si
        hist_pct = (float(hist_act) / close * 100) if (hist_act is not None
                                                       and pd.notna(hist_act) and close) else None

        info = company_info.get(ticker, {})
        rows.append({
            "ticker": ticker,
            "name": info.get("name", ticker),
            "sector": info.get("sector", "Sin clasificar"),
            "industry": info.get("industry", ""),
            "universe": info.get("universe", "?"),
            "last_date": last["Date"].strftime("%Y-%m-%d"),
            "close": round(close, 2),
            "sma": round(float(sma_last), 2) if pd.notna(sma_last) else None,
            "band_up": round(float(up_last), 2) if pd.notna(up_last) else None,
            "band_down": round(float(down_last), 2) if pd.notna(down_last) else None,
            "dist_sma_pct": round(float(dist_pct), 2) if dist_pct is not None else None,
            "band_pos": round(float(band_pos), 3) if band_pos is not None else None,
            "signal": signal,
            "zone": short_signal(signal),
            # --- RSI 14 (independiente de la SMA) ---
            "rsi": round(float(rsi_val), 1) if rsi_val is not None and pd.notna(rsi_val) else None,
            "rsi_signal": rsi_signal(rsi_val),
            # --- MACD 12/26/9 (independiente de los otros dos) ---
            "macd_hist": round(float(hist_act), 4) if hist_act is not None and pd.notna(hist_act) else None,
            "macd_hist_pct": round(hist_pct, 3) if hist_pct is not None else None,
            "macd_signal": macd_signal(hist_act, hist_prev),
            "r1m": (lambda v: round(v, 2) if v is not None else None)(pct_return(cierre, periods["r1m"])),
            "r3m": (lambda v: round(v, 2) if v is not None else None)(pct_return(cierre, periods["r3m"])),
            "r6m": (lambda v: round(v, 2) if v is not None else None)(pct_return(cierre, periods["r6m"])),
            "r1y": (lambda v: round(v, 2) if v is not None else None)(pct_return(cierre, periods["r1y"])),
            "avg_vol_60d": int(v) if pd.notna(v := df["Volume"].tail(vol_window).mean()) else None,
            "n_rows": len(df),
            "first_date": df["Date"].iloc[0].strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows)


def load_fund_csv(ticker, suffix):
    path = os.path.join(FUND_DIR, f"{ticker}_{suffix}_variacion.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    return df.sort_values("Date").reset_index(drop=True)


def compute_margins(ticker):
    dfa = load_fund_csv(ticker, "anual")
    if dfa is None or dfa.empty:
        return None
    last = dfa.iloc[-1]
    rev = last.get("TotalRevenue")
    if pd.isna(rev) or not rev:
        return None
    return {
        "date": str(last["Date"]),
        "revenue": rev,
        "gross_margin": (last["GrossProfit"] / rev * 100) if pd.notna(last.get("GrossProfit")) else None,
        "op_margin": (last["OperatingIncome"] / rev * 100) if pd.notna(last.get("OperatingIncome")) else None,
        "net_margin": (last["NetIncome"] / rev * 100) if pd.notna(last.get("NetIncome")) else None,
        "revenue_yoy": last.get("TotalRevenue_var_pct"),
        "netincome_yoy": last.get("NetIncome_var_pct"),
        "capex": last.get("CapitalExpenditure"),
        "fcf": last.get("FreeCashFlow"),
    }


def compute_pe(ticker, close):
    dfq = load_fund_csv(ticker, "trimestral")
    dfa = load_fund_csv(ticker, "anual")
    eps, label = None, ""
    if dfq is not None and len(dfq) >= 4:
        last4 = dfq.tail(4)
        if last4["DilutedEPS"].notna().all():
            eps = last4["DilutedEPS"].sum()
            label = "TTM (4 trimestres)"
    if eps is None and dfa is not None and not dfa.empty:
        last = dfa.iloc[-1]
        if pd.notna(last.get("DilutedEPS")):
            eps = last["DilutedEPS"]
            label = f"último año fiscal ({str(last['Date'])[:4]})"
    if eps is None or eps == 0:
        return None
    return {"pe": close / eps, "eps": eps, "label": label, "negative": eps < 0}


def compute_ev_ebitda(ticker, close):
    dfa = load_fund_csv(ticker, "anual")
    if dfa is None or dfa.empty:
        return None
    last = dfa.iloc[-1]
    ebitda = last.get("EBITDA")
    shares = last.get("DilutedAverageShares")
    if pd.isna(ebitda) or not ebitda or pd.isna(shares):
        return None
    market_cap = close * shares
    debt = last.get("TotalDebt") or 0
    cash = last.get("CashAndCashEquivalents") or 0
    if pd.isna(debt):
        debt = 0
    if pd.isna(cash):
        cash = 0
    ev = market_cap + debt - cash
    return {"ev": ev, "ebitda": ebitda, "market_cap": market_cap,
            "multiple": ev / ebitda, "negative": ebitda < 0, "date": str(last["Date"])}


def compute_recommendation(row, margins):
    reasons = []
    tech_score, fund_score = 0, 0
    has_tech, has_fund = False, False

    if row.get("sma") is not None:
        has_tech = True
        if row["dist_sma_pct"] > 0:
            tech_score += 1
            reasons.append(f"el precio está +{row['dist_sma_pct']:.2f}% sobre su SMA")
        else:
            tech_score -= 1
            reasons.append(f"el precio está {row['dist_sma_pct']:.2f}% bajo su SMA")
        if row.get("r3m") is not None:
            if row["r3m"] > 0:
                tech_score += 1; reasons.append(f"el momentum de 3 meses es positivo ({row['r3m']:+.2f}%)")
            else:
                tech_score -= 1; reasons.append(f"el momentum de 3 meses es negativo ({row['r3m']:+.2f}%)")
        if row.get("r1y") is not None:
            if row["r1y"] > 0:
                tech_score += 1; reasons.append(f"el retorno de 12 meses es positivo ({row['r1y']:+.2f}%)")
            else:
                tech_score -= 1; reasons.append(f"el retorno de 12 meses es negativo ({row['r1y']:+.2f}%)")

    if margins:
        has_fund = True
        if margins.get("revenue_yoy") is not None:
            if margins["revenue_yoy"] > 0:
                fund_score += 1; reasons.append(f"los ingresos anuales crecieron {margins['revenue_yoy']:+.2f}% interanual")
            else:
                fund_score -= 1; reasons.append(f"los ingresos anuales cayeron {margins['revenue_yoy']:+.2f}% interanual")
        if margins.get("netincome_yoy") is not None:
            if margins["netincome_yoy"] > 0:
                fund_score += 1; reasons.append(f"la utilidad neta anual creció {margins['netincome_yoy']:+.2f}% interanual")
            else:
                fund_score -= 1; reasons.append(f"la utilidad neta anual cayó {margins['netincome_yoy']:+.2f}% interanual")

    if not has_tech and not has_fund:
        return "Sin datos suficientes", "No hay suficiente historial técnico ni fundamental para generar una lectura."

    total = tech_score + fund_score
    if total >= 3:
        label = "Sesgo positivo"
    elif total <= -3:
        label = "Sesgo negativo"
    else:
        label = "Neutral / Mantener"
    text = ("En conjunto, " + "; ".join(reasons) + ".") if reasons else "No hay suficientes señales para justificar una lectura."
    return label, text
