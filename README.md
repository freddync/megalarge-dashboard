# Dashboard Integrado — Megacap + Large Cap

Dashboard técnico + fundamental de 894 empresas (81 Megacap >$200B + 813 Large Cap $10B-$200B),
con SMA 100 + banda ±1.5σ, RSI 14 y MACD, construido en Streamlit.

## Indicadores y señales

El dashboard usa **tres indicadores técnicos independientes**. Cada uno aporta su valor
numérico y su etiqueta, y **cada columna se puede ordenar por separado** en la tabla general:

| Indicador | Columnas | Señal |
|---|---|---|
| **SMA 100** con banda ±1.5σ | `Dist. SMA %` y `Zona` | Sobrevendido / Bajista / Alcista / Sobrecomprado |
| **RSI 14** (límites 70/30) | `RSI 14` y `Señal RSI` | Sobreventa / Neutral / Sobrecompra |
| **MACD 12/26/9** | `MACD hist %` y `Señal MACD` | Bajista / Perdiendo fuerza / Pre-cruce / Alcista |

Notas de criterio:

- El **RSI** es el estándar de Wilder: 14 periodos con límites 70/30.
- El RSI se calcula con el suavizado de Wilder **inicializado con media simple** (validado
  contra el ejemplo canónico del libro de Wilder: 70.46 vs 70.53 publicado).
- Los cuatro estados del **MACD** salen del signo del histograma y de su pendiente:
  **Pre-cruce** (negativo pero subiendo) es la señal de compra anticipada, antes de la golden
  cross; **Perdiendo fuerza** (positivo pero cayendo) es la señal de venta. Al ordenar la
  columna van de más bajista a más alcista.
- El histograma se muestra **como % del precio**, para poder comparar empresas de muy
  distinto valor nominal.
- Las señales son deliberadamente **independientes**: una empresa puede estar Sobrecomprada
  por SMA y Neutral por RSI. No se combinan en un puntaje único.

## Listado "Sobrevendido + Pre-cruce"

Pestaña aparte en la vista General con las empresas que cumplen **a la vez**: precio bajo
la banda inferior de la SMA 100 (Zona = Sobrevendido) y MACD en Pre-cruce. Respeta los
filtros del panel izquierdo (universo, sector) y sus filas abren la empresa igual que la
tabla principal.

## Frecuencia: diaria o semanal

## Probarlo en tu computador (opcional, antes de publicarlo)

1. Necesitas Python instalado (el mismo que ya usas para los .bat de Fintual).
2. Doble click en `Ejecutar_Local.bat`. Se abrirá en tu navegador en `http://localhost:8501`.
3. Para cerrarlo, cierra la ventana negra (consola) que se abrió.

Esto **no** lo publica en internet, solo corre en tu computador.

## Publicarlo online con Streamlit Community Cloud (gratis)

Streamlit Cloud lee el código y los datos desde un repositorio de GitHub, así que primero
necesitas subir esta carpeta a GitHub. Son cuentas tuyas — yo no puedo crearlas por ti,
pero aquí tienes cada paso.

### Paso 1: Crear una cuenta de GitHub (si no tienes una)

1. Ve a [github.com](https://github.com) y crea una cuenta gratis.

### Paso 2: Crear el repositorio

1. En GitHub, click en el botón verde **"New"** (o el ícono `+` arriba a la derecha → "New repository").
2. Nómbralo, por ejemplo, `fintual-dashboard`.
3. Puedes dejarlo **Público** (necesario para el plan gratis de Streamlit Cloud) o **Privado**
   (Streamlit Cloud también soporta repos privados si conectas tu cuenta de GitHub).
4. NO marques "Add a README" (ya tenemos uno). Click **Create repository**.

### Paso 3: Subir esta carpeta al repositorio

Necesitas tener [Git instalado](https://git-scm.com/downloads) en tu computador. Luego, abre
una consola (cmd o PowerShell) **dentro de esta carpeta** (`Fintual/DashboardIntegrado`) y corre:

```
git init
git add -A
git commit -m "version inicial del dashboard"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/fintual-dashboard.git
git push -u origin main
```

(Reemplaza `TU-USUARIO` y el nombre del repo por los tuyos — GitHub te muestra estos
comandos exactos en la página del repo recién creado, en la sección "…or push an existing
repository from the command line").

### Paso 4: Conectar Streamlit Community Cloud

1. Ve a [share.streamlit.io](https://share.streamlit.io) y entra con tu cuenta de GitHub
   (botón "Sign in" / "Continue with GitHub").
2. Click en **"New app"**.
3. Elige tu repositorio (`fintual-dashboard`), la rama `main`, y como "Main file path"
   escribe `app.py`.
4. Click **Deploy**. La primera vez tarda unos minutos en instalar las dependencias.
5. Cuando termine, te da un link público (algo como `https://tu-usuario-fintual-dashboard.streamlit.app`)
   — ese es el que puedes abrir desde cualquier dispositivo o compartir.

### Actualización automática de precios (GitHub Actions)

Los precios se actualizan **solos**, sin necesidad de encender el computador. La Action
`.github/workflows/actualizar-precios.yml` corre **cada hora, de lunes a viernes, entre las
9:00 y las 20:00 hora de Nueva York** (12 corridas por día hábil). De noche y los fines de
semana no hace nada.

Baja los precios de las 894 empresas desde Yahoo, reescribe `data/precios/` y
`data/precios_semanal/`, y hace commit. Streamlit Cloud detecta el push y redeploya solo.

Durante la sesión (9:30-16:00 NY) la última barra es **parcial**: su "cierre" es el precio
del momento y el volumen está incompleto. El dashboard lo marca explícitamente. Después del
cierre la barra queda consolidada y las corridas siguientes ya no la modifican — por eso
esas corridas terminan sin hacer commit, que es lo esperado.

Dos notas técnicas sobre el cron, ambas aprendidas a golpes:

1. El cron de GitHub solo entiende UTC y no ajusta por horario de verano. Por eso se dispara
   cada hora en el rango UTC que puede caer en la ventana, y el primer paso del workflow
   decide según la hora **local de Nueva York**. Así el cambio EDT/EST se ajusta solo.
2. El filtro es por **ventana horaria, no por una hora exacta**. GitHub atrasa los cron
   cuando tiene carga (llegamos a ver atrasos de 4 horas), y un filtro de igualdad
   descartaba las corridas por completo: el workflow aparecía en verde durando 8 segundos
   y los datos nunca se actualizaban.

- **Lanzarla a mano**: pestaña *Actions* del repo → "Actualizar precios" → *Run workflow*.
- **Si un ticker falla**, se conserva su CSV anterior (nunca se borra ni se deja a medias).
- **Si falla más del 20% de los tickers**, la Action queda en rojo y GitHub te avisa por
  correo, en vez de dejar datos viejos en silencio.
- Es gratis e ilimitado porque el repositorio es público.

Los **fundamentales no** se actualizan por esta vía (cambian cada trimestre): para esos
sigue el flujo manual de abajo.

### Actualizar los fundamentales (a mano, cada trimestre)

1. `Fintual/MegaCap/Actualizar_Financieros.bat` (81 Megacap).
2. `Fintual/LargeCap/Actualizar_Financieros_LargeCap.bat` (813 Large Cap, 30-40 min).
3. `Actualizar_Datos_Dashboard.bat` en esta carpeta: copia los fundamentales a `/data`,
   hace commit y push. Streamlit Cloud se actualiza solo en 1-2 minutos.

Los **precios no se tocan** en este flujo (los actualiza la Action cada hora y son más
frescos que las copias locales). Si alguna vez necesitas reconstruirlos desde las
carpetas locales: `python update_data.py --todo`.

## Opciones (calls/puts y GEX)

El gráfico de precio principal ya no muestra muros; en cambio permite **dibujar líneas de
tendencia** (botones de línea, trazo libre, rectángulo y borrar en la barra del gráfico).
Las líneas no se guardan: se pierden al cambiar de empresa o recargar.

Los muros (PW2/PW1/CW1/CW2 = los 2 strikes con mayor OI por lado) viven en la sección
"Última semana vs muros de opciones", con su propio selector entre los **2 vencimientos
más próximos**:

- **Perfil de volumen** a la derecha del gráfico: acciones transadas por nivel de precio
  durante la semana (el volumen de cada vela se reparte entre su mínimo y su máximo), con
  las barras dentro de la zona de un muro pintadas de su color y el POC marcado.
- En la tabla de muros: **% vol. semana en zona** (qué parte del volumen de la semana se
  transó en la zona del muro) y **Contratos hoy / OI** (rotación del muro hoy). Yahoo no
  entrega OI histórico, así que no se puede medir directamente cuántos contratos se cerraron.

- **Gráfico "Última semana vs muros"**: velas de **1 hora** de los últimos 5 días hábiles,
  con cada muro y su zona de contacto (±1.5% del strike) extendidos **hasta el cierre del
  día de vencimiento**. El espacio en blanco a la derecha son las horas de mercado que
  quedan (se saltan noches y fines de semana).
- **Comportamiento de cada muro** (columna en la tabla y etiqueta en el gráfico):
  - *Rompió ↑/↓*: la semana empezó de un lado del strike y hoy cierra del otro.
  - *Probando*: tocó la zona y sigue dentro de ella.
  - *Rebotando*: tocó la zona (incluso perforando con mecha) y ya se alejó ≥0.75%.
  - *Acercándose*: sin tocarla, a menos de 6% y con la distancia achicándose en la
    última sesión.
  - *Lejos*: ninguna de las anteriores.
- Limitación: los muros son la foto del Open Interest de hoy (Yahoo no entrega OI
  histórico), así que no se sabe si el muro ya estaba ahí al inicio de la semana.

### Historial de Open Interest (solo Megacap)

La Action `.github/workflows/foto-open-interest.yml` toma **una foto al día, después del
cierre** (~16:30-19:30 NY), del OI y del volumen de contratos de las 81 Megacap
(`scripts/snapshot_oi.py` → `data/oi_hist/{TICKER}.csv`): vencimientos de las próximas
2 semanas (mínimo los 2 más próximos), strikes a ±15% del precio, últimos 30 días. Si la foto del día ya existe
(feriado o corrida repetida) se omite. Para tomarla a mano: `Foto_OI_Local.bat`, o en
GitHub → Actions → "Foto diaria de Open Interest" → *Run workflow*.

Con eso, la tabla de muros muestra **Δ OI sem.** (OI actual vs la primera foto de los
últimos 7 días) y **Contratos sem.**, más un gráfico de la evolución del OI de cada muro.
Si el OI de un muro baja mientras se transan contratos, se están cerrando posiciones y el
muro se debilita. El historial parte desde la primera foto (Yahoo no entrega OI pasado).

- Los strikes se filtran a ±25% del spot, igual que en el script de Colab.
- Δ y Γ se calculan con Black-Scholes (r = 4.5%) sobre la volatilidad implícita, porque
  Yahoo no entrega griegas.
- Cobertura = OI × 100 × |Δ| (acciones nocionales delta-hedged por los market makers).
- GEX = Γ × OI × 100 × Spot² × 0.01, en USD por cada 1% de movimiento. Asume la convención
  estándar de que los dealers están largos en calls y cortos en puts.

**Esta sección sí necesita internet en vivo** (es la única del dashboard que no usa datos
bundleados): descarga la cadena con `yfinance` y las velas horarias desde la API de gráficos
de Yahoo, y cachea ambas 15 minutos (botón "↻ Actualizar" para forzar). Si no hay conexión
o la empresa no tiene opciones listadas, el resto de la página funciona igual y solo se
muestra un aviso. Se puede apagar con el checkbox "Mostrar opciones".

## Estructura

```
app.py                  -- la app de Streamlit
data_layer.py           -- funciones de carga/cálculo (SMA, P/E, EV/EBITDA, etc.)
options_layer.py        -- cadenas de opciones, Black-Scholes, GEX y muros
update_data.py          -- reconstruye /data desde MegaCap/ y LargeCap/
Actualizar_Datos_Dashboard.bat  -- corre update_data.py
Ejecutar_Local.bat       -- prueba la app en tu computador antes de publicarla
requirements.txt        -- dependencias (Streamlit instala esto automáticamente)
data/
  company_info.json     -- nombre/sector/industria/descripción por ticker
  precios/*.csv         -- ~1250 sesiones diarias por ticker (suficiente para SMA200 diaria)
  precios_semanal/*.csv -- hasta 600 semanas (~11 años) por ticker, para la SMA200 semanal
  fundamentales_variacion/*.csv  -- estados financieros anuales/trimestrales + variaciones
```

## Notas

- Precios y fundamentales no hacen llamadas a internet en tiempo real: viven en `/data`
  dentro del repo. Esto hace que la app cargue rápido y no dependa de límites de tasa de
  Yahoo Finance. La única excepción es el panel de opciones, que sí descarga en vivo
  (ver la sección "Opciones" más arriba).
- Sector/industria/descripción de las empresas Megacap fueron curadas a mano; las de
  Large Cap vienen automáticas del screener (puede haber alguna clasificación imprecisa).
- El análisis y la recomendación que muestra la app son señales algorítmicas automáticas,
  no asesoría financiera.
