"""
refresh_prices.py
-----------------
Actualiza los precios del dashboard DESDE CERO, sin depender de las carpetas
locales MegaCap/ y LargeCap/. Pensado para correr dentro de GitHub Actions,
donde lo unico disponible es lo que esta en el repositorio.

Que hace:
  1. Lee la lista de tickers de data/company_info.json
  2. Baja el historial diario de Yahoo (endpoint publico de chart, sin crumb)
  3. Escribe data/precios/{ticker}.csv     (ultimas N_ROWS_KEEP sesiones)
  4. Escribe data/precios_semanal/{ticker}.csv (ultimas N_WEEKS_KEEP semanas)

Criterios de robustez:
  - Si un ticker falla, se DEJA INTACTO su CSV anterior (nunca se borra ni se
    reemplaza por datos incompletos).
  - Si el archivo nuevo es identico al viejo, no se reescribe (evita ruido en git).
  - Si fallan demasiados tickers, el script termina con error para que la Action
    quede en rojo y llegue el aviso, en vez de dejar datos viejos en silencio.

Uso local:  python scripts/refresh_prices.py
            python scripts/refresh_prices.py --limit 20     (prueba rapida)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import sys
import time

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRECIOS_DIR = os.path.join(DATA_DIR, "precios")
SEMANAL_DIR = os.path.join(DATA_DIR, "precios_semanal")
COMPANY_INFO = os.path.join(DATA_DIR, "company_info.json")

SELLO_PATH = os.path.join(DATA_DIR, "_ultima_actualizacion.json")

N_ROWS_KEEP = 1250     # diario: SMA200 + ~1000 sesiones para graficar
N_WEEKS_KEEP = 600     # semanal: ~11 años, para que la SMA200 semanal tenga recorrido

SLEEP_BETWEEN = 0.6    # pausa entre tickers, para no gatillar rate-limit de Yahoo
MAX_FAIL_RATIO = 0.20  # si falla mas del 20% de los tickers, la corrida se marca como fallida

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
}


def fetch_prices(ticker: str, retries: int = 3):
    """Historial diario completo desde el endpoint publico de Yahoo.

    Este endpoint (v8/finance/chart) no exige cookie/crumb, a diferencia del de
    opciones. Devuelve None si no se pudo obtener.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": 0, "period2": int(time.time()), "interval": "1d", "events": "div,splits"}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                d = r.json()
                if d.get("chart", {}).get("error"):
                    last_err = d["chart"]["error"]
                    break
                result = d["chart"]["result"]
                if not result:
                    last_err = "respuesta vacia"
                    break
                return result[0]
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (429, 503):        # rate-limit: esperar mas
                time.sleep(5 + attempt * 10)
                continue
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(2 + attempt * 3)
    print(f"  FALLO {ticker}: {last_err}", flush=True)
    return None


def result_to_df(result) -> pd.DataFrame | None:
    ts = result.get("timestamp") or []
    q = result.get("indicators", {}).get("quote", [{}])[0]
    opens, highs, lows, closes, vols = (q.get("open"), q.get("high"), q.get("low"),
                                        q.get("close"), q.get("volume"))
    if not ts or closes is None:
        return None
    rows = []
    for i in range(len(ts)):
        if None in (closes[i], highs[i], lows[i], vols[i], opens[i]):
            continue
        rows.append({
            "Date": datetime.datetime.utcfromtimestamp(ts[i]).strftime("%Y-%m-%d"),
            "Open": round(float(opens[i]), 2), "High": round(float(highs[i]), 2),
            "Low": round(float(lows[i]), 2), "Close": round(float(closes[i]), 2),
            "Volume": int(vols[i]),
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


def to_csv_text(df: pd.DataFrame) -> str:
    out = df.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    buf = io.StringIO()
    out.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def write_if_changed(path: str, text: str) -> bool:
    """Escribe solo si el contenido cambio. Devuelve True si hubo escritura."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", newline="") as f:
            if f.read() == text:
                return False
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return True


def weekly_from_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Barras semanales con cierre el viernes (mismo criterio que el dashboard)."""
    wk = (df.set_index("Date")
            .resample("W-FRI")
            .agg({"Open": "first", "High": "max", "Low": "min",
                  "Close": "last", "Volume": "sum"})
            .dropna(subset=["Close"])
            .reset_index()
            .tail(N_WEEKS_KEEP))
    for c in ["Open", "High", "Low", "Close"]:
        wk[c] = wk[c].round(2)
    wk["Volume"] = wk["Volume"].astype("int64")
    return wk


def escribir_sello(ok: int, failed: int, ultima_sesion: str | None):
    """Deja constancia de cuando se actualizaron los precios, para mostrarlo en
    el dashboard. Se guarda en UTC (sin ambigüedad) y la app lo convierte."""
    from zoneinfo import ZoneInfo
    ahora = datetime.datetime.now(datetime.timezone.utc)
    sello = {
        "utc": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "ny": ahora.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z"),
        "tickers_ok": ok,
        "tickers_fallidos": failed,
        "ultima_sesion": ultima_sesion,
    }
    with open(SELLO_PATH, "w", encoding="utf-8") as f:
        json.dump(sello, f, ensure_ascii=False, indent=1)
    print(f"Sello de actualizacion: {sello['ny']} (ultima sesion con datos: {ultima_sesion})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="procesar solo los primeros N tickers (para pruebas)")
    args = ap.parse_args()

    if not os.path.exists(COMPANY_INFO):
        sys.exit(f"ERROR: no encuentro {COMPANY_INFO}")

    with open(COMPANY_INFO, encoding="utf-8") as f:
        tickers = sorted(json.load(f).keys())
    if args.limit:
        tickers = tickers[:args.limit]

    os.makedirs(PRECIOS_DIR, exist_ok=True)
    os.makedirs(SEMANAL_DIR, exist_ok=True)

    print(f"Actualizando precios de {len(tickers)} tickers...", flush=True)
    t0 = time.time()
    ok = failed = changed = 0
    fallidos = []
    ultima_sesion = None    # fecha mas reciente vista en los datos

    for i, ticker in enumerate(tickers, start=1):
        res = fetch_prices(ticker)
        if res is None:
            failed += 1
            fallidos.append(ticker)
            time.sleep(SLEEP_BETWEEN)
            continue

        df = result_to_df(res)
        if df is None or df.empty:
            failed += 1
            fallidos.append(ticker)
            time.sleep(SLEEP_BETWEEN)
            continue

        if write_if_changed(os.path.join(PRECIOS_DIR, f"{ticker}.csv"),
                            to_csv_text(df.tail(N_ROWS_KEEP))):
            changed += 1
        write_if_changed(os.path.join(SEMANAL_DIR, f"{ticker}.csv"),
                         to_csv_text(weekly_from_daily(df)))
        ok += 1

        fecha = df["Date"].max().strftime("%Y-%m-%d")
        if ultima_sesion is None or fecha > ultima_sesion:
            ultima_sesion = fecha

        if i % 50 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] ok={ok} fallidos={failed} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        time.sleep(SLEEP_BETWEEN)

    print(f"\nResumen: {ok} actualizados, {changed} con datos nuevos, {failed} fallidos "
          f"en {(time.time()-t0)/60:.1f} min")
    if fallidos:
        print("Tickers fallidos:", ", ".join(fallidos[:40]) + ("..." if len(fallidos) > 40 else ""))

    ratio = failed / max(len(tickers), 1)
    if ratio > MAX_FAIL_RATIO:
        # No se escribe el sello: si la corrida fue mala, el dashboard debe seguir
        # mostrando la fecha de la ultima actualizacion que si funciono.
        sys.exit(f"ERROR: fallo el {ratio:.0%} de los tickers (umbral {MAX_FAIL_RATIO:.0%}). "
                 "Probablemente Yahoo esta bloqueando o limitando las peticiones.")

    escribir_sello(ok, failed, ultima_sesion)
    print("OK")


if __name__ == "__main__":
    main()
