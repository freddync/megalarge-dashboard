"""
Dashboard integrado Megacap + Large Cap (NYSE/NASDAQ/AMEX) -- SMA100/SMA200.

Corre local con:  streamlit run app.py
"""

import os

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import data_layer as dl
import options_layer as ol

st.set_page_config(page_title="Fintual — Megacap + Large Cap", layout="wide", page_icon="📈")

# Alto total del bloque gráfico y proporción que ocupa el precio (el resto es
# volumen). El panel de opciones usa los mismos valores para quedar alineado.
CHART_HEIGHT = 620
PRICE_ROW_FRAC = 0.74

# ---------------------------------------------------------------------------
# Carga de datos (cacheada)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_company_info():
    return dl.load_company_info()


def data_version():
    """Identificador de la version de los datos que hay en disco.

    Se usa como parte de la clave de cache de los calculos pesados: cuando la
    Action publica precios nuevos, este valor cambia y las caches se recalculan
    solas, sin depender de que el proceso se reinicie.
    """
    sello = get_sello()
    if sello and sello.get("utc"):
        return sello["utc"]
    # sin sello: usar la fecha de modificacion del directorio de precios
    try:
        return str(os.path.getmtime(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "precios")))
    except Exception:
        return "sin-version"


@st.cache_data(ttl=300, show_spinner=False)
def get_sello():
    """Fecha/hora de la ultima actualizacion de precios (TTL corto: cambia dos
    veces al dia y conviene que la app lo refleje pronto tras un redeploy).

    Se lee el JSON directamente, sin pasar por data_layer, a proposito: si el
    entorno quedara con una version desactualizada de ese modulo en memoria
    (pasa en Streamlit Cloud tras un push), esta funcion seguiria andando.
    """
    import json as _json
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "_ultima_actualizacion.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


def texto_actualizacion(summary):
    """Linea legible con cuando se actualizaron los precios y que tan viejo es.

    Es informacion accesoria: si algo falla aca, se devuelve un texto vacio en
    vez de dejar caer todo el dashboard.
    """
    try:
        sello = get_sello()
    except Exception:
        sello = None
    ultima_sesion = summary["last_date"].max() if len(summary) else None

    if not sello:
        # sin sello (datos antiguos o generados a mano): al menos la ultima sesion
        return (f"Última sesión con datos: **{ultima_sesion}**" if ultima_sesion
                else "Sin información de actualización.")

    try:
        from zoneinfo import ZoneInfo
        import datetime as _dt
        ts = _dt.datetime.strptime(sello["utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
        delta = _dt.datetime.now(_dt.timezone.utc) - ts
        horas = delta.total_seconds() / 3600
        if horas < 1:
            antiguedad = f"hace {int(delta.total_seconds() / 60)} min"
        elif horas < 48:
            antiguedad = f"hace {int(horas)} h"
        else:
            antiguedad = f"hace {int(horas / 24)} días"
        ny = ts.astimezone(ZoneInfo("America/New_York")).strftime("%d-%b %H:%M")
        local = ts.astimezone(ZoneInfo("America/Santiago")).strftime("%d-%b %H:%M")
    except Exception:
        return f"Precios actualizados: **{sello.get('ny', sello.get('utc', '?'))}**"

    fallidos = sello.get("tickers_fallidos", 0)
    aviso = f" · ⚠️ {fallidos} empresas sin datos en esa corrida" if fallidos else ""

    # Si la ultima barra es la del dia de hoy en NY, viene de la sesion en curso:
    # su cierre es el precio del momento y el volumen esta incompleto.
    sesion = sello.get("ultima_sesion") or ultima_sesion
    try:
        hoy_ny = _dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        en_curso = " _(sesión en curso: cierre y volumen aún parciales)_" if sesion == hoy_ny else ""
    except Exception:
        en_curso = ""

    return (f"🔄 Precios actualizados: **{ny} NY** ({local} Chile, {antiguedad}) · "
            f"última sesión en los datos: **{sesion}**{en_curso}{aviso}")

@st.cache_data(show_spinner="Calculando SMA y resumen técnico para todas las empresas (primera carga puede tardar ~20s)...")
def get_summary(window, freq=dl.FREQ_DAILY, version=""):
    """`version` no se usa dentro: existe solo para que la cache se invalide
    cuando cambian los datos en disco (ver data_version())."""
    info = get_company_info()
    return dl.build_summary(window, info, freq)

@st.cache_data(show_spinner=False)
def get_price_df(ticker, freq=dl.FREQ_DAILY, version=""):
    return dl.get_series(ticker, freq)

@st.cache_data(show_spinner=False)
def get_fund_annual(ticker):
    return dl.load_fund_csv(ticker, "anual")

@st.cache_data(show_spinner=False)
def get_fund_quarterly(ticker):
    return dl.load_fund_csv(ticker, "trimestral")

@st.cache_data(show_spinner=False)
def get_pe_ev_table(window, freq=dl.FREQ_DAILY, version=""):
    """Tabla con P/E y EV/EBITDA + comparacion sectorial para todas las empresas."""
    summary = get_summary(window, freq, version)
    rows = []
    for _, r in summary.iterrows():
        t = r["ticker"]
        pe = dl.compute_pe(t, r["close"])
        ev = dl.compute_ev_ebitda(t, r["close"])
        m = dl.compute_margins(t)
        rows.append({
            "ticker": t, "sector": r["sector"],
            "pe": pe["pe"] if pe and not pe["negative"] else None,
            "pe_negative": bool(pe and pe["negative"]),
            "ev_ebitda": ev["multiple"] if ev and not ev["negative"] else None,
            "ev_negative": bool(ev and ev["negative"]),
            "revenue": m["revenue"] if m else None,
            "gross_margin": m["gross_margin"] if m else None,
            "op_margin": m["op_margin"] if m else None,
            "net_margin": m["net_margin"] if m else None,
            "revenue_yoy": m["revenue_yoy"] if m else None,
            "netincome_yoy": m["netincome_yoy"] if m else None,
            "capex": m["capex"] if m else None,
            "fcf": m["fcf"] if m else None,
        })
    df = pd.DataFrame(rows)
    # promedios sectoriales (excluye negativos y outliers extremos)
    pe_valid = df[(df.pe_negative == False) & (df.pe > 0) & (df.pe < 200)]
    ev_valid = df[(df.ev_negative == False) & (df.ev_ebitda > 0) & (df.ev_ebitda < 100)]
    sector_pe = pe_valid.groupby("sector")["pe"].mean().to_dict()
    sector_pe_n = pe_valid.groupby("sector")["pe"].count().to_dict()
    sector_ev = ev_valid.groupby("sector")["ev_ebitda"].mean().to_dict()
    sector_ev_n = ev_valid.groupby("sector")["ev_ebitda"].count().to_dict()
    df["pe_vs_sector"] = df.apply(lambda r: (r.pe / sector_pe[r.sector] - 1) * 100
                                   if pd.notna(r.pe) and r.sector in sector_pe else None, axis=1)
    df["ev_vs_sector"] = df.apply(lambda r: (r.ev_ebitda / sector_ev[r.sector] - 1) * 100
                                   if pd.notna(r.ev_ebitda) and r.sector in sector_ev else None, axis=1)
    return df, sector_pe, sector_pe_n, sector_ev, sector_ev_n


@st.cache_data(ttl=900, show_spinner="Descargando cadena de opciones...")
def get_options(ticker):
    """Cadena de opciones de los 2 vencimientos más próximos, ya procesada.

    Devuelve (data, error). Se cachea 15 minutos: las opciones cambian intradía,
    pero no tiene sentido golpear Yahoo en cada rerun de Streamlit.
    A diferencia del resto del dashboard (datos estáticos bundleados en el repo),
    esto SÍ requiere internet en tiempo real.
    """
    try:
        spot, avg_vol_5d, raw_chains = ol.fetch_chains(ticker)
    except ImportError:
        return None, "falta la librería yfinance (agrégala con: pip install yfinance)"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    chains = []
    for ch in raw_chains:
        calls, puts, levels = ol.build_levels(spot, ch["dte"], ch["calls"], ch["puts"])
        if levels.empty:
            continue
        chains.append({
            "exp": ch["exp"], "dte": ch["dte"],
            "calls": calls, "puts": puts, "levels": levels,
            "call_walls": ol.top_walls(calls, 2),
            "put_walls": ol.top_walls(puts, 2),
            "total_gex": ol.total_gex(levels),
            "gamma_flip": ol.gamma_flip(levels),
        })
    return {"spot": spot, "avg_vol_5d": avg_vol_5d, "chains": chains}, None


@st.cache_data(ttl=900, show_spinner="Descargando velas horarias...")
def get_intraday(ticker):
    """Velas de 1 hora de la última semana. Devuelve (df, error). Cache 15 min."""
    try:
        return ol.fetch_intraday(ticker), None
    except ImportError:
        return None, "falta la librería requests"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


WALL_STYLE = {"CW1": "#3ecf8e", "CW2": "#6de08c", "PW1": "#ef5a6f", "PW2": "#f0a8b0"}
ESTADO_COLOR = {"Rebotando": "#3ecf8e", "Probando": "#e6b45e", "Acercándose": "#5ea8e6",
                "Rompió ↑": "#ef5a6f", "Rompió ↓": "#ef5a6f", "Lejos": "#8b93a3"}


def chain_walls(chain):
    """[(tag, wall)] en orden CW2, CW1, PW1, PW2 (de arriba hacia abajo)."""
    out = []
    cw, pw = chain["call_walls"], chain["put_walls"]
    if len(cw) > 1: out.append(("CW2", cw[1]))
    if cw: out.append(("CW1", cw[0]))
    if pw: out.append(("PW1", pw[0]))
    if len(pw) > 1: out.append(("PW2", pw[1]))
    return out


def build_week_walls_chart(bars, chain, estados):
    """Velas de 1 hora de la última semana + muros extendidos hasta el vencimiento.

    El eje X salta noches y fines de semana (rangebreaks), así que el espacio en
    blanco a la derecha es proporcional a las horas de mercado que quedan hasta
    el cierre del día de vencimiento.
    """
    # cierre del día de vencimiento (15:59 para no caer justo en el corte de la noche)
    exp_dt = pd.Timestamp(chain["exp"]) + pd.Timedelta(hours=15, minutes=59)
    now_dt = bars.index[-1]
    x_end = max(exp_dt, now_dt + pd.Timedelta(hours=1))

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=bars.index, open=bars["Open"], high=bars["High"], low=bars["Low"], close=bars["Close"],
        increasing_line_color="#3ecf8e", decreasing_line_color="#ef5a6f",
        increasing_fillcolor="#3ecf8e", decreasing_fillcolor="#ef5a6f",
        name="Velas 1h", showlegend=False))

    zone = ol.WALL_ZONE_PCT / 100
    y_vals = [bars["Low"].min(), bars["High"].max()]
    for tag, w in chain_walls(chain):
        k, color = w["strike"], WALL_STYLE[tag]
        est = estados.get(tag, {}).get("estado", "")
        y_vals.append(k)
        # zona de contacto sombreada (±WALL_ZONE_PCT) y línea del strike
        fig.add_shape(type="rect", x0=bars.index[0], x1=x_end, y0=k * (1 - zone), y1=k * (1 + zone),
                      fillcolor=color, opacity=0.07, line_width=0, layer="below")
        fig.add_trace(go.Scatter(
            x=[bars.index[0], x_end], y=[k, k], mode="lines",
            line=dict(color=color, width=1.4, dash="dot"),
            name=f"{tag} {k:,.2f} · {est} · OI {ol.fmt_qty(w['oi'])}",
            hovertemplate=f"{tag}: {k:,.2f}<br>{est}<extra></extra>"))
        fig.add_annotation(x=x_end, y=k, text=f"{tag} {k:,.2f} · {est}", showarrow=False,
                           xanchor="right", yanchor="bottom", xshift=-4, font=dict(size=10, color=color),
                           bgcolor="rgba(23,26,33,0.7)")

    last = float(bars["Close"].iloc[-1])
    fig.add_trace(go.Scatter(x=[now_dt, x_end], y=[last, last], mode="lines",
                             line=dict(color="#e6e8ec", width=1, dash="dashdot"),
                             name=f"Precio actual {last:,.2f}",
                             hovertemplate=f"Precio actual: {last:,.2f}<extra></extra>"))

    for x, label, color, anchor in ((now_dt, "Hoy", "#e6e8ec", "left"),
                                    (exp_dt, f"Vence {chain['exp']}", "#e6b45e", "right")):
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
                      line=dict(color=color, width=1, dash="dash"))
        fig.add_annotation(x=x, y=1, yref="paper", text=label, showarrow=False,
                           xanchor=anchor, yanchor="top", font=dict(size=10, color=color))
    # zona futura (sin datos todavía) levemente sombreada
    if exp_dt > now_dt:
        fig.add_shape(type="rect", x0=now_dt, x1=x_end, y0=0, y1=1, yref="paper",
                      fillcolor="#e6b45e", opacity=0.04, line_width=0, layer="below")

    lo, hi = min(y_vals), max(y_vals)
    pad = (hi - lo) * 0.06 or hi * 0.01
    fig.update_yaxes(range=[lo - pad, hi + pad])
    fig.update_xaxes(range=[bars.index[0] - pd.Timedelta(minutes=30), x_end],
                     rangeslider_visible=False,
                     rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")])
    fig.update_layout(height=460, template="plotly_dark", plot_bgcolor="#171a21",
                      paper_bgcolor="#171a21", margin=dict(t=10, b=10),
                      legend=dict(orientation="h", x=0, y=-0.08, xanchor="left", yanchor="top",
                                  font=dict(size=10.5)))
    return fig

def fmt_pct(x):
    if x is None or pd.isna(x):
        return "—"
    return f"{'+' if x >= 0 else ''}{x:.2f}%"

def fmt_money(x):
    if x is None or pd.isna(x):
        return "—"
    ax = abs(x)
    if ax >= 1e9:
        return f"{x/1e9:.2f}B"
    if ax >= 1e6:
        return f"{x/1e6:.1f}M"
    return f"{x:,.2f}"

ZONE_COLOR = {
    "Sobrecomprado": "#3ecf8e", "Alcista": "#8fd6b5", "Bajista": "#f0a8b0",
    "Sobrevendido": "#ef5a6f", "Sin datos": "#8b93a3",
}


def build_fund_table_t(df, is_annual):
    """Tabla fundamental traspuesta: métricas en las filas, periodos en las columnas.

    Los años fiscales se rotulan FY{año} (convención estándar: el año en que cierra
    el ejercicio, que varía por empresa). Los trimestres muestran YYYY-MM porque
    ahí el mes sí identifica de qué trimestre se trata.

    En la tabla anual, después de cada año se intercala una columna "FY#### YoY"
    con la variación porcentual respecto al año anterior (el primer año no la lleva
    porque no hay periodo previo con qué compararlo).

    Devuelve (tabla, columnas_yoy) para poder colorear esas columnas aparte.
    """
    if df is None or df.empty:
        return None, []

    # (encabezado, tipo, indice de la fila del periodo)
    col_spec = []
    for i, d in enumerate(df["Date"]):
        header = ("FY" + str(d)[:4]) if is_annual else str(d)[:7]
        col_spec.append((header, "valor", i))
        if is_annual and i > 0:
            col_spec.append((f"{header} YoY", "yoy", i))

    data = {}
    for key, label, raw in dl.FUND_ROWS:
        if key not in df.columns:
            continue
        vals = []
        for _, kind, i in col_spec:
            r = df.iloc[i]
            if kind == "yoy":
                pv = r.get(f"{key}_var_pct")
                vals.append(fmt_pct(pv) if pd.notna(pv) else "—")
            else:
                v = r.get(key)
                if pd.isna(v):
                    vals.append("—")
                elif raw:
                    vals.append(f"{float(v):.2f}")
                else:
                    vals.append(fmt_money(v))
        data[label] = vals

    if not data:
        return None, []

    headers = [h for h, _, _ in col_spec]
    out = pd.DataFrame(data, index=headers).T
    out.index.name = "Métrica"
    yoy_cols = [h for h, kind, _ in col_spec if kind == "yoy"]
    return out, yoy_cols


def style_yoy(table, yoy_cols):
    """Pinta en verde/rojo las columnas YoY según el signo."""
    if not yoy_cols:
        return table

    def color(v):
        if isinstance(v, str):
            if v.startswith("+"):
                return "color: #3ecf8e;"
            if v.startswith("-"):
                return "color: #ef5a6f;"
        return ""

    try:
        return table.style.map(color, subset=yoy_cols)
    except Exception:
        # pandas < 2.1 usa applymap; si tampoco existe, se muestra sin color
        try:
            return table.style.applymap(color, subset=yoy_cols)
        except Exception:
            return table

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Navegacion entre vistas
# ---------------------------------------------------------------------------
# Streamlit no deja modificar el estado de un widget despues de instanciarlo,
# asi que los "saltos" de vista se dejan pendientes en session_state y se
# aplican aca arriba, ANTES de crear el radio de Vista y el selectbox de Empresa.

# Las tablas usan una "key" con un contador (nonce). Al incrementarlo, Streamlit
# considera que es un widget nuevo y lo vuelve a montar, con lo que la seleccion
# (fila o columna) queda realmente limpia. Borrar la key de session_state no basta:
# el frontend puede conservar la columna marcada y volver a disparar el ordenamiento.
if "_tbl_nonce" not in st.session_state:
    st.session_state["_tbl_nonce"] = 0


def reset_tables():
    """Fuerza el re-montado de las tablas del listado (limpia la selección)."""
    st.session_state["_tbl_nonce"] += 1


def table_key(base):
    return f"{base}_{st.session_state['_tbl_nonce']}"


if "_goto_ticker" in st.session_state:
    st.session_state["view"] = "Empresa"
    st.session_state["ticker_sel"] = st.session_state.pop("_goto_ticker")
    # limpiar la seleccion: si no, al volver a General la fila sigue marcada
    # y nos rebotaria de inmediato a la vista Empresa otra vez.
    reset_tables()

if st.session_state.pop("_goto_general", False):
    st.session_state["view"] = "General"

# Orden de las tablas del listado general. El orden nativo de st.dataframe (el que
# hace el frontend al clickear un titulo) NO es visible desde Python y se pierde al
# cambiar de vista, asi que lo manejamos nosotros: guardamos columna + direccion en
# session_state (claves que NO son de widgets, por lo que sobreviven la navegacion)
# y ordenamos con pandas antes de dibujar la tabla.

_TEXT_COLS = {"Ticker", "Nombre", "Universo", "Sector", "Zona", "Señal RSI", "Señal MACD"}

_pending_sort = st.session_state.pop("_pending_sort", None)
if _pending_sort:
    _which, _col = _pending_sort
    _col_key, _asc_key = f"sort_{_which}_col", f"sort_{_which}_asc"
    if st.session_state.get(_col_key) == _col:
        # mismo titulo clickeado de nuevo -> invertir la direccion
        st.session_state[_asc_key] = not st.session_state.get(_asc_key, True)
    else:
        st.session_state[_col_key] = _col
        # texto: A-Z; numerico: de mayor a menor (que suele ser lo util)
        st.session_state[_asc_key] = _col in _TEXT_COLS
    # limpiar la seleccion para que un segundo click sobre el mismo titulo se
    # registre como click nuevo (y alcance a invertir el orden)
    reset_tables()


def _selected_rows(selection):
    """Indices de filas seleccionadas en un st.dataframe (o lista vacia)."""
    try:
        return list(selection.selection.rows)
    except Exception:
        try:
            return list((selection or {}).get("selection", {}).get("rows", []))
        except Exception:
            return []


def maybe_open_empresa(selection, df_shown, col="Ticker"):
    """Si el usuario clickeo una fila del listado, salta al analisis de esa empresa."""
    rows = _selected_rows(selection)
    if not rows:
        return
    st.session_state["_goto_ticker"] = str(df_shown.iloc[rows[0]][col])
    st.rerun()


def _selected_columns(selection):
    """Titulos de columna seleccionados en un st.dataframe (o lista vacia)."""
    try:
        return list(selection.selection.columns)
    except Exception:
        try:
            return list((selection or {}).get("selection", {}).get("columns", []))
        except Exception:
            return []


def handle_header_sort(selection, which):
    """Click en el titulo de una columna -> ordenar por ella y dejarlo guardado.

    Ojo: cuando la tabla tiene habilitada la seleccion de filas Y de columnas,
    Streamlit marca AMBAS al clickear una celda. Si en ese caso ordenaramos,
    entrar a una empresa se sentiria como si se hubiera vuelto a apretar el
    titulo de la columna. Por eso, si viene una fila seleccionada, manda la
    navegacion y aca no hacemos nada.
    """
    if _selected_rows(selection):
        return
    cols = _selected_columns(selection)
    if not cols:
        return
    st.session_state["_pending_sort"] = (which, str(cols[0]))
    st.rerun()


# Columnas cuyo orden NO es alfabético sino conceptual. La Zona va de más
# sobrevendido a más sobrecomprado, que es como se lee de menor a mayor.
# Los valores que no estén en el mapa (ej. "Sin datos") quedan como NaN y se
# van siempre al final, igual que las celdas vacías de las columnas numéricas.
ZONE_ORDER = {"Sobrevendido": 0, "Bajista": 1, "Alcista": 2, "Sobrecomprado": 3}

# RSI: de sobreventa a sobrecompra, igual criterio que la Zona
RSI_ORDER = {"Sobreventa": 0, "Neutral": 1, "Sobrecompra": 2}

# MACD: sigue el ciclo del indicador, de lo más bajista a lo más alcista.
# "Perdiendo fuerza" (histograma positivo pero cayendo) es la señal de venta y
# "Pre-cruce" (negativo pero subiendo) la de compra anticipada.
MACD_ORDER = {"Bajista": 0, "Perdiendo fuerza": 1, "Pre-cruce": 2, "Alcista": 3}

ORDINAL_COLS = {"Zona": ZONE_ORDER, "Señal RSI": RSI_ORDER, "Señal MACD": MACD_ORDER}


def apply_saved_sort(df, which, colmap):
    """Ordena el DataFrame segun lo guardado en session_state para esa tabla.

    `colmap` mapea el nombre visible de la columna -> el nombre de la columna con
    el valor crudo (numerico), para no ordenar alfabeticamente strings como '35.5x'.
    Las columnas de ORDINAL_COLS se ordenan por su posición conceptual.
    """
    disp_col = st.session_state.get(f"sort_{which}_col")
    if not disp_col:
        return df
    raw_col = colmap.get(disp_col)
    if raw_col is None or raw_col not in df.columns:
        return df
    asc = st.session_state.get(f"sort_{which}_asc", True)

    order_map = ORDINAL_COLS.get(disp_col)
    if order_map is not None:
        tmp = "_orden_"
        return (df.assign(**{tmp: df[raw_col].map(order_map)})
                  .sort_values(tmp, ascending=asc, na_position="last", kind="mergesort")
                  .drop(columns=tmp))

    return df.sort_values(raw_col, ascending=asc, na_position="last", kind="mergesort")


def sort_caption(which):
    disp_col = st.session_state.get(f"sort_{which}_col")
    if not disp_col:
        return "Orden actual: por defecto (Ticker A-Z)."
    arrow = "▲ asc." if st.session_state.get(f"sort_{which}_asc", True) else "▼ desc."
    return f"Orden actual: **{disp_col}** {arrow} — se mantiene al entrar y volver de una empresa."


st.sidebar.title("📈 Fintual")
st.sidebar.caption("Megacap (>$200B) + Large Cap ($10B-$200B) · NYSE/NASDAQ/AMEX")

view = st.sidebar.radio("Vista", ["General", "Empresa"], horizontal=True, key="view")

freq = st.sidebar.radio("Frecuencia", [dl.FREQ_DAILY, dl.FREQ_WEEKLY], horizontal=True, key="freq",
                        help="Diaria usa cada sesión; Semanal agrupa por semana (cierre el viernes): "
                             "apertura de la primera sesión, máximo y mínimo de la semana, cierre de la "
                             "última y volumen sumado.")

unidad = "días" if freq == dl.FREQ_DAILY else "semanas"
sma_window = 100        # fija: la SMA 100 es la ventana del proyecto
st.sidebar.caption(f"Indicadores: **SMA {sma_window}** (banda ±1.5σ) · **RSI {dl.RSI_PERIOD}** "
                   f"({dl.RSI_SOBRECOMPRA}/{dl.RSI_SOBREVENTA}) · "
                   f"**MACD {dl.MACD_FAST}/{dl.MACD_SLOW}/{dl.MACD_SIGNAL}**")

info = get_company_info()
DATA_VERSION = data_version()
summary = get_summary(sma_window, freq, DATA_VERSION)

all_sectors = sorted(summary["sector"].unique())
all_universes = sorted(summary["universe"].unique())

sel_universe = st.sidebar.multiselect("Universo", all_universes, default=all_universes)
sel_sector = st.sidebar.selectbox("Sector", ["Todos"] + all_sectors)

filtered = summary[summary["universe"].isin(sel_universe)]
if sel_sector != "Todos":
    filtered = filtered[filtered["sector"] == sel_sector]

st.sidebar.markdown(f"**{len(filtered)}** empresas en el filtro actual (de {len(summary)} totales)")
st.sidebar.markdown("---")
st.sidebar.markdown(texto_actualizacion(summary))
st.sidebar.caption(
    "Los precios se actualizan solos cada hora, de lunes a viernes entre las 9:00 y las 20:00 "
    "hora de Nueva York, mediante GitHub Actions. Los fundamentales se actualizan a mano cada "
    "trimestre."
)

# ---------------------------------------------------------------------------
# VISTA GENERAL
# ---------------------------------------------------------------------------

if view == "General":
    st.title(f"Resumen general — SMA{sma_window}")
    st.markdown(texto_actualizacion(summary))
    st.caption(
        f"{len(filtered)} empresas · Tres señales **independientes**, cada una ordenable por su propia columna: "
        f"**Zona** = dónde está el precio respecto a la banda SMA{sma_window}±1.5σ · "
        f"**Señal RSI** = RSI {dl.RSI_PERIOD} sobre {dl.RSI_SOBRECOMPRA} (sobrecompra) o bajo "
        f"{dl.RSI_SOBREVENTA} (sobreventa) · "
        f"**Señal MACD** = estado del histograma {dl.MACD_FAST}/{dl.MACD_SLOW}/{dl.MACD_SIGNAL} "
        "(Pre-cruce = compra anticipada, Perdiendo fuerza = venta)")

    tab1, tab2, tab3, tab4 = st.tabs(["Resumen técnico", "Indicadores financieros", "P/E vs. crecimiento", "Resumen por sector"])

    with tab1:
        # Cada indicador aporta su valor numerico y su etiqueta, y ambos son
        # ordenables por separado: se puede ordenar por "Dist. SMA %" o por
        # "Zona", por "RSI 5" o por "Señal RSI", etc.
        raw_cols_1 = ["ticker", "name", "universe", "sector", "close", "sma", "dist_sma_pct",
                      "zone", "rsi", "rsi_signal", "macd_hist_pct", "macd_signal",
                      "r1m", "r3m", "r6m", "r1y"]
        disp_cols_1 = ["Ticker", "Nombre", "Universo", "Sector", "Precio", f"SMA{sma_window}", "Dist. SMA %",
                       "Zona", f"RSI {dl.RSI_PERIOD}", "Señal RSI", "MACD hist %", "Señal MACD",
                       "1m %", "3m %", "6m %", "1a %"]
        colmap_1 = dict(zip(disp_cols_1, raw_cols_1))

        show = apply_saved_sort(filtered[raw_cols_1].copy(), "tecnico", colmap_1)
        show.columns = disp_cols_1

        st.caption("👉 Click en el **ticker** (o en cualquier celda de la fila) para abrir el análisis de esa "
                   "empresa · click en el **título de una columna** para ordenar por ella (vuelve a clickearlo "
                   "para invertir).")
        st.caption(sort_caption("tecnico"))
        sel1 = st.dataframe(show, width="stretch", height=520, hide_index=True,
                            on_select="rerun", selection_mode=["single-row", "single-column"],
                            key=table_key("tbl_tecnico"))
        handle_header_sort(sel1, "tecnico")
        maybe_open_empresa(sel1, show)

    with tab2:
        pe_ev_df, sector_pe, sector_pe_n, sector_ev, sector_ev_n = get_pe_ev_table(sma_window, freq, DATA_VERSION)
        pe_ev_filtered = pe_ev_df[pe_ev_df.ticker.isin(filtered.ticker)]
        show2 = pe_ev_filtered.copy()
        show2["PE"] = show2.apply(lambda r: "N/A (pérdidas)" if r.pe_negative else (f"{r.pe:.1f}x" if pd.notna(r.pe) else "—"), axis=1)
        show2["EV/EBITDA"] = show2.apply(lambda r: "N/A (EBITDA neg.)" if r.ev_negative else (f"{r.ev_ebitda:.1f}x" if pd.notna(r.ev_ebitda) else "—"), axis=1)
        show2["PE vs sector"] = show2["pe_vs_sector"].apply(fmt_pct)
        show2["EV/EBITDA vs sector"] = show2["ev_vs_sector"].apply(fmt_pct)
        show2["Ingresos"] = show2["revenue"].apply(fmt_money)
        show2["Marg. bruto"] = show2["gross_margin"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        show2["Marg. operac."] = show2["op_margin"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        show2["Marg. neto"] = show2["net_margin"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        show2["Crec. ingresos"] = show2["revenue_yoy"].apply(fmt_pct)
        show2["Crec. ut. neta"] = show2["netincome_yoy"].apply(fmt_pct)
        show2["CAPEX"] = show2["capex"].apply(fmt_money)
        show2["FCF"] = show2["fcf"].apply(fmt_money)
        final_cols = ["ticker", "sector", "PE", "PE vs sector", "EV/EBITDA", "EV/EBITDA vs sector",
                      "Ingresos", "Marg. bruto", "Marg. operac.", "Marg. neto", "Crec. ingresos", "Crec. ut. neta", "CAPEX", "FCF"]
        # el orden se aplica sobre las columnas crudas (numericas), no sobre el texto formateado
        colmap_2 = {"Ticker": "ticker", "Sector": "sector", "PE": "pe", "PE vs sector": "pe_vs_sector",
                    "EV/EBITDA": "ev_ebitda", "EV/EBITDA vs sector": "ev_vs_sector", "Ingresos": "revenue",
                    "Marg. bruto": "gross_margin", "Marg. operac.": "op_margin", "Marg. neto": "net_margin",
                    "Crec. ingresos": "revenue_yoy", "Crec. ut. neta": "netincome_yoy",
                    "CAPEX": "capex", "FCF": "fcf"}
        show2 = apply_saved_sort(show2, "financiero", colmap_2)
        show2_final = show2[final_cols].rename(columns={"ticker": "Ticker", "sector": "Sector"})
        st.caption("👉 Click en el **ticker** (o en cualquier celda de la fila) para abrir el análisis de esa "
                   "empresa · click en el **título de una columna** para ordenar por ella (vuelve a clickearlo "
                   "para invertir).")
        st.caption(sort_caption("financiero"))
        sel2 = st.dataframe(show2_final, width="stretch", height=520, hide_index=True,
                            on_select="rerun", selection_mode=["single-row", "single-column"],
                            key=table_key("tbl_financiero"))
        handle_header_sort(sel2, "financiero")
        maybe_open_empresa(sel2, show2_final)
        st.caption("P/E usa EPS diluido TTM (4 trimestres) si hay datos, si no el del último año fiscal. "
                   "EV/EBITDA = (Market Cap + Deuda - Caja) / EBITDA del último año fiscal.")

    with tab3:
        pe_ev_df, sector_pe, sector_pe_n, sector_ev, sector_ev_n = get_pe_ev_table(sma_window, freq, DATA_VERSION)
        pe_ev_filtered = pe_ev_df[pe_ev_df.ticker.isin(filtered.ticker)]
        scatter_df = pe_ev_filtered[(pe_ev_filtered.pe_negative == False) & pe_ev_filtered.pe.notna() & pe_ev_filtered.netincome_yoy.notna()].copy()
        scatter_df["pe_capped"] = scatter_df["pe"].clip(upper=120)
        scatter_df["growth_capped"] = scatter_df["netincome_yoy"].clip(-150, 150)
        if len(scatter_df):
            fig = px.scatter(scatter_df, x="pe_capped", y="growth_capped", color="sector",
                              hover_data={"ticker": True, "pe": ":.1f", "netincome_yoy": ":.1f", "pe_capped": False, "growth_capped": False},
                              labels={"pe_capped": "P/E Ratio", "growth_capped": "Crecimiento utilidad neta YoY (%)", "sector": "Sector"})
            fig.update_traces(marker=dict(size=9, opacity=0.8))
            fig.update_layout(height=550, template="plotly_dark", plot_bgcolor="#171a21", paper_bgcolor="#171a21")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Sin datos suficientes de P/E y crecimiento de utilidad neta para este filtro.")

    with tab4:
        pe_ev_df, sector_pe, sector_pe_n, sector_ev, sector_ev_n = get_pe_ev_table(sma_window, freq, DATA_VERSION)
        sec_rows = []
        for sector in sorted(filtered.sector.unique()):
            tickers_sec = filtered[filtered.sector == sector]
            sec_rows.append({
                "Sector": sector, "# Empresas": len(tickers_sec),
                "P/E prom.": f"{sector_pe[sector]:.1f}x ({sector_pe_n[sector]} emp.)" if sector in sector_pe else "—",
                "EV/EBITDA prom.": f"{sector_ev[sector]:.1f}x ({sector_ev_n[sector]} emp.)" if sector in sector_ev else "—",
                "Dist. SMA prom.": fmt_pct(tickers_sec["dist_sma_pct"].mean()),
                "Retorno 1a prom.": fmt_pct(tickers_sec["r1y"].mean()),
            })
        st.dataframe(pd.DataFrame(sec_rows), width="stretch", height=520, hide_index=True)

# ---------------------------------------------------------------------------
# VISTA EMPRESA
# ---------------------------------------------------------------------------

else:
    tickers_sorted = sorted(filtered["ticker"].tolist())
    if not tickers_sorted:
        st.warning("No hay empresas con el filtro actual.")
        st.stop()

    # Si el ticker guardado (ej. el que se clickeó en el listado) ya no está en
    # el filtro actual, caemos a un default válido. Se setea ANTES de crear el
    # widget para que Streamlit lo tome sin errores.
    if st.session_state.get("ticker_sel") not in tickers_sorted:
        st.session_state["ticker_sel"] = "NVDA" if "NVDA" in tickers_sorted else tickers_sorted[0]

    ticker = st.sidebar.selectbox("Empresa", tickers_sorted, key="ticker_sel")

    row = summary[summary.ticker == ticker].iloc[0]
    comp_info = info.get(ticker, {})

    if st.button("← Volver al listado general"):
        st.session_state["_goto_general"] = True
        st.rerun()

    st.title(f"{row['name']} ({ticker})")
    st.caption(f"{row['universe']} · {row['sector']} · {row['industry']} · Último dato: {row['last_date']} · "
               f"Historial desde {row['first_date']} ({row['n_rows']} sesiones)")
    st.write(comp_info.get("desc", ""))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Precio", f"{row['close']:.2f}")
    c2.metric(f"SMA{sma_window}", f"{row['sma']:.2f}" if pd.notna(row["sma"]) else "—")
    c3.metric("Dist. SMA", fmt_pct(row["dist_sma_pct"]))
    c4.metric("Retorno 1a", fmt_pct(row["r1y"]))
    c5.metric("Zona", row["zone"])

    # las tres señales, cada una con su valor y su lectura
    s1, s2, s3, s4 = st.columns(4)
    s1.metric(f"RSI {dl.RSI_PERIOD}", f"{row['rsi']:.1f}" if pd.notna(row.get("rsi")) else "—",
              help=f"Sobre {dl.RSI_SOBRECOMPRA} = sobrecompra · bajo {dl.RSI_SOBREVENTA} = sobreventa")
    s2.metric("Señal RSI", row.get("rsi_signal") or "—")
    s3.metric("MACD hist %", f"{row['macd_hist_pct']:+.3f}%" if pd.notna(row.get("macd_hist_pct")) else "—",
              help="Histograma (MACD menos su señal) como % del precio, para poder comparar entre empresas")
    s4.metric("Señal MACD", row.get("macd_signal") or "—",
              help="Pre-cruce = se acerca la golden cross (compra) · Perdiendo fuerza = pierde momentum (venta)")

    # ---- Analisis + recomendacion ----
    margins = dl.compute_margins(ticker)
    reco_label, reco_text = dl.compute_recommendation(row.to_dict(), margins)
    st.subheader("Análisis y recomendación")
    st.markdown(
        f"**Lectura técnica** (las tres señales son independientes entre sí): "
        f"el precio está {fmt_pct(row['dist_sma_pct'])} respecto a su SMA{sma_window}, en zona "
        f"**{row['zone']}** · el RSI {dl.RSI_PERIOD} marca "
        f"{row['rsi']:.1f} → **{row.get('rsi_signal')}**".replace("nan", "—") +
        f" · el MACD está en **{row.get('macd_signal')}**. "
        f"Retornos: 1m {fmt_pct(row['r1m'])}, 3m {fmt_pct(row['r3m'])}, 1a {fmt_pct(row['r1y'])}.")
    badge_color = {"Sesgo positivo": "green", "Sesgo negativo": "red", "Neutral / Mantener": "orange"}.get(reco_label, "gray")
    st.markdown(f":{badge_color}[**{reco_label}**]  \n{reco_text}")
    st.caption("Señal algorítmica combinando técnico (SMA) y fundamental (crecimiento/margen). "
               "No constituye asesoría financiera ni recomendación de inversión.")

    # ---- Grafico tecnico + panel de opciones (Plotly) ----
    st.subheader("Técnico")

    opt_on = st.checkbox("Mostrar opciones (calls/puts y GEX de los 2 vencimientos más próximos)",
                         value=True, key="opt_on",
                         help="Descarga la cadena de opciones desde Yahoo vía yfinance. "
                              "Requiere internet (funciona en tu computador y en Streamlit Cloud).")

    opt_data, opt_error = (None, None)
    if opt_on:
        opt_data, opt_error = get_options(ticker)

    # selector de vencimiento (define qué muros se usan en ambos gráficos)
    exp_choice = None
    if opt_data and opt_data["chains"]:
        oc1, oc3 = st.columns([4, 1])
        exp_labels = [f"{c['exp']} ({c['dte']}d)" for c in opt_data["chains"]]
        exp_choice = oc1.radio("Vencimiento", exp_labels, horizontal=True, key="opt_exp")
        if oc3.button("↻ Actualizar", help="Vuelve a descargar opciones y velas horarias (se cachean 15 min)"):
            get_options.clear()
            get_intraday.clear()
            st.rerun()

    # tipo de gráfico: las velas solo se ofrecen en semanal (en diario, ~1000 velas
    # quedan ilegibles y la línea de cierre se lee mucho mejor)
    chart_type = "Línea"
    if freq == dl.FREQ_WEEKLY:
        chart_type = st.radio("Tipo de gráfico", ["Velas", "Línea"], horizontal=True, key="chart_type")

    df_price = get_price_df(ticker, freq, DATA_VERSION)
    if df_price is not None:
        sma, up, down = dl.compute_sma_bands(df_price, sma_window)
        n_disp = 1000 if freq == dl.FREQ_DAILY else 260
        disp = df_price.tail(n_disp).copy()
        sma_d, up_d, down_d = sma.tail(n_disp), up.tail(n_disp), down.tail(n_disp)

        # precio (fila 1) y volumen (fila 2) en una sola figura, con el eje X
        # compartido: así el volumen queda exactamente del mismo ancho que el precio
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[PRICE_ROW_FRAC, 1 - PRICE_ROW_FRAC], vertical_spacing=0.03)

        # valores actuales, para rotular cada serie en la leyenda con su número
        last_close = float(disp["Close"].iloc[-1])
        sma_now = sma_d.iloc[-1]
        up_now, down_now = up_d.iloc[-1], down_d.iloc[-1]
        banda_lbl = (f"Banda ±1.5σ: {down_now:,.2f} – {up_now:,.2f}"
                     if pd.notna(up_now) and pd.notna(down_now) else "Banda ±1.5σ (sin dato)")
        sma_lbl = (f"SMA{sma_window} ({unidad}): {sma_now:,.2f}"
                   if pd.notna(sma_now) else f"SMA{sma_window} ({unidad}): sin dato")

        fig.add_trace(go.Scatter(x=disp["Date"], y=up_d, line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=disp["Date"], y=down_d, fill="tonexty", fillcolor="rgba(79,140,255,0.12)",
                                 line=dict(width=0), name=banda_lbl), row=1, col=1)
        fig.add_trace(go.Scatter(x=disp["Date"], y=sma_d, line=dict(color="#e6b45e", width=1.5, dash="dash"),
                                 name=sma_lbl), row=1, col=1)

        if chart_type == "Velas":
            fig.add_trace(go.Candlestick(x=disp["Date"], open=disp["Open"], high=disp["High"],
                                         low=disp["Low"], close=disp["Close"],
                                         name=f"Precio · último {last_close:,.2f}",
                                         increasing_line_color="#3ecf8e", decreasing_line_color="#ef5a6f"),
                          row=1, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False)
        else:
            fig.add_trace(go.Scatter(x=disp["Date"], y=disp["Close"], line=dict(color="#e6e8ec", width=1.6),
                                     name=f"Cierre: {last_close:,.2f}"), row=1, col=1)

        vol_colors = ["#3ecf8e" if c >= o else "#ef5a6f" for c, o in zip(disp["Close"], disp["Open"])]
        fig.add_trace(go.Bar(x=disp["Date"], y=disp["Volume"], marker_color=vol_colors,
                             name="Volumen", showlegend=False), row=2, col=1)
        fig.update_yaxes(title_text="Volumen", row=2, col=1)

        chain = None
        if opt_data and opt_data["chains"] and exp_choice:
            idx = [f"{c['exp']} ({c['dte']}d)" for c in opt_data["chains"]].index(exp_choice)
            chain = opt_data["chains"][idx]

        # rango del eje Y compartido entre el precio y el panel de opciones, para
        # que los niveles de strike queden alineados horizontalmente
        y_lo = float(min(disp["Close"].min(), down_d.min() if pd.notna(down_d.min()) else disp["Close"].min()))
        y_hi = float(max(disp["Close"].max(), up_d.max() if pd.notna(up_d.max()) else disp["Close"].max()))
        if chain is not None and not chain["levels"].empty:
            y_lo = min(y_lo, float(chain["levels"]["strike"].min()))
            y_hi = max(y_hi, float(chain["levels"]["strike"].max()))
        pad = (y_hi - y_lo) * 0.04
        y_range = [y_lo - pad, y_hi + pad]

        # Muros de opciones como niveles horizontales. Se dibujan como trazos (no
        # como shapes) para que aparezcan en la leyenda: así queda explícito qué
        # significa cada línea, y el nombre lleva el valor numérico del strike.
        if chain is not None:
            x0, x1 = disp["Date"].iloc[0], disp["Date"].iloc[-1]
            walls = (
                list(zip(chain["call_walls"], ["#3ecf8e", "#6de08c"],
                         ["CW1", "CW2"], ["Resistencia (call wall)", "Resistencia 2"])) +
                list(zip(chain["put_walls"], ["#ef5a6f", "#f0a8b0"],
                         ["PW1", "PW2"], ["Soporte (put wall)", "Soporte 2"]))
            )
            for w, color, tag, meaning in walls:
                dist = (w["strike"] / last_close - 1) * 100
                fig.add_trace(go.Scatter(
                    x=[x0, x1], y=[w["strike"], w["strike"]], mode="lines",
                    line=dict(color=color, width=1.2, dash="dot"),
                    name=f"{tag} · {meaning}: {w['strike']:,.2f} ({fmt_pct(dist)} vs precio) · OI {ol.fmt_qty(w['oi'])}",
                    hovertemplate=f"{tag} — {meaning}<br>Strike: {w['strike']:,.2f}<br>"
                                  f"OI: {ol.fmt_qty(w['oi'])}<br>Dist. al precio: {fmt_pct(dist)}<extra></extra>",
                ), row=1, col=1)
                # etiqueta con el valor pegada a la línea, dentro del gráfico
                fig.add_annotation(x=x1, y=w["strike"], text=f"{tag} {w['strike']:,.2f}",
                                   showarrow=False, xanchor="right", yanchor="bottom",
                                   font=dict(size=10, color=color),
                                   bgcolor="rgba(23,26,33,0.7)", row=1, col=1)

        # línea del último cierre, como referencia para leer los muros
        fig.add_trace(go.Scatter(
            x=[disp["Date"].iloc[0], disp["Date"].iloc[-1]], y=[last_close, last_close],
            mode="lines", line=dict(color="#8b93a3", width=1, dash="dashdot"),
            name=f"Último cierre: {last_close:,.2f}",
            hovertemplate=f"Último cierre: {last_close:,.2f}<extra></extra>",
        ), row=1, col=1)

        # leyenda vertical dentro del gráfico: con los muros son hasta 8 entradas y
        # los nombres son largos (llevan el valor), así que en horizontal no caben
        fig.update_layout(height=CHART_HEIGHT, template="plotly_dark", plot_bgcolor="#171a21",
                          paper_bgcolor="#171a21", margin=dict(t=10, b=10), bargap=0.05,
                          legend=dict(orientation="v", x=0.005, y=0.995,
                                      xanchor="left", yanchor="top",
                                      bgcolor="rgba(15,17,21,0.75)",
                                      bordercolor="#2a2f3a", borderwidth=1,
                                      font=dict(size=10.5)))
        fig.update_yaxes(range=y_range, row=1, col=1)

        st.plotly_chart(fig, width="stretch")

        # ---- RSI y MACD, debajo del precio y compartiendo el mismo eje de tiempo ----
        rsi_serie = dl.compute_rsi(df_price["Close"]).tail(n_disp)
        macd_l, macd_s, macd_h = dl.compute_macd(df_price["Close"])
        macd_l, macd_s, macd_h = macd_l.tail(n_disp), macd_s.tail(n_disp), macd_h.tail(n_disp)

        fig_ind = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.45, 0.55], vertical_spacing=0.08,
                                subplot_titles=(f"RSI {dl.RSI_PERIOD}",
                                                f"MACD {dl.MACD_FAST}/{dl.MACD_SLOW}/{dl.MACD_SIGNAL}"))

        fig_ind.add_trace(go.Scatter(x=disp["Date"], y=rsi_serie, line=dict(color="#b98af0", width=1.3),
                                     name=f"RSI {dl.RSI_PERIOD}"), row=1, col=1)
        fig_ind.add_hline(y=dl.RSI_SOBRECOMPRA, line=dict(color="#ef5a6f", width=1, dash="dot"),
                          annotation_text=f"Sobrecompra {dl.RSI_SOBRECOMPRA}",
                          annotation_font=dict(size=9, color="#ef5a6f"), row=1, col=1)
        fig_ind.add_hline(y=dl.RSI_SOBREVENTA, line=dict(color="#3ecf8e", width=1, dash="dot"),
                          annotation_text=f"Sobreventa {dl.RSI_SOBREVENTA}",
                          annotation_font=dict(size=9, color="#3ecf8e"), row=1, col=1)
        fig_ind.update_yaxes(range=[0, 100], row=1, col=1)

        hist_colors = ["#3ecf8e" if h >= 0 else "#ef5a6f" for h in macd_h]
        fig_ind.add_trace(go.Bar(x=disp["Date"], y=macd_h, marker_color=hist_colors,
                                 name="Histograma"), row=2, col=1)
        fig_ind.add_trace(go.Scatter(x=disp["Date"], y=macd_l, line=dict(color="#e6e8ec", width=1.2),
                                     name="MACD"), row=2, col=1)
        fig_ind.add_trace(go.Scatter(x=disp["Date"], y=macd_s, line=dict(color="#e6b45e", width=1.2, dash="dash"),
                                     name="Señal"), row=2, col=1)
        fig_ind.add_hline(y=0, line=dict(color="#2a2f3a", width=1), row=2, col=1)

        fig_ind.update_layout(height=380, template="plotly_dark", plot_bgcolor="#171a21",
                              paper_bgcolor="#171a21", margin=dict(t=30, b=10), bargap=0.05,
                              legend=dict(orientation="h", y=-0.12), showlegend=True)
        st.plotly_chart(fig_ind, width="stretch")

        # referencia escrita de cada línea (además de la leyenda del gráfico)
        ref = [
            f"**Cierre** (blanco): precio de cada {'sesión' if freq == dl.FREQ_DAILY else 'semana'}. "
            f"Último: **{last_close:,.2f}**.",
            f"**SMA{sma_window}** (amarillo punteado): promedio móvil de los últimos {sma_window} "
            f"{unidad}. Valor actual: **{f'{sma_now:,.2f}' if pd.notna(sma_now) else 'sin dato'}**.",
            f"**Banda ±1.5σ** (azul sombreado): la SMA más/menos 1.5 desviaciones estándar del cierre. "
            f"Rango actual: **{f'{down_now:,.2f} – {up_now:,.2f}' if pd.notna(up_now) else 'sin dato'}**.",
            f"**Último cierre** (gris rayado): línea horizontal de referencia en **{last_close:,.2f}**.",
        ]
        if chain is not None:
            for w, _c, tag, meaning in walls:
                dist = (w["strike"] / last_close - 1) * 100
                ref.append(f"**{tag}** ({'verde' if tag.startswith('CW') else 'rojo'} punteado): "
                           f"{meaning.lower()} en **{w['strike']:,.2f}** "
                           f"({fmt_pct(dist)} respecto al precio), con {ol.fmt_qty(w['oi'])} de Open Interest.")
        with st.expander("¿Qué significa cada línea del gráfico?", expanded=False):
            for line in ref:
                st.markdown(f"- {line}")
            if chain is not None:
                st.caption(f"Los muros corresponden al vencimiento {chain['exp']} ({chain['dte']} días). "
                           "Son los 2 strikes con mayor Open Interest por lado: suelen actuar como "
                           "zonas de soporte (puts) y resistencia (calls).")
    else:
        st.info("Sin historial de precios disponible.")

    # ---- Detalle de opciones: GEX, gamma flip y tabla de muros ----
    if opt_on:
        if opt_error:
            st.info(f"No se pudo cargar la cadena de opciones de {ticker}: {opt_error}")
        elif opt_data and opt_data["chains"] and exp_choice:
            idx = [f"{c['exp']} ({c['dte']}d)" for c in opt_data["chains"]].index(exp_choice)
            chain = opt_data["chains"][idx]

            # ---- Última semana vs muros, hasta el vencimiento ----
            st.subheader(f"Última semana vs muros (hasta el vencimiento {chain['exp']})")
            bars, bars_err = get_intraday(ticker)
            estados = {}
            if bars_err or bars is None or bars.empty:
                st.info(f"No se pudieron cargar las velas horarias de {ticker}: {bars_err or 'sin datos'}")
            else:
                estados = {tag: ol.classify_wall(bars, w["strike"]) for tag, w in chain_walls(chain)}
                st.plotly_chart(build_week_walls_chart(bars, chain, estados), width="stretch")
                with st.expander("¿Cómo se clasifica cada muro?", expanded=False):
                    z = ol.WALL_ZONE_PCT
                    st.markdown(
                        f"Se usan las velas de 1 hora de los últimos 5 días hábiles. La franja sombreada "
                        f"de cada muro es su **zona de contacto** (±{z:g}% del strike).\n\n"
                        f"- **Rompió ↑/↓**: la semana empezó de un lado del strike y hoy cierra del otro.\n"
                        f"- **Probando**: tocó la zona y el precio sigue dentro de ella (la pelea está en curso).\n"
                        f"- **Rebotando**: tocó la zona (incluso perforándola con mecha) y ya se alejó al "
                        f"menos {z/2:g}% del punto más cercano: el muro funcionó.\n"
                        f"- **Acercándose**: no lo ha tocado, está a menos de {z*ol.APPROACH_ZONE_MULT:g}% y "
                        f"la distancia se redujo respecto a hace ~1 sesión.\n"
                        f"- **Lejos**: ninguna de las anteriores.")
                    st.caption("Limitación: los muros son la foto del Open Interest de HOY. Yahoo no entrega "
                               "OI histórico, así que no sabemos si el muro ya estaba en ese strike al "
                               "principio de la semana.")

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Spot (opciones)", f"{opt_data['spot']:.2f}")
            k2.metric("Vol. prom. 5d", ol.fmt_qty(opt_data["avg_vol_5d"]))
            k3.metric("GEX neto", ol.fmt_gex(chain["total_gex"]),
                      help="Gamma Exposure agregado, en USD por cada 1% de movimiento. "
                           "Positivo = dealers amortiguan el movimiento; negativo = lo amplifican.")
            flip = chain["gamma_flip"]
            k4.metric("Gamma flip", f"{flip:.2f}" if flip else "—",
                      help="Strike donde el GEX acumulado cambia de signo.")

            walls_rows = []
            wall_labels = {"CW2": "CW2 (resist. 2)", "CW1": "CW1 (resist. 1)",
                           "PW1": "PW1 (soporte 1)", "PW2": "PW2 (soporte 2)"}
            for tag, w in chain_walls(chain):
                est = estados.get(tag, {})
                walls_rows.append({
                    "Muro": wall_labels[tag],
                    "Strike": f"{w['strike']:g}",
                    "Comportamiento": est.get("estado", "—"),
                    "Detalle (última semana)": est.get("detalle", ""),
                    "vs Spot": fmt_pct((w["strike"] / opt_data["spot"] - 1) * 100),
                    "OI": ol.fmt_qty(w["oi"]),
                    "Volumen": ol.fmt_qty(w["volume"]),
                    "IV": f"{w['iv']*100:.1f}%",
                    "Δ": f"{w['delta']:.2f}",
                    "Cobertura": ol.fmt_qty(w["hedge_shares"]),
                    "GEX": ol.fmt_gex(w["gex"]),
                })
            if walls_rows:
                wdf = pd.DataFrame(walls_rows)
                try:
                    wdf = wdf.style.map(lambda v: f"color: {ESTADO_COLOR.get(v, '#e6e8ec')}; font-weight: 600",
                                        subset=["Comportamiento"])
                except Exception:
                    pass  # sin jinja2 (o pandas antiguo) se muestra sin color
                st.dataframe(wdf, width="stretch", hide_index=True)
                st.caption("Muros = los 2 strikes con mayor Open Interest por lado, dentro de ±25% del spot. "
                           "Cobertura = acciones nocionales delta-hedged por los market makers (OI × 100 × |Δ|). "
                           "Δ y Γ se calculan con Black-Scholes (r=4.5%) sobre la volatilidad implícita, porque "
                           "Yahoo no entrega griegas. El GEX asume la convención estándar: dealers largos en "
                           "calls y cortos en puts.")
        elif opt_data:
            st.info(f"{ticker} no tiene cadena de opciones disponible.")

    # ---- Fundamental ----
    st.subheader("Fundamental")
    peInfo = dl.compute_pe(ticker, row["close"])
    evInfo = dl.compute_ev_ebitda(ticker, row["close"])
    pe_ev_df, sector_pe, sector_pe_n, sector_ev, sector_ev_n = get_pe_ev_table(sma_window, freq, DATA_VERSION)
    sector = row["sector"]

    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("P/E Ratio", ("N/A (pérdidas)" if peInfo and peInfo["negative"] else (f"{peInfo['pe']:.1f}x" if peInfo else "—")))
    fc2.metric(f"P/E prom. {sector}", f"{sector_pe[sector]:.1f}x" if sector in sector_pe else "—")
    fc3.metric("EV/EBITDA", ("N/A (EBITDA neg.)" if evInfo and evInfo["negative"] else (f"{evInfo['multiple']:.1f}x" if evInfo else "—")))
    fc4.metric(f"EV/EBITDA prom. {sector}", f"{sector_ev[sector]:.1f}x" if sector in sector_ev else "—")

    if margins:
        fc5, fc6, fc7, fc8 = st.columns(4)
        fc5.metric("Marg. bruto", f"{margins['gross_margin']:.1f}%" if margins["gross_margin"] is not None else "—")
        fc6.metric("Marg. operacional", f"{margins['op_margin']:.1f}%" if margins["op_margin"] is not None else "—")
        fc7.metric("Marg. neto", f"{margins['net_margin']:.1f}%" if margins["net_margin"] is not None else "—")
        fc8.metric("Crec. ingresos YoY", fmt_pct(margins["revenue_yoy"]))

    dfa = get_fund_annual(ticker)
    dfq = get_fund_quarterly(ticker)

    fig_fund = go.Figure()
    if dfa is not None and not dfa.empty:
        labels_a = ["FY" + str(d)[:4] for d in dfa["Date"]]
        fig_fund.add_trace(go.Bar(x=[l + " (anual)" for l in labels_a], y=dfa["TotalRevenue"] / 1e9, name="Ingresos", marker_color="#4f8cff"))
        fig_fund.add_trace(go.Bar(x=[l + " (anual)" for l in labels_a], y=dfa["NetIncome"] / 1e9, name="Ut. neta", marker_color="#3ecf8e"))
    fig_fund.update_layout(height=320, template="plotly_dark", plot_bgcolor="#171a21", paper_bgcolor="#171a21",
                            barmode="group", yaxis_title="USD B", margin=dict(t=10, b=10))
    st.plotly_chart(fig_fund, width="stretch")

    # Tablas traspuestas: los periodos (años fiscales / trimestres) van en las
    # columnas y las métricas en las filas. Se muestran una debajo de la otra
    # (no lado a lado) porque al trasponer se vuelven más anchas.
    st.markdown("**Anual**")
    tbl_a, yoy_cols = build_fund_table_t(dfa, is_annual=True)
    if tbl_a is not None:
        st.dataframe(style_yoy(tbl_a, yoy_cols), width="stretch")
        st.caption("Las columnas **YoY** muestran la variación porcentual de cada métrica "
                   "respecto al año fiscal anterior.")
    else:
        st.caption("Sin datos anuales.")

    st.markdown("**Trimestral**")
    tbl_q, _ = build_fund_table_t(dfq, is_annual=False)
    if tbl_q is not None:
        st.dataframe(tbl_q, width="stretch")
    else:
        st.caption("Sin datos trimestrales.")

    st.caption("Sector/industria/descripción provienen de clasificación curada (Megacap) o del screener (Large Cap, automática). "
               "Datos generados de forma estática — para refrescar, corre el script de actualización local y sube los datos al repo.")
