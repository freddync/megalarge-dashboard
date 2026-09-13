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


def load_company_info():
    with open(COMPANY_INFO_PATH, encoding="utf-8") as f:
        return json.load(f)


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


def compute_weekly_momentum(close, step=5):
    """Compara el ritmo de la última semana contra el promedio de las 3 previas.

    `step` = cuántas barras equivalen a una semana (5 en datos diarios, 1 en semanales),
    para que la métrica signifique lo mismo en ambas frecuencias.
    """
    if len(close) <= 4 * step:
        return None
    p = [close.iloc[-1 - i * step] for i in range(5)]
    if any(pd.isna(x) or x == 0 for x in p):
        return None
    w1 = (p[0] / p[1] - 1) * 100
    w2 = (p[1] / p[2] - 1) * 100
    w3 = (p[2] / p[3] - 1) * 100
    w4 = (p[3] / p[4] - 1) * 100
    avg_prev = (abs(w2) + abs(w3) + abs(w4)) / 3
    return "Acelerando" if abs(w1) >= avg_prev else "Desacelerando"


def compute_weekly_accel_2w(close, step=5):
    """Versión corta: última semana contra la semana anterior."""
    if len(close) <= 2 * step:
        return None
    p0, p1, p2 = close.iloc[-1], close.iloc[-1 - step], close.iloc[-1 - 2 * step]
    if any(pd.isna(x) or x == 0 for x in [p0, p1, p2]):
        return None
    w1 = (p0 / p1 - 1) * 100
    w2 = (p1 / p2 - 1) * 100
    return "Acelerando" if abs(w1) >= abs(w2) else "Desacelerando"


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

    `window` es la SMA (100 o 200) y `freq` define si esas 100/200 barras son
    días o semanas. Los retornos y el momentum se ajustan a la frecuencia para
    que sigan significando lo mismo (1 mes, 3 meses, 1 semana, etc.).
    """
    periods = RETURN_PERIODS.get(freq, RETURN_PERIODS[FREQ_DAILY])
    step = BARS_PER_WEEK.get(freq, 5)
    vol_window = 60 if freq == FREQ_DAILY else 12

    rows = []
    for ticker in list_tickers():
        df = get_series(ticker, freq)
        if df is None or len(df) < 5:
            continue
        sma, up, down = compute_sma_bands(df, window)
        last = df.iloc[-1]
        close = float(last["Close"])
        sma_last = sma.iloc[-1]
        up_last = up.iloc[-1]
        down_last = down.iloc[-1]
        signal, dist_pct, band_pos = zone_signal(close, sma_last, up_last, down_last)
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
            "r1m": (lambda v: round(v, 2) if v is not None else None)(pct_return(df["Close"], periods["r1m"])),
            "r3m": (lambda v: round(v, 2) if v is not None else None)(pct_return(df["Close"], periods["r3m"])),
            "r6m": (lambda v: round(v, 2) if v is not None else None)(pct_return(df["Close"], periods["r6m"])),
            "r1y": (lambda v: round(v, 2) if v is not None else None)(pct_return(df["Close"], periods["r1y"])),
            "momentum": compute_weekly_momentum(df["Close"], step),
            "accel2w": compute_weekly_accel_2w(df["Close"], step),
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
