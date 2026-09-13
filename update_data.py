"""
update_data.py
---------------
Reconstruye la carpeta /data del dashboard integrado (Streamlit) a partir de
lo que ya tengan descargado los dashboards de Megacap y Large Cap (sus
carpetas Datos/precios_diarios y Datos/fundamentales_variacion).

Uso:
    1) Corre primero (si quieres datos frescos) los .bat de Megacap y Large Cap
       para actualizar sus propios datos:
         - Fintual/MegaCap/Actualizar_Precios.bat + Actualizar_Financieros.bat
         - Fintual/LargeCap/Actualizar_Precios_LargeCap.bat + Actualizar_Financieros_LargeCap.bat
    2) Corre este script (o Actualizar_Datos_Dashboard.bat) para refrescar /data
       de este proyecto Streamlit con lo ultimo que haya en esas carpetas.
    3) git add -A && git commit -m "actualizar datos" && git push
       (Streamlit Community Cloud redeploya solo al detectar el push)
"""

import os
import sys
import json
import shutil
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRECIOS_OUT = os.path.join(DATA_DIR, "precios")
SEMANAL_OUT = os.path.join(DATA_DIR, "precios_semanal")
FUND_OUT = os.path.join(DATA_DIR, "fundamentales_variacion")

# Rutas esperadas de los proyectos "fuente" (Megacap y Large Cap), relativas a
# la carpeta Fintual/ que contiene tanto MegaCap/, LargeCap/ como este proyecto.
FINTUAL_DIR = os.path.dirname(BASE_DIR)  # asumiendo que este proyecto vive en Fintual/DashboardIntegrado
MEGACAP_DATOS = os.path.join(FINTUAL_DIR, "MegaCap", "Datos")
LARGECAP_DATOS = os.path.join(FINTUAL_DIR, "LargeCap", "Datos")

N_ROWS_KEEP = 1250    # diario: suficiente para SMA200 + ~1000 sesiones de despliegue
N_WEEKS_KEEP = 600    # semanal: ~11 años, para que la SMA200 semanal tenga recorrido

SECTOR_ES = {
    "Technology": "Tecnología", "Health Care": "Salud", "Finance": "Financiero",
    "Consumer Discretionary": "Consumo discrecional", "Consumer Staples": "Consumo básico",
    "Industrials": "Industrial", "Energy": "Energía", "Utilities": "Servicios públicos",
    "Real Estate": "Bienes raíces", "Basic Materials": "Materiales",
    "Telecommunications": "Servicios de comunicación", "Miscellaneous": "Diversos",
    "Sin clasificar": "Sin clasificar",
}


def check_sources():
    missing = []
    if not os.path.isdir(MEGACAP_DATOS):
        missing.append(MEGACAP_DATOS)
    if not os.path.isdir(LARGECAP_DATOS):
        missing.append(LARGECAP_DATOS)
    if missing:
        print("ERROR: no encuentro las carpetas fuente:")
        for m in missing:
            print(" -", m)
        print("\nEste script asume que la carpeta de este proyecto Streamlit vive")
        print("dentro de Fintual/, junto a MegaCap/ y LargeCap/ (ej. Fintual/DashboardIntegrado/).")
        print("Si la moviste a otro lugar, edita MEGACAP_DATOS y LARGECAP_DATOS arriba en este archivo.")
        sys.exit(1)


def rebuild_company_info():
    sys.path.insert(0, os.path.join(FINTUAL_DIR, "MegaCap", "Scripts"))
    sys.path.insert(0, os.path.join(FINTUAL_DIR, "LargeCap", "Scripts"))
    import fintual_common as mc
    import largecap_common as lc

    merged = {}
    for t, name in mc.TICKERS_INFO.items():
        info = mc.COMPANY_INFO.get(t, {})
        merged[t] = {
            "name": name, "sector": info.get("sector", "Sin clasificar"),
            "industry": info.get("industry", ""), "desc": info.get("desc", ""),
            "universe": "Megacap (>$200B)", "source_dir": "megacap",
        }
    for t in lc.TICKERS:
        if t in merged:
            continue
        info = lc.COMPANY_INFO.get(t, {})
        merged[t] = {
            "name": info.get("name", t), "sector": info.get("sector", "Sin clasificar"),
            "industry": info.get("industry", ""), "desc": info.get("desc", ""),
            "universe": "Large Cap ($10B-$200B)", "source_dir": "largecap",
        }
    with open(os.path.join(DATA_DIR, "company_info.json"), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print(f"company_info.json: {len(merged)} empresas ({sum(1 for v in merged.values() if v['source_dir']=='megacap')} megacap, "
          f"{sum(1 for v in merged.values() if v['source_dir']=='largecap')} large cap)")
    return merged


def rebuild_prices(tickers):
    """Genera el CSV diario recortado y, desde el historial COMPLETO, las barras
    semanales (que necesitan muchos más años para una SMA200 semanal útil)."""
    os.makedirs(PRECIOS_OUT, exist_ok=True)
    os.makedirs(SEMANAL_OUT, exist_ok=True)
    keep = ["Date", "Open", "High", "Low", "Close", "Volume"]
    n_ok = n_sem = 0
    for t, info in tickers.items():
        src_dir = MEGACAP_DATOS if info["source_dir"] == "megacap" else LARGECAP_DATOS
        src = os.path.join(src_dir, "precios_diarios", f"{t}.csv")
        if not os.path.exists(src):
            continue
        full = pd.read_csv(src, parse_dates=["Date"])
        full = full[[c for c in keep if c in full.columns]]
        full = full.sort_values("Date").dropna(subset=["Open", "High", "Low", "Close", "Volume"])

        # --- diario (recortado) ---
        df = full.tail(N_ROWS_KEEP).copy()
        for c in ["Open", "High", "Low", "Close"]:
            df[c] = df[c].round(2)
        df.to_csv(os.path.join(PRECIOS_OUT, f"{t}.csv"), index=False)
        n_ok += 1

        # --- semanal (desde todo el historial disponible) ---
        wk = (full.set_index("Date")
                  .resample("W-FRI")
                  .agg({"Open": "first", "High": "max", "Low": "min",
                        "Close": "last", "Volume": "sum"})
                  .dropna(subset=["Close"])
                  .reset_index()
                  .tail(N_WEEKS_KEEP))
        for c in ["Open", "High", "Low", "Close"]:
            wk[c] = wk[c].round(2)
        wk.to_csv(os.path.join(SEMANAL_OUT, f"{t}.csv"), index=False)
        n_sem += 1

    print(f"precios diarios: {n_ok}/{len(tickers)} tickers")
    print(f"precios semanales: {n_sem}/{len(tickers)} tickers")


def rebuild_fundamentals(tickers):
    os.makedirs(FUND_OUT, exist_ok=True)
    n_ok = 0
    for t, info in tickers.items():
        src_dir = MEGACAP_DATOS if info["source_dir"] == "megacap" else LARGECAP_DATOS
        for suffix in ["anual_variacion", "trimestral_variacion"]:
            src = os.path.join(src_dir, "fundamentales_variacion", f"{t}_{suffix}.csv")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(FUND_OUT, f"{t}_{suffix}.csv"))
                n_ok += 1
    print(f"fundamentales: {n_ok} archivos copiados")


if __name__ == "__main__":
    check_sources()
    os.makedirs(DATA_DIR, exist_ok=True)
    tickers = rebuild_company_info()
    rebuild_prices(tickers)
    rebuild_fundamentals(tickers)
    print("\nListo. Ahora sube los cambios con git:")
    print("  git add -A")
    print('  git commit -m "actualizar datos"')
    print("  git push")
