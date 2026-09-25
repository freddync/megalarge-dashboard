"""Diagnóstico de la cadena de opciones de Yahoo (yfinance).

Muestra qué trae Yahoo para unos tickers y qué queda después del procesamiento
del dashboard. Escribe todo en diagnostico_opciones.txt (en esta misma carpeta).
Uso: doble click en Diagnostico_Opciones.bat, o  python diagnostico_opciones.py NVDA AAPL
"""
import os
import sys
import traceback
import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))  # carpeta DashboardIntegrado

SALIDA = os.path.join(AQUI, "diagnostico_opciones.txt")
TICKERS = sys.argv[1:] or ["NVDA", "AAPL", "MSFT"]

lineas = []


def log(*a):
    txt = " ".join(str(x) for x in a)
    print(txt)
    lineas.append(txt)


def main():
    import pandas as pd
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)

    log("Fecha local:", datetime.datetime.now().isoformat(timespec="seconds"))
    log("Python:", sys.version.split()[0])
    try:
        import yfinance as yf
        log("yfinance:", yf.__version__)
    except Exception as e:
        log("NO SE PUDO IMPORTAR yfinance:", repr(e))
        return
    log("pandas:", pd.__version__)

    import options_layer as ol

    for tk in TICKERS:
        log("\n" + "=" * 70)
        log("TICKER", tk)
        log("=" * 70)
        try:
            t = yf.Ticker(tk)
            exps = t.options
            log("Vencimientos (primeros 6):", list(exps)[:6], "| total:", len(exps))
            for exp in list(exps)[:2]:
                ch = t.option_chain(exp)
                for nombre, df in (("CALLS", ch.calls), ("PUTS", ch.puts)):
                    log(f"\n-- {exp} {nombre}: {len(df)} filas")
                    log("Columnas:", list(df.columns))
                    if len(df):
                        for c in ("openInterest", "impliedVolatility", "volume", "bid", "ask"):
                            if c in df.columns:
                                s = pd.to_numeric(df[c], errors="coerce")
                                log(f"  {c:18s} nulos={int(s.isna().sum()):4d}  ceros={int((s == 0).sum()):4d}  "
                                    f"min={s.min()}  max={s.max()}")
                        cols = [c for c in ("strike", "lastPrice", "bid", "ask", "volume",
                                            "openInterest", "impliedVolatility") if c in df.columns]
                        mid = len(df) // 2
                        log(df[cols].iloc[max(0, mid - 4): mid + 4].to_string())
        except Exception:
            log("ERROR leyendo yfinance directo:\n" + traceback.format_exc())

        log("\n-- Procesamiento del dashboard (options_layer) --")
        try:
            spot, avg_vol, raw = ol.fetch_chains(tk)
            log("Spot:", spot, "| vol prom 5d:", avg_vol, "| vencimientos:", [(c["exp"], c["dte"]) for c in raw])
            for c in raw:
                calls, puts, levels = ol.build_levels(spot, c["dte"], c["calls"], c["puts"])
                log(f"{c['exp']}: calls procesados={len(calls)} puts={len(puts)} niveles={len(levels)} "
                    f"OI total calls={int(levels['call_oi'].sum()) if len(levels) else 0} "
                    f"puts={int(levels['put_oi'].sum()) if len(levels) else 0}")
                log("   Call walls:", [(w["strike"], w["oi"]) for w in ol.top_walls(calls, 2)])
                log("   Put walls: ", [(w["strike"], w["oi"]) for w in ol.top_walls(puts, 2)])
        except Exception:
            log("ERROR en options_layer:\n" + traceback.format_exc())

        log("\n-- Velas horarias (fetch_intraday) --")
        try:
            bars = ol.fetch_intraday(tk)
            log(f"{len(bars)} velas, desde {bars.index[0]} hasta {bars.index[-1]}")
        except Exception:
            log("ERROR en fetch_intraday:\n" + traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("ERROR GENERAL:\n" + traceback.format_exc())
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    print(f"\nResultado guardado en {SALIDA}")
