# Dashboard Integrado — Megacap + Large Cap

Dashboard técnico + fundamental de 894 empresas (81 Megacap >$200B + 813 Large Cap $10B-$200B),
con SMA 100 + banda ±1.5σ, RSI 5 y MACD, construido en Streamlit.

## Indicadores y señales

El dashboard usa **tres indicadores técnicos independientes**. Cada uno aporta su valor
numérico y su etiqueta, y **cada columna se puede ordenar por separado** en la tabla general:

| Indicador | Columnas | Señal |
|---|---|---|
| **SMA 100** con banda ±1.5σ | `Dist. SMA %` y `Zona` | Sobrevendido / Bajista / Alcista / Sobrecomprado |
| **RSI 5** (límites 80/20) | `RSI 5` y `Señal RSI` | Sobreventa / Neutral / Sobrecompra |
| **MACD 12/26/9** | `MACD hist %` y `Señal MACD` | Bajista / Perdiendo fuerza / Pre-cruce / Alcista |

Notas de criterio:

- El **RSI de 5 periodos** usa 80/20 en vez del clásico 70/30: con periodo tan corto el
  indicador cruza 70/30 casi a diario y la señal pierde valor.
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

### Actualizar los datos a mano (fundamentales, o si prefieres control total)

Streamlit Cloud redeploya automáticamente cada vez que detecta un push nuevo a la rama
conectada. El flujo para refrescar precios/fundamentales es:

1. Corre los `.bat` de actualización de `Fintual/MegaCap/` y `Fintual/LargeCap/` como siempre
   (para que esas carpetas tengan los datos más recientes).
2. Corre `Actualizar_Datos_Dashboard.bat` en esta carpeta (reconstruye `/data` con lo último).
3. En la consola, dentro de esta carpeta:
   ```
   git add -A
   git commit -m "actualizar datos"
   git push
   ```
4. En 1-2 minutos Streamlit Cloud detecta el push y redeploya solo, sin que tengas que hacer nada más ahí.

## Opciones (calls/puts y GEX)

En la vista de cada empresa, al lado del gráfico de precio, se muestra el Open Interest,
el volumen y el GEX por nivel de strike para los **2 vencimientos más próximos**, más una
tabla con los "muros" (PW2/PW1/CW1/CW2 = los 2 strikes con mayor OI por lado).

- Los strikes se filtran a ±25% del spot, igual que en el script de Colab.
- Δ y Γ se calculan con Black-Scholes (r = 4.5%) sobre la volatilidad implícita, porque
  Yahoo no entrega griegas.
- Cobertura = OI × 100 × |Δ| (acciones nocionales delta-hedged por los market makers).
- GEX = Γ × OI × 100 × Spot² × 0.01, en USD por cada 1% de movimiento. Asume la convención
  estándar de que los dealers están largos en calls y cortos en puts.

**Esta sección sí necesita internet en vivo** (es la única del dashboard que no usa datos
bundleados): descarga la cadena con `yfinance` y la cachea 15 minutos. Si no hay conexión
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
