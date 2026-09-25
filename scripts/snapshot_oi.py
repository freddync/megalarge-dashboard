"""
snapshot_oi.py
--------------
Foto diaria del Open Interest (OI) y del volumen de contratos de las Megacap.

Yahoo solo entrega el OI "de hoy", así que para ver cómo evoluciona un muro hay
que ir guardándolo día a día. Este script corre una vez al día DESPUÉS del
cierre (GitHub Actions, ~17:00 NY). En ese momento:
  - el OI que muestra Yahoo corresponde al cierre del día hábil ANTERIOR (la OCC
    lo publica de noche y Yahoo lo actualiza en la mañana), y
  - el volumen de contratos es el de la sesión completa de hoy.
Así, OI(día D+1) - OI(día D) junto al volumen del día D permite estimar cuántos
contratos se abrieron o cerraron durante D.

Qué guarda (data/oi_hist/{TICKER}.csv), por día:
  fecha, exp, tipo (C/P), strike, oi, vol, iv
  - vencimientos de los próximos MAX_DTE días (máximo MAX_EXPS)
  - strikes dentro de ±STRIKE_WINDOW del precio
  - se descartan filas con OI y volumen en cero
  - se conservan los últimos KEEP_DAYS días de fotos

La "fecha" es la de la última sesión con precio en Yahoo. Si esa fecha ya está
guardada (feriado, o una segunda corrida el mismo día) el ticker se omite, así
que correrlo varias veces es inofensivo.

Uso local:  python scripts/snapshot_oi.py
            python scripts/snapshot_oi.py --limit 5
            python scripts/snapshot_oi.py --tickers NVDA AAPL
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(DATA_DIR, "oi_hist")
COMPANY_INFO = os.path.join(DATA_DIR, "company_info.json")
SELLO_PATH = os.path.join(OUT_DIR, "_ultima_foto.json")

UNIVERSO = "Megacap (>$200B)"
MAX_DTE = 21          # vencimientos de las próximas 3 semanas...
MAX_EXPS = 8          # ...con un máximo de 8 (algunas tienen vencimientos diarios)
STRIKE_WINDOW = 0.20  # ±20% del precio
KEEP_DAYS = 60        # días de fotos que se conservan
SLEEP_BETWEEN = 0.5
MAX_FAIL_RATIO = 0.30

COLS = ["fecha", "exp", "tipo", "strike", "oi", "vol", "iv"]


def megacap_tickers() -> list[str]:
    with open(COMPANY_INFO, encoding="utf-8") as f:
        info = json.load(f)
    return sorted(t for t, v in info.items() if v.get("universe") == UNIVERSO)


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def snapshot_ticker(yf, ticker: str) -> tuple[str, pd.DataFrame]:
    """Devuelve (fecha_sesion, filas) para un ticker."""
    t = yf.Ticker(ticker)
    hist = t.history(period="10d")
    closes = hist["Close"].dropna() if hist is not None and not hist.empty else pd.Series(dtype=float)
    if not len(closes):
        raise RuntimeError("sin precios recientes")
    spot = float(closes.iloc[-1])
    fecha = pd.Timestamp(closes.index[-1]).strftime("%Y-%m-%d")
    if not math.isfinite(spot) or spot <= 0:
        raise RuntimeError("precio inválido")

    hoy = datetime.date.fromisoformat(fecha)
    exps = []
    for e in (t.options or []):
        dte = (datetime.date.fromisoformat(e) - hoy).days
        if 0 <= dte <= MAX_DTE:
            exps.append(e)
        if len(exps) >= MAX_EXPS:
            break
    if not exps:
        raise RuntimeError("sin vencimientos próximos")

    lo, hi = spot * (1 - STRIKE_WINDOW), spot * (1 + STRIKE_WINDOW)
    partes = []
    for e in exps:
        ch = t.option_chain(e)
        for tipo, df in (("C", ch.calls), ("P", ch.puts)):
            if df is None or df.empty:
                continue
            d = pd.DataFrame({
                "strike": _num(df["strike"]),
                "oi": _num(df.get("openInterest")).fillna(0),
                "vol": _num(df.get("volume")).fillna(0),
                "iv": _num(df.get("impliedVolatility")),
            })
            d = d[(d["strike"] >= lo) & (d["strike"] <= hi) & ((d["oi"] > 0) | (d["vol"] > 0))]
            d.insert(0, "tipo", tipo)
            d.insert(0, "exp", e)
            partes.append(d)
        time.sleep(0.15)
    if not partes:
        raise RuntimeError("cadena vacía")
    out = pd.concat(partes, ignore_index=True)
    out.insert(0, "fecha", fecha)
    out["oi"] = out["oi"].astype(int)
    out["vol"] = out["vol"].astype(int)
    out["iv"] = out["iv"].round(4)
    return fecha, out[COLS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tickers", nargs="*", default=None)
    args = ap.parse_args()

    import yfinance as yf

    os.makedirs(OUT_DIR, exist_ok=True)
    tickers = args.tickers or megacap_tickers()
    if args.limit:
        tickers = tickers[: args.limit]

    ok, omitidos, fallidos = [], [], []
    fechas = set()
    for i, tk in enumerate(tickers, 1):
        path = os.path.join(OUT_DIR, f"{tk}.csv")
        try:
            fecha, filas = snapshot_ticker(yf, tk)
            fechas.add(fecha)
            prev = pd.read_csv(path, dtype={"fecha": str, "exp": str}) if os.path.exists(path) else pd.DataFrame(columns=COLS)
            if (prev["fecha"] == fecha).any():
                omitidos.append(tk)
                print(f"[{i}/{len(tickers)}] {tk}: la foto del {fecha} ya existe, se omite")
            else:
                todo = pd.concat([prev, filas], ignore_index=True)
                dias = sorted(todo["fecha"].unique())[-KEEP_DAYS:]
                todo = todo[todo["fecha"].isin(dias)].sort_values(["fecha", "exp", "tipo", "strike"])
                todo.to_csv(path, index=False)
                ok.append(tk)
                print(f"[{i}/{len(tickers)}] {tk}: {len(filas)} filas ({fecha})")
        except Exception as e:  # un ticker malo no debe botar la corrida completa
            fallidos.append(tk)
            print(f"[{i}/{len(tickers)}] {tk}: ERROR {type(e).__name__}: {e}")
        time.sleep(SLEEP_BETWEEN)

    print(f"\nOK: {len(ok)} · ya existían: {len(omitidos)} · fallidos: {len(fallidos)} {fallidos}")
    if ok:
        with open(SELLO_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "fechas_sesion": sorted(fechas),
                "tickers_ok": len(ok), "tickers_fallidos": fallidos,
            }, f, ensure_ascii=False, indent=1)
    if tickers and len(fallidos) / len(tickers) > MAX_FAIL_RATIO:
        print("Demasiados tickers fallidos: se marca la corrida como fallida.")
        sys.exit(1)


if __name__ == "__main__":
    main()
