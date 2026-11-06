import hashlib
import io
import re
import textwrap

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
import streamlit as st

import engine  # Motor de backend (usa parsers.py para leer los ficheros)

st.set_page_config(
    page_title="ATFCM Sector & Configuration Analyzer",
    page_icon="✈️",
    layout="wide",
)

for _k, _v in {"uploaded_cos": [], "uploaded_spc": [], "uploaded_cfg": [],
               "audit_result": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

TURNOS = ["Mañana", "Tarde", "Noche"]
# Funciones del motor que esta versión de la app necesita
ENGINE_REQUIRED = ["sector_usage_table", "explode_sectors", "usage_table", "sector_config_usage",
                   "configs_used", "cs_options_for_acc", "minimal_partitions", "rank_partitions"]


# ---------------------------------------------------------------------------
# Carga centralizada (una sola lectura de los ficheros por cambio de entrada)
# ---------------------------------------------------------------------------
def _items(files):
    """Convierte los ficheros subidos en tuplas (nombre, bytes) hashables."""
    return tuple((getattr(f, "name", f"archivo_{i}"), f.getvalue()) for i, f in enumerate(files or []))


@st.cache_data(show_spinner=False)
def cargar_datos(cos_items, spc_items, cfg_items):
    df_cos = engine.load_cos(list(cos_items))
    cfg_map = engine.load_cfg(list(cfg_items))
    _, es_map = engine.load_spc(list(spc_items))
    return df_cos, cfg_map, es_map


def firma(*grupos):
    h = hashlib.md5()
    for items in grupos:
        for name, data in items:
            h.update(name.encode("utf-8", "ignore"))
            h.update(data)
    return h.hexdigest()


def obtener_numero_sectores_nominal(cnf_nombre):
    m = re.search(r"CNF(\d+)", str(cnf_nombre).upper())
    return int(m.group(1)) if m else 1


def sectores_de(cnf, cnf_map):
    return cnf_map.get(str(cnf).upper().strip(), frozenset())


def guia(texto):
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown(textwrap.dedent(texto))
    st.markdown("---")


# ---------------------------------------------------------------------------
# Pestaña 1 - Carga
# ---------------------------------------------------------------------------
def render_tab1():
    st.header("1. Carga de Archivos de Entrada (.COS, .SPC, .CFG)")
    guia("""
    **Qué es.** El punto de entrada de la sesión: aquí se cargan los tres ficheros de NEST que usan todas las demás pestañas.

    **Ficheros esperados** (separador `;`, codificación latin-1):

    | Fichero | Contenido | Ejemplo de línea |
    |---|---|---|
    | `.COS` | Esquema de apertura: qué configuración abre cada ACC en cada tramo horario | `11/06/2026;LECMCTAS;04:45;05:05;CNF3C;E` |
    | `.SPC` | Sectores colapsados (`A`) y sus componentes (`S`); un componente puede ser otro bloque | `A;LECBG12;...` y debajo `S;LECBG1` |
    | `.CFG` | Sectores que abre cada configuración de cada ACC | `LECBCTAW;CNF4CW;LECBG23` |

    **Cómo se usa.**
    * Puedes cargar varios ficheros de cada tipo (por ejemplo, varios ciclos de `.COS`); se combinan.
    * Las líneas vacías o que empiezan por `#` o `;` se ignoran, igual que las cabeceras y las líneas sin horas válidas.
    * Un tramo con hora de fin menor o igual que la de inicio se interpreta como cruce de medianoche (`23:30–01:15` = 105 min).
    * Quitar un fichero del cargador lo elimina también del análisis. Si cambias los ficheros después de ejecutar un desdoblamiento, el resultado anterior se descarta para no mezclar datos.
    """)

    col_cos, col_spc, col_cfg = st.columns(3)
    specs = [
        (col_cos, "📄 Archivos .COS", "Esquemas de Apertura (.COS):", ["cos", "txt"], "uploaded_cos", "uploader_cos"),
        (col_spc, "🧩 Archivos .SPC", "Definición de Sectores (.SPC):", ["spc", "txt"], "uploaded_spc", "uploader_spc"),
        (col_cfg, "⚙️ Archivos .CFG", "Definición de Configuraciones (.CFG):", ["cfg", "txt"], "uploaded_cfg", "uploader_cfg"),
    ]
    for col, titulo, label, tipos, estado, key in specs:
        with col:
            st.subheader(titulo)
            files = st.file_uploader(label, type=tipos, accept_multiple_files=True, key=key)
            st.session_state[estado] = list(files or [])
            if files:
                st.success(f"Cargados: {len(files)} {titulo.split()[-1]}")


# ---------------------------------------------------------------------------
# Pestaña 2 - Dashboard
# ---------------------------------------------------------------------------
def render_tab2(d):
    st.header("2. Dashboard de Exploración y Análisis del ACC")
    guia("""
    **Qué es.** Exploración del comportamiento real de un ACC en el ciclo: cuántos sectores abre, cuándo desdobla o colapsa y qué sectores usa.

    **Datos necesarios.** `.COS` y `.CFG`. Con el `.SPC` se distingue además entre sectores colapsados (CS) y elementales (ES). Sin `.CFG`, el número de sectores se estima a partir del nombre de la configuración (`CNF7…` → 7).

    **Filtros comunes.**
    * **ACC**: el centro a analizar. Las configuraciones se buscan solo en el catálogo de ese ACC.
    * **Fecha**: un día concreto o todos los días agregados.
    * **Turno**: Mañana (07–15 h), Tarde (15–22 h) o Noche (22–07 h), según la hora de inicio del tramo.
    * **Tipo de sector**: cuenta todos los sectores, solo los CS o solo los ES (solo afecta a 2.1).

    **Enfoques.**
    * **2.1 Análisis global**: curva de sectores abiertos a lo largo del día (media por hora si eliges todos los días), mínimo, máximo y media en sala **ponderada por duración**, y minutos por configuración y turno.
    * **2.2 Dinámica de desdobles y colapsos**: cada cambio de configuración, con cuántos sectores se ganan o pierden y cuáles. La secuencia se calcula día a día, así que el primer tramo de un día no se compara con el último del anterior.
    * **2.3 Gantt**: qué sectores están abiertos en cada momento. El color indica la **carga de la sala** (sectores abiertos en esa configuración), no la carga del propio sector. Para leer horas concretas, filtra un solo día.
    * **2.4 Asistente predictivo**: a partir del histórico completo del ACC, probabilidad de que a una hora dada (±15 min) haya desdoble, colapso o estabilidad. Si eliges una fecha, solo usa los días de la misma semana (por ejemplo, todos los jueves).
    """)

    df_cos, cfg_map, es_map = d["df_cos"], d["cfg_map"], d["es_map"]
    if df_cos.empty:
        st.warning("⚠️ Carga los archivos .COS en la Pestaña 1 para habilitar la exploración.")
        return

    sub_tab = st.radio(
        "Selecciona el enfoque de análisis:",
        options=["📊 2.1 Análisis Global del ACC",
                 "🔄 2.2 Dinámica de Sectores Colapsados / Desdoblados",
                 "🗺️ 2.3 Gantt de Sectores Activos",
                 "🔮 2.4 Asistente Predictivo de Capacidad"],
        horizontal=True, key="sub_tab_selector",
    )
    st.markdown("---")
    st.markdown("### 🔍 Filtros de Selección de Escenario")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        acc_sel = st.selectbox("Seleccionar Centro ACC:", options=sorted(df_cos["ACC"].unique()), key="global_acc_sel")
    df_acc = df_cos[df_cos["ACC"] == acc_sel].copy()
    with f2:
        fecha_sel = st.selectbox("Seleccionar Fecha del Plan:",
                                 options=["TODOS LOS DÍAS (Agregado)"] + sorted(df_acc["Fecha"].unique()),
                                 key="global_fecha_sel")
    with f3:
        turno_sel = st.selectbox("Filtrar por Turno:", options=["TODOS"] + TURNOS, key="global_turno_sel")
    with f4:
        tipo_sector_sel = st.selectbox(
            "Filtrar Tipo de Sector:",
            options=["TODOS (CS y ES)", "Solo Sectores Integrados (CS)", "Solo Sectores Elementales (ES)"],
            key="global_tipo_sector_sel")

    cnf_map, exacto = engine.cnf_map_for_acc(cfg_map, acc_sel)
    if not cfg_map:
        st.info("ℹ️ Sin .CFG cargado: el número de sectores se estima a partir del nombre de la configuración.")
    elif not exacto:
        st.warning(f"⚠️ El ACC {acc_sel} no aparece en el .CFG; se usa el catálogo combinado por nombre de configuración.")

    def n_sectores(cnf):
        secs = sectores_de(cnf, cnf_map)
        return len(secs) if secs else obtener_numero_sectores_nominal(cnf)

    df_acc["Sectores_Activos"] = df_acc["Configuracion"].apply(n_sectores)
    df_fecha = df_acc if fecha_sel.startswith("TODOS") else df_acc[df_acc["Fecha"] == fecha_sel]
    df_filtered = df_fecha if turno_sel == "TODOS" else df_fecha[df_fecha["Turno"] == turno_sel]

    if df_filtered.empty:
        st.info("No hay registros para la combinación de filtros seleccionada.")
        return

    if "2.1" in sub_tab:
        dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel, cnf_map, es_map, tipo_sector_sel)
    elif "2.2" in sub_tab:
        dibujar_subtab_22_colapsados(df_fecha, cnf_map, acc_sel, turno_sel)
    elif "2.3" in sub_tab:
        dibujar_subtab_23_gantt_sectores(df_filtered, cnf_map, es_map, turno_sel)
    else:
        dibujar_subtab_24_predictivo(df_acc, cnf_map, fecha_sel)


def dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel, cnf_map, es_map, tipo_sector_sel):
    st.subheader("⏱️ Perfil de Carga y Capacidad Cronológica del ACC")
    df_plot = df_filtered.copy()

    if tipo_sector_sel != "TODOS (CS y ES)":
        objetivo = "CS" if "(CS)" in tipo_sector_sel else "ES"

        def contar(cnf):
            secs = sectores_de(cnf, cnf_map)
            if not secs:
                return obtener_numero_sectores_nominal(cnf)
            return sum(1 for s in secs if engine.classify_sector(s, es_map) == objetivo)

        df_plot["Sectores_Activos"] = df_plot["Configuracion"].apply(contar)

    if fecha_sel.startswith("TODOS"):
        agrup = df_plot.groupby("Hora")["Sectores_Activos"].mean().reset_index()
        fig = px.line(agrup, x="Hora", y="Sectores_Activos", markers=True,
                      title=f"Curva Promedio de Apertura ({tipo_sector_sel}) - ACC: {acc_sel}")
    else:
        fig = px.line(df_plot.sort_values("Hora"), x="Hora", y="Sectores_Activos", text="Configuracion",
                      markers=True, line_shape="hv",
                      title=f"Curva de Apertura ({tipo_sector_sel}) - ACC: {acc_sel} ({fecha_sel})")
        fig.update_traces(textposition="top center")
    fig.update_traces(line_color="#2b5c8f", line_width=3)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.markdown(f"### 📊 Estadísticas de Uso de Configuraciones y Sectores ({tipo_sector_sel})")
    total = int(df_plot["Duracion_Min"].sum())
    # Media ponderada por duración: un tramo de 5 min no pesa como uno de 5 h
    media = (df_plot["Sectores_Activos"] * df_plot["Duracion_Min"]).sum() / total if total else 0.0
    sec_min, sec_max = int(df_plot["Sectores_Activos"].min()), int(df_plot["Sectores_Activos"].max())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📉 SECTORES MÍNIMOS", f"{sec_min}")
    c2.metric("📈 SECTORES MÁXIMOS", f"{sec_max}")
    c3.metric("📊 MEDIA EN SALA (ponderada)", f"{media:.2f} sec.")
    c4.metric("⏱️ TIEMPO TOTAL ANALIZADO", f"{total:,} min")

    col_t, col_s = st.columns([3, 2])
    with col_t:
        st.markdown("#### 📑 Frecuencia y Minutos por Configuración")
        freq = (df_plot.groupby("Configuracion")
                .agg(Ocurrencias=("Hora", "count"), Minutos_Totales=("Duracion_Min", "sum"),
                     Sectores_Contados=("Sectores_Activos", "first"))
                .reset_index())
        freq["Porcentaje Tiempo (%)"] = (freq["Minutos_Totales"] / total * 100).round(2) if total else 0.0
        freq = freq.sort_values("Minutos_Totales", ascending=False)
        st.dataframe(freq, use_container_width=True, hide_index=True)
    with col_s:
        st.markdown("#### 💡 Conclusiones Operativas Automáticas")
        if not freq.empty:
            top = freq.iloc[0]
            st.info(
                f"🔹 **Configuración dominante:** **`{top['Configuracion']}`**, con **{int(top['Minutos_Totales'])} minutos** "
                f"({top['Porcentaje Tiempo (%)']}% del total).\n\n"
                f"🔹 **Carga de sala:** entre **{sec_min} y {sec_max} sectores simultáneos**.")

    st.markdown("---")
    pivot = (df_plot.groupby(["Configuracion", "Turno"])["Duracion_Min"].sum()
             .unstack(fill_value=0).reindex(columns=TURNOS, fill_value=0).astype(int))
    g1, g2 = st.columns(2)
    with g1:
        st.subheader("⏱️ Minutos por Turno y Configuración")
        fig_bar, ax = plt.subplots(figsize=(8, max(4, len(pivot) * 0.35)))
        pivot.plot(kind="barh", stacked=True, ax=ax, colormap="YlGnBu")
        ax.set_xlabel("Minutos acumulados")
        ax.set_ylabel("Configuración")
        ax.legend(title="Turno", loc="lower right", fontsize=9)
        st.pyplot(fig_bar)
        plt.close(fig_bar)
    with g2:
        st.subheader("🔥 Mapa de Calor: Minutos por Configuración y Turno")
        fig_h, ax = plt.subplots(figsize=(8, max(4, len(pivot) * 0.35)))
        sns.heatmap(pivot, annot=True, fmt="d", cmap="YlGnBu", ax=ax, cbar=False)
        ax.set_ylabel("Configuración")
        ax.set_xlabel("Turno")
        st.pyplot(fig_h)
        plt.close(fig_h)


def dibujar_subtab_22_colapsados(df_fecha, cnf_map, acc_sel, turno_sel):
    """La secuencia se calcula por día y fichero completos (sin filtrar por turno)
    para que el primer tramo de cada día no se compare con otro día."""
    from plotly.subplots import make_subplots
    st.subheader("🚀 Dinámica Secuencial de Desdobles y Colapsos")

    eventos = []
    for (_, fecha), grupo in df_fecha.sort_values(["Archivo", "Fecha", "Hora"]).groupby(["Archivo", "Fecha"], sort=False):
        prev = None
        for _, fila in grupo.iterrows():
            cnf = fila["Configuracion"]
            act = sectores_de(cnf, cnf_map)
            base = {"Fecha": fecha, "Hora": fila["Hora"], "Turno": fila["Turno"], "Sectores Totales": len(act)}
            if prev is None:
                eventos.append({**base, "Transición": f"Inicio ({cnf})", "Acción": "Apertura Inicial",
                                "Sectores Implicados": ", ".join(sorted(act)), "Delta_Sectores": 0})
            else:
                pcnf, psec = prev
                delta = len(act) - len(psec)
                if delta > 0:
                    accion, impl = "🟢 DESDOBLAMIENTO", act - psec
                elif delta < 0:
                    accion, impl = "🔴 COLAPSO", psec - act
                else:
                    accion, impl = "Estable", act ^ psec
                eventos.append({**base, "Transición": f"{pcnf} ➔ {cnf}", "Acción": accion,
                                "Sectores Implicados": ", ".join(sorted(impl)) or "Ninguno",
                                "Delta_Sectores": delta})
            prev = (cnf, act)

    df_seq = pd.DataFrame(eventos)
    if turno_sel != "TODOS" and not df_seq.empty:
        df_seq = df_seq[df_seq["Turno"] == turno_sel]
    if df_seq.empty:
        st.info("Sin eventos para los filtros seleccionados.")
        return

    varias = df_seq["Fecha"].nunique() > 1
    df_seq["Eje"] = (df_seq["Fecha"] + " " + df_seq["Hora"]) if varias else df_seq["Hora"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    barras = df_seq[df_seq["Acción"] != "Apertura Inicial"]
    for sel, nombre, color in [(barras["Delta_Sectores"] > 0, "🟢 DESDOBLAMIENTO", "#2ca02c"),
                               (barras["Delta_Sectores"] < 0, "🔴 COLAPSO", "#d62728")]:
        sub = barras[sel]
        if not sub.empty:
            fig.add_trace(go.Bar(x=sub["Eje"], y=sub["Delta_Sectores"], name=nombre, marker_color=color), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_seq["Eje"], y=df_seq["Sectores Totales"], name="📈 TOTAL SECTORES",
                             mode="lines+markers", line=dict(color="#1f77b4", width=3, dash="dash")), secondary_y=True)
    fig.update_layout(title_text=f"Evolución de Tendencias - ACC: {acc_sel}", height=420)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_seq.drop(columns=["Eje"]), use_container_width=True, hide_index=True)


def dibujar_subtab_23_gantt_sectores(df_filtered, cnf_map, es_map, turno_sel):
    st.subheader("🗺️ Perfil de Apertura por Sector (Gantt)")
    regs = []
    for _, fila in df_filtered.sort_values(["Fecha", "Hora"]).iterrows():
        # Fechas dd/mm/aaaa: dayfirst explícito para no confundir día y mes
        dia = pd.to_datetime(fila["Fecha"], dayfirst=True, errors="coerce")
        if pd.isna(dia):
            dia = pd.Timestamp("2000-01-01")
        ini = dia + pd.Timedelta(minutes=engine.hhmm_to_min(fila["Hora"]))
        fin = ini + pd.Timedelta(minutes=int(fila["Duracion_Min"]))  # cruza medianoche correctamente
        secs = sectores_de(fila["Configuracion"], cnf_map)
        for sec in secs:
            regs.append({"Sector": sec, "Inicio": ini, "Fin": fin, "Configuración": fila["Configuracion"],
                         "Carga_Sala": len(secs),
                         "Tipo": "CS" if engine.classify_sector(sec, es_map) == "CS" else "ES"})
    df_g = pd.DataFrame(regs)
    if df_g.empty:
        st.warning("Las configuraciones del periodo no están definidas en el .CFG.")
        return
    fig = px.timeline(df_g, x_start="Inicio", x_end="Fin", y="Sector", color="Carga_Sala",
                      hover_data=["Configuración", "Tipo"],
                      color_continuous_scale=px.colors.sequential.Cividis_r,
                      title=f"Mapa de Densidad y Carga en Sala (Turno: {turno_sel})")
    fig.update_yaxes(categoryorder="category descending")
    fig.update_layout(height=max(400, 22 * df_g["Sector"].nunique()))
    st.plotly_chart(fig, use_container_width=True)


def dibujar_subtab_24_predictivo(df_acc, cnf_map, fecha_sel):
    st.subheader("🔮 Asistente Predictivo de Capacidad (Mapeo Histórico)")
    st.caption("Usa el histórico completo del ACC; si se elige una fecha, se toman los días de la misma semana.")
    p1, p2 = st.columns(2)
    with p1:
        hora_test = st.text_input("⏱️ Hora a consultar (HH:MM):", value="13:30", key="pred_hora_input")
    ref = None if fecha_sel.startswith("TODOS") else fecha_sel
    pred = engine.predict_atc_behavior(df_acc, cnf_map, hora_consulta=hora_test, fecha_referencia=ref)
    with p2:
        st.markdown(f"**🔮 Diagnóstico estadístico** ({pred['dia_semana']}, {pred['total_muestras']} muestras):")
        a, b, c = st.columns(3)
        a.metric("🟢 PROB. DESDOBLE", f"{pred['prob_desdoble']}%")
        b.metric("🔴 PROB. FUSIÓN", f"{pred['prob_fusion']}%")
        c.metric("⚪ PROB. ESTABLE", f"{pred['prob_estable']}%")
    st.info(f"Tendencia: **{pred['tendencia_principal']}** · Configuración más frecuente: **{pred['sector_objetivo']}**")


# ---------------------------------------------------------------------------
# Pestaña 3 - Motor de desdoblamiento
# ---------------------------------------------------------------------------
FECHA_TODAS_INSP = "TODOS LOS DÍAS (Ciclo Completo)"
NIVEL_CS = "Por Sector Integrado (CS)"


def _sanear(key, options):
    """Borra el valor guardado de un selector si ya no está entre sus opciones."""
    if key in st.session_state and st.session_state[key] not in list(options):
        del st.session_state[key]


def _fmt_min(m):
    m = int(m)
    return f"{m} min" if m < 60 else f"{m / 60:,.0f} h"


def etiqueta_uso(cs, uso_cs):
    m, dias = int(uso_cs.loc[cs, "Minutos"]), int(uso_cs.loc[cs, "Dias"])
    return f"{cs} · {_fmt_min(m)} en {dias} días" if m else f"{cs} · sin uso en el ciclo"


# ---------------------------------------------------------------------------
# Selección compartida entre el Motor y la Inspección Jerárquica
# ---------------------------------------------------------------------------
# st.session_state["sel_activa"] = (ACC, CS). Solo cambia cuando el usuario elige
# algo en uno de los selectores enlazados (los callbacks se ejecutan antes de cada
# recarga). Cada pestaña la aplica a sus selectores ANTES de dibujarlos, así que
# las dos muestran siempre el mismo ACC y el mismo CS.
SEL = "sel_activa"


def _sel():
    return st.session_state.get(SEL) or (None, None)


def _cb_motor_acc():
    st.session_state[SEL] = (st.session_state.get("acc_select"), None)


def _cb_motor_cs(acc):
    st.session_state[SEL] = (acc, st.session_state.get(f"cs_select_{acc}"))


def _cb_insp_acc():
    st.session_state[SEL] = (st.session_state.get("hier_acc"), None)


def _cb_insp_cs():
    st.session_state[SEL] = (st.session_state.get("hier_acc"), st.session_state.get("detail_CS"))


def _cb_ver_sector_activo():
    st.session_state["hier_nivel"] = NIVEL_CS
    st.session_state["hier_fecha"] = FECHA_TODAS_INSP


def banner_sector_activo(acc, cs):
    st.info(f"🔗 **Sector activo** (compartido entre el Motor y la Inspección Jerárquica): `{acc}` · `{cs}`. "
            "Cámbialo en cualquiera de las dos pestañas y la otra lo sigue.")


def panel_uso_cs(df_cos, cfg_map, acc, cs, fila_uso):
    """Resumen de uso del CS en el ciclo, con los mismos datos que la Inspección
    Jerárquica. Devuelve True si el CS no se abrió en ningún tramo."""
    mins = int(fila_uso["Minutos"])
    por_cnf = engine.sector_config_usage(df_cos, cfg_map, acc, cs)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⏱️ Abierto en el ciclo", _fmt_min(mins))
    k2.metric("📅 Días con apertura", int(fila_uso["Dias"]))
    k3.metric("🔄 Tramos del COS afectados", int(fila_uso["Tramos"]))
    k4.metric("⚙️ Configuraciones distintas", len(por_cnf))
    if mins == 0:
        st.warning(f"⚠️ {cs} no se abrió en ningún tramo del ciclo cargado, así que desdoblarlo no cambiaría el .COS. "
                   "Elige otro CS o carga un ciclo en el que esté operativo.")
        return True
    with st.expander(f"📈 Detalle de uso de {cs} (mismos datos que la Inspección Jerárquica)"):
        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Por turno**")
            dt = pd.DataFrame({"Turno": engine.TURNOS, "Minutos": [int(fila_uso[t]) for t in engine.TURNOS]})
            dt["Porcentaje (%)"] = (dt["Minutos"] / mins * 100).round(2)
            st.dataframe(dt, use_container_width=True, hide_index=True)
        with e2:
            st.markdown("**Configuraciones que se reescribirán**")
            st.dataframe(por_cnf, use_container_width=True, hide_index=True)
    return False


def render_tab3(d):
    st.header("3. Motor de Desdoblamiento de Sectores Colapsados (CS)")
    guia("""
    **Qué es.** Desdobla un sector colapsado (CS) en el **menor número de piezas** posible (CS intermedios o ES definidos en el `.SPC`) y genera los `.COS` y `.CFG` para simular en NEST la demora y las regulaciones con ese desdoble.

    **Datos necesarios.** `.SPC`, `.CFG` y `.COS`.

    **Paso a paso.**
    1. **ACC**: aparecen primero los que tienen tramos en el `.COS`.
    2. **Sector colapsado (CS)**: solo los que el `.SPC` define con 2 o más ES y el ACC abre en alguna configuración. Por defecto se muestran **solo los CS operativos en el ciclo cargado**, ordenados de más a menos uso, con sus horas y días de apertura. Desmarca la casilla para ver también los que no se usaron.
    3. **Revisa el uso del CS**: horas abierto, días con apertura, tramos del `.COS` que se modificarán y número de configuraciones distintas. El desplegable de detalle muestra el reparto por turno y las configuraciones que se reescribirán. Si el CS no se abrió en el ciclo, aparece un aviso y el botón Ejecutar queda desactivado.
    4. **Elige la partición** en la tabla de particiones mínimas (por defecto, la primera) o escribe una a mano en *Piezas*.
    5. **Ajusta los parámetros** y pulsa **Ejecutar Desdoblamiento**.
    6. **Descarga el ZIP** (también disponible en la pestaña Exportación).

    **Tabla de particiones mínimas.**

    | Columna | Significado |
    |---|---|
    | Nº piezas | Número de piezas; todas las filas tienen el mínimo posible |
    | Partición | Piezas que la forman |
    | Configs existentes | Configuraciones del `.COS` que, tras el desdoble, coinciden con una que ya existe en el `.CFG` y se reutilizan |
    | Configs nuevas | Configuraciones del `.COS` cuyo resultado no existe en el `.CFG` y habrá que crear |
    | Piezas sin CS propio | Piezas que no tienen bloque `A` propio en el `.SPC` (solo aparecen como `S` de otro bloque) |
    | Minutos históricos piezas | Suma de los minutos que cada pieza estuvo abierta en el ciclo: cuánto se usa ya esa forma de partir |

    Orden: menos piezas sin CS propio → menos configuraciones nuevas → más minutos históricos. Solo cuentan las configuraciones que **aparecen en el `.COS`**, que son las únicas que se reescriben.

    **Parámetros de ejecución.**
    * **Piezas**: lo que se aplicará. Se rellena con la partición elegida y se puede editar (separa con `;` o `,`). Al ejecutar se valida que cubra el CS de forma exacta: sin ES que falten o sobren, sin solapes entre piezas, sin nombres inexistentes ni repetidos y con al menos dos piezas.
    * **Sufijo**: se añade a las configuraciones nuevas, que se renumeran con el total real de sectores (`CNF3C` → `CNF4C_D`). Si el nombre ya existe se añade un número (`_D2`).
    * **Longitud máxima de nombre**: si NEST limita los caracteres del nombre de configuración, indícalo y se avisará de los que lo superen. Con 0 no se comprueba.

    **Resultado.** Indicadores de tramos modificados y configuraciones nuevas o reutilizadas, la lista de configuraciones nuevas, la matriz PRE ➔ POST y el detalle tramo a tramo. Los tramos con configuraciones que no están en el `.CFG` se dejan sin cambios y se avisa.

    **Contenido del ZIP.**
    * `AUDIT_<fichero>.cos`: el `.COS` reescrito. Las líneas de otros ACC y el formato original se conservan.
    * `NUEVAS_CONFIGURACIONES_<ACC>.cfg`: solo las configuraciones creadas.
    * `CFG_FUSIONADO_<ACC>.cfg`: el `.CFG` original más las nuevas, listo para cargar en NEST.
    * `AUDITORIA_<ACC>_<CS>.csv`: el detalle tramo a tramo.
    * `LEEME.txt`: un resumen de la ejecución.

    **Enlace con la Inspección Jerárquica.** El ACC y el CS forman un **sector activo compartido** entre las dos pestañas (lo indica el aviso azul 🔗):
    * Al elegir un ACC o un CS aquí, la Inspección muestra el mismo ACC y, en el nivel *Por Sector Integrado (CS)*, el detalle de ese CS.
    * Al elegir un ACC o un CS en la Inspección, el Motor lo selecciona automáticamente. Si el CS no tuvo uso en el ciclo, se desmarca la casilla de operativos para poder mostrarlo.
    * Si el sector elegido en la Inspección no es desdoblable, o su ACC no está en el `.CFG`, el Motor mantiene su selección y lo indica.
    * Las cifras de uso coinciden en las dos pestañas porque salen del mismo cálculo.
    * Streamlit no permite cambiar de pestaña desde el código: después de elegir, haz clic en la otra pestaña.
    """)

    df_cos, cfg_map, es_map = d["df_cos"], d["cfg_map"], d["es_map"]
    if not es_map:
        st.warning("⚠️ Carga los archivos .SPC en la Pestaña 1 para continuar.")
        return
    if not cfg_map:
        st.warning("⚠️ Carga los archivos .CFG en la Pestaña 1 para continuar.")
        return

    accs_cfg = sorted({a for a, _ in cfg_map})
    accs_cos = set(df_cos["ACC"].unique()) if not df_cos.empty else set()
    accs = sorted(accs_cfg, key=lambda a: (a not in accs_cos, a))  # primero los que tienen COS

    sel_acc0, sel_cs0 = _sel()
    c1, c2 = st.columns(2)
    with c1:
        if sel_acc0 in accs:
            st.session_state["acc_select"] = sel_acc0
        else:
            _sanear("acc_select", accs)
        acc_sel = st.selectbox("1. Seleccionar ACC:", options=accs, key="acc_select", on_change=_cb_motor_acc)
    opciones_cs = engine.cs_options_for_acc(acc_sel, cfg_map, es_map)
    uso = (engine.sector_usage_table(df_cos, cfg_map, acc_sel) if not df_cos.empty
           else pd.DataFrame(columns=engine.USO_COLS))
    uso_cs = uso.reindex(opciones_cs, fill_value=0)
    operativos = [c for c in opciones_cs if uso_cs.loc[c, "Minutos"] > 0]
    with c2:
        if not opciones_cs:
            st.info("Este ACC no abre ningún sector que el .SPC defina con 2 o más ES.")
            return
        if "solo_operativos" not in st.session_state:
            st.session_state["solo_operativos"] = True
        if sel_acc0 == acc_sel and sel_cs0 in opciones_cs and sel_cs0 not in operativos:
            st.session_state["solo_operativos"] = False  # el sector activo no tuvo uso: mostrarlo
        solo_op = st.checkbox(
            f"Solo CS operativos en el ciclo cargado ({len(operativos)} de {len(opciones_cs)})",
            key="solo_operativos",
            help="Oculta los CS que no se abrieron en ningún tramo del .COS: desdoblarlos no cambiaría nada.")
        lista = operativos if solo_op else opciones_cs
        if not lista:
            st.warning("Ningún CS desdoblable de este ACC se abrió en el ciclo cargado. "
                       "Desmarca la casilla para verlos todos.")
            return
        lista = sorted(lista, key=lambda c: (-int(uso_cs.loc[c, "Minutos"]), c))
        key_cs = f"cs_select_{acc_sel}"
        if sel_acc0 == acc_sel and sel_cs0 in lista:
            st.session_state[key_cs] = sel_cs0
        else:
            _sanear(key_cs, lista)
        cs_sel = st.selectbox("2. Sector colapsado (CS) a desdoblar (ordenado por uso):", options=lista,
                              key=key_cs, format_func=lambda c: etiqueta_uso(c, uso_cs),
                              on_change=_cb_motor_cs, args=(acc_sel,))

    # Si la selección compartida aún no apunta a un CS de este ACC, la fija el Motor
    if sel_acc0 is None or (sel_acc0 == acc_sel and sel_cs0 is None):
        st.session_state[SEL] = (acc_sel, cs_sel)
    if _sel() == (acc_sel, cs_sel):
        banner_sector_activo(acc_sel, cs_sel)
    elif sel_acc0 not in accs:
        st.info(f"🔗 El ACC activo en la Inspección ({sel_acc0}) no está en el .CFG; el Motor mantiene {acc_sel}.")
    else:
        st.info(f"🔗 El sector activo en la Inspección ({sel_cs0}) no se puede desdoblar; "
                f"el Motor mantiene {cs_sel}.")

    universo = sorted(es_map[cs_sel])
    sector_min = {k: int(v) for k, v in uso["Minutos"].items()}
    particiones = engine.minimal_partitions(cs_sel, es_map)
    ranking = engine.rank_partitions(acc_sel, cs_sel, particiones, cfg_map, sector_min,
                                     cnfs_usadas=engine.configs_used(df_cos, acc_sel))

    st.markdown(f"### Desdoblamiento de **{cs_sel}** ({len(universo)} ES)")
    sin_uso = panel_uso_cs(df_cos, cfg_map, acc_sel, cs_sel, uso_cs.loc[cs_sel])
    izq, der = st.columns([3, 2])

    with izq:
        st.write("**🧩 Sectores elementales que lo forman:** " + ", ".join(f"`{e}`" for e in universo))
        piezas = engine.candidate_pieces(cs_sel, es_map)
        df_piezas = pd.DataFrame([{
            "Pieza": p["name"], "Nº ES": len(p["es"]), "ES": ", ".join(sorted(p["es"])),
            "Minutos abierta": sector_min.get(p["name"], 0),
            "CS propio en SPC": "Sí" if p["own_cs"] else "No",
            "Alias": ", ".join(p["aliases"]),
        } for p in piezas]).sort_values(["Nº ES", "Pieza"], ascending=[False, True])
        with st.expander(f"Piezas disponibles en el SPC ({len(df_piezas)})"):
            st.dataframe(df_piezas, use_container_width=True, hide_index=True)

        if ranking.empty:
            st.warning("No se encontró ninguna partición válida para este CS.")
            idx = None
        else:
            n = int(ranking.iloc[0]["Nº piezas"])
            st.markdown(f"**🏆 Particiones mínimas: {len(ranking)} opción(es) de {n} piezas**")
            st.dataframe(ranking.drop(columns=["Parámetro"]), use_container_width=True, hide_index=True)
            st.caption("Configs existentes / nuevas: solo las configuraciones que abren el CS **y aparecen en el .COS**. "
                       "Orden: piezas sin CS propio (menos es mejor) → configuraciones nuevas a crear (menos) → "
                       "minutos históricos de apertura de las piezas (más).")
            if int(ranking.iloc[0]["Piezas sin CS propio"]) > 0:
                st.warning("⚠️ La mejor partición incluye ES sin bloque propio en el .SPC; comprueba que NEST puede abrirlos como sector.")
            idx = st.selectbox("Partición a aplicar:", options=list(range(len(ranking))),
                               format_func=lambda i: f"{i + 1}. {ranking.iloc[i]['Partición']}",
                               key=f"part_sel_{acc_sel}_{cs_sel}")

    with der:
        st.write("**⚙️ Parámetros de ejecución**")
        defecto = ranking.iloc[idx]["Parámetro"] if idx is not None else ";".join(universo)
        target = st.text_input("Piezas (separadas por ';' o ','):", value=defecto,
                               key=f"target_{acc_sel}_{cs_sel}_{idx}",
                               help="Se rellena con la partición elegida. Puedes editarla: debe cubrir el CS de forma exacta y sin solapes.")
        sufijo = st.text_input("Sufijo de las configuraciones nuevas:", value="_D", key="sufijo_cnf")
        max_len = st.number_input("Longitud máxima de nombre en NEST (0 = sin comprobar):",
                                  min_value=0, max_value=64, value=0, step=1, key="max_len_cnf")
        ejecutar = st.button("▶️ Ejecutar Desdoblamiento", type="primary", use_container_width=True,
                             disabled=sin_uso or df_cos.empty,
                             help="Desactivado si el CS no se abrió en el ciclo cargado.")

    if ejecutar:
        tokens = engine.parse_tokens(target)
        val = engine.validate_partition(cs_sel, tokens, es_map)
        if not val["ok"]:
            st.error("🚨 **Error de integridad espacial:** la combinación no cubre el CS de forma exacta y disjunta.")
            for clave, msg in [("faltantes", "Faltan por cubrir"), ("sobrantes", "Elementos ajenos al CS"),
                               ("solapes", "ES cubiertos por más de una pieza"),
                               ("desconocidos", "Nombres que no existen en el SPC"),
                               ("duplicados", "Piezas repetidas")]:
                if val[clave]:
                    st.warning(f"⚠️ {msg}: `{', '.join(val[clave])}`")
            if val["es_el_propio"]:
                st.warning(f"⚠️ {cs_sel} no puede ser una pieza de sí mismo.")
            if val["piezas"] < 2:
                st.warning("⚠️ Un desdoblamiento necesita al menos dos piezas.")
        elif df_cos.empty:
            st.error("⚠️ Se requieren archivos .COS para ejecutar el desdoblamiento.")
        else:
            with st.spinner("Reescribiendo los esquemas de apertura..."):
                res = engine.run_desdoble_audit(
                    spc_files=list(d["spc_items"]), cos_files=list(d["cos_items"]),
                    cfg_files=list(d["cfg_items"]), acc=acc_sel, cs_integrated=cs_sel,
                    pieces=tokens, sufijo=sufijo.strip().upper(), max_len=int(max_len) or None)
            res.update(acc=acc_sel, cs=cs_sel, piezas=tokens, firma=d["firma"])
            st.session_state.audit_result = res

    mostrar_resultado(d)


def mostrar_resultado(d):
    res = st.session_state.get("audit_result")
    if not res or res.get("firma") != d["firma"]:
        return
    st.markdown("---")
    if not res["ok"]:
        st.error(f"🚨 {res['error']}")
        return

    df_c, df_n = res["df_cambios"], res["df_nuevas"]
    st.success(f"✅ {res['cs']} desdoblado en {len(res['piezas'])} piezas: `{';'.join(res['piezas'])}`")
    for aviso in res["avisos"]:
        st.warning(f"⚠️ {aviso}")
    st.download_button("📦 Descargar ficheros NEST (ZIP)", data=res["zip_bytes"],
                       file_name=f"desdoble_{res['acc']}_{res['cs']}.zip", mime="application/zip",
                       key="btn_descarga_zip_auditoria")

    if df_c.empty:
        st.info("ℹ️ Ningún tramo de los .COS abre este CS: no hay cambios.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("🔄 TRAMOS MODIFICADOS", len(df_c))
    k2.metric("✨ CONFIGURACIONES NUEVAS", len(df_n))
    k3.metric("♻️ REUTILIZADAS DEL CFG", df_c[df_c["Resultado"] == "Existente en CFG"]["CNF_POST"].nunique())

    if not df_n.empty:
        st.markdown("#### ✨ Configuraciones nuevas para el .CFG")
        st.dataframe(df_n, use_container_width=True, hide_index=True)
    st.markdown("#### 📑 Matriz de transición (PRE ➔ POST)")
    st.dataframe(pd.crosstab(df_c["CNF_PRE"], df_c["CNF_POST"], margins=True, margins_name="Total"),
                 use_container_width=True)
    st.markdown("#### 📋 Tramos modificados")
    st.dataframe(df_c, use_container_width=True, hide_index=True)
    sin_cfg = res["df_audit"][res["df_audit"]["Resultado"] == "CNF no definida en CFG"]
    if not sin_cfg.empty:
        st.warning(f"⚠️ {len(sin_cfg)} tramos usan configuraciones que no están en el .CFG: "
                   f"`{', '.join(sorted(sin_cfg['CNF_PRE'].unique()))}`. Se han dejado sin cambios.")


# ---------------------------------------------------------------------------
# Pestaña 4 - Inspección jerárquica
# ---------------------------------------------------------------------------
def render_tab_inspeccion_espacio_aereo(d):
    st.header("4. Inspección Jerárquica: ACC ➔ Configuración ➔ CS ➔ ES")
    guia("""
    **Qué es.** Cuánto tiempo y en qué turnos se usó cada configuración y cada sector de un ACC. Sirve para decidir qué CS conviene desdoblar.

    **Datos necesarios.** `.COS`; para los niveles de sector, también `.CFG` y `.SPC`.

    **Selectores.**
    * **ACC**: centro a consultar.
    * **Ámbito temporal**: el ciclo completo o un día concreto.
    * **Nivel de consulta**:
        * *Por Configuración*: minutos, número de tramos y porcentaje de tiempo de cada configuración.
        * *Por Sector Integrado (CS)* / *Por Sector Elemental (ES)*: mapa de calor de minutos por sector y turno, tabla resumen y detalle de un sector.

    **Tabla resumen de sectores.** Minutos totales, días con apertura, tramos y minutos por turno. En el nivel CS se añaden:
    * **Nº ES (SPC)**: cuántos sectores elementales forman el CS.
    * **Desdoblable en el Motor**: si el Motor puede desdoblarlo (el `.SPC` lo define con 2 o más ES y el ACC está en el `.CFG`).

    **Detalle de un sector.** El selector está ordenado de más a menos uso. Muestra el reparto por turno y las configuraciones en las que se abrió.

    **Enlace con el Motor de desdoblamiento.** El ACC y el CS forman un **sector activo compartido** con el Motor (aviso azul 🔗):
    * El ACC elegido aquí pasa al Motor, que muestra el último CS elegido para ese ACC o, si no hay ninguno, el más usado.
    * En el nivel CS, el sector elegido en el selector de detalle pasa al Motor si es desdoblable. Debajo del selector se indica si lo es.
    * Lo que elijas en el Motor aparece aquí: mismo ACC y, en el nivel CS, el detalle de ese sector. Si estás en otro nivel, el botón **👁️ Ver el detalle** te lleva al nivel CS con el ciclo completo.
    * Si eliges un día concreto en el que el sector activo no se abrió, se avisa y basta con volver al ciclo completo.
    * Las cifras coinciden con las del Motor porque salen del mismo cálculo. Para ir al Motor, haz clic en su pestaña.
    """)

    df_cos, cfg_map, es_map = d["df_cos"], d["cfg_map"], d["es_map"]
    if df_cos.empty:
        st.warning("⚠️ Carga al menos ficheros .COS en la Pestaña 1.")
        return

    sel_acc0, sel_cs0 = _sel()
    h1, h2, h3 = st.columns(3)
    accs = sorted(df_cos["ACC"].unique())
    with h1:
        if sel_acc0 in accs:
            st.session_state["hier_acc"] = sel_acc0
        else:
            _sanear("hier_acc", accs)
        sel_acc = st.selectbox("1. Seleccionar ACC:", options=accs, key="hier_acc", on_change=_cb_insp_acc)
    df_acc = df_cos[df_cos["ACC"] == sel_acc]
    fechas = [FECHA_TODAS_INSP] + sorted(df_acc["Fecha"].unique())
    niveles = ["Por Configuración", NIVEL_CS, "Por Sector Elemental (ES)"]
    with h2:
        _sanear("hier_fecha", fechas)
        sel_fecha = st.selectbox("2. Ámbito Temporal:", options=fechas, key="hier_fecha")
    with h3:
        nivel = st.selectbox("3. Nivel de Consulta:", options=niveles, key="hier_nivel")

    df_scope = df_acc if sel_fecha.startswith("TODOS") else df_acc[df_acc["Fecha"] == sel_fecha]
    hay_activo = sel_acc0 == sel_acc and sel_cs0 is not None
    if hay_activo and nivel != NIVEL_CS:
        banner_sector_activo(sel_acc, sel_cs0)
        st.button(f"👁️ Ver el detalle de {sel_cs0} (nivel CS, ciclo completo)", key="btn_ver_activo",
                  on_click=_cb_ver_sector_activo)
    st.markdown("---")

    if nivel == "Por Configuración":
        st.markdown(f"#### 📊 Configuraciones en **{sel_acc}** ({sel_fecha})")
        agg = df_scope.groupby("Configuracion").agg(Ocurrencias=("Hora", "count"), Minutos_Totales=("Duracion_Min", "sum")).reset_index()
        tot = agg["Minutos_Totales"].sum()
        agg["Porcentaje (%)"] = (agg["Minutos_Totales"] / tot * 100).round(2) if tot else 0.0
        agg = agg.sort_values("Minutos_Totales", ascending=False)
        t1, t2 = st.columns([2, 1])
        t1.dataframe(agg, use_container_width=True, hide_index=True)
        with t2:
            st.plotly_chart(px.pie(agg, names="Configuracion", values="Minutos_Totales", title="Distribución por minutos"), use_container_width=True)
        return

    tipo = "CS" if "Integrado" in nivel else "ES"
    st.markdown(f"#### 🔥 Sectores **{tipo}** por turno en **{sel_acc}** ({sel_fecha})")
    cnf_map, _ = engine.cnf_map_for_acc(cfg_map, sel_acc)
    if not cnf_map:
        st.info("Se requiere cargar ficheros .CFG válidos.")
        return

    # Misma base de cálculo que el Motor de desdoblamiento (engine.explode_sectors)
    ex = engine.explode_sectors(df_scope, cnf_map)
    df_sec = ex[ex["Sector"].map(lambda s: engine.classify_sector(s, es_map) == tipo)] if not ex.empty else ex
    if df_sec.empty:
        st.warning(f"No se encontraron sectores {tipo} activos en este ámbito.")
        return

    uso = engine.usage_table(df_sec)
    pivot = uso[TURNOS].sort_index()
    fig, ax = plt.subplots(figsize=(10, max(5, len(pivot) * 0.3)))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="YlGnBu", ax=ax, cbar=False)
    ax.set_title(f"Tiempo de apertura acumulado en minutos (sectores {tipo})")
    ax.set_ylabel(f"Sector ({tipo})")
    ax.set_xlabel("Turno")
    st.pyplot(fig)
    plt.close(fig)

    desdoblables = set(engine.cs_options_for_acc(sel_acc, cfg_map, es_map)) if tipo == "CS" else set()
    acc_en_motor = sel_acc in {a for a, _ in cfg_map}
    resumen = uso.rename(columns={"Minutos": "Minutos Totales", "Dias": "Días", **{t: f"{t} (min)" for t in TURNOS}})
    if tipo == "CS":
        resumen.insert(0, "Nº ES (SPC)", [len(es_map.get(s, ())) for s in resumen.index])
        resumen.insert(1, "Desdoblable en el Motor", ["Sí" if s in desdoblables else "No" for s in resumen.index])
    resumen = resumen.reset_index().rename(columns={"Sector": f"Sector ({tipo})"})
    st.markdown(f"#### 📋 Resumen de tiempos (sectores {tipo})")
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    st.markdown("---")
    opciones_det = list(uso.index)  # ordenados por minutos, como en el Motor
    key_det = f"detail_{tipo}"
    if tipo == "CS" and hay_activo and sel_cs0 in opciones_det:
        st.session_state[key_det] = sel_cs0
    else:
        _sanear(key_det, opciones_det)
    sector_sel = st.selectbox(f"Selecciona un sector {tipo} para ver sus configuraciones:", options=opciones_det,
                              key=key_det, format_func=lambda s: f"{s} · {_fmt_min(uso.loc[s, 'Minutos'])}",
                              on_change=_cb_insp_cs if tipo == "CS" else None)
    if tipo == "CS":
        if _sel() == (sel_acc, sector_sel):
            banner_sector_activo(sel_acc, sector_sel)
        elif hay_activo:
            st.caption(f"El sector activo {sel_cs0} no se abrió en este ámbito temporal; "
                       "elige el ciclo completo para verlo.")
        if sector_sel in desdoblables and acc_en_motor:
            if _sel() == (sel_acc, sector_sel):
                st.caption(f"✅ {sector_sel} es desdoblable y la pestaña **Motor de Desdoblamiento** ya lo tiene seleccionado.")
            else:
                st.caption(f"✅ {sector_sel} es desdoblable: vuelve a elegirlo en este selector para enviarlo al Motor.")
        else:
            st.caption(f"{sector_sel} no se puede desdoblar en el Motor: el .SPC no lo define con 2 o más ES "
                       "o el ACC no está en el .CFG.")
    sub = df_sec[df_sec["Sector"] == sector_sel]
    tot = int(sub["Duracion_Min"].sum())
    st.write(f"⏱️ El sector **`{sector_sel}`** estuvo activo **{tot} minutos**.")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**📅 Distribución por turno:**")
        dt = sub.groupby("Turno")["Duracion_Min"].sum().reindex(TURNOS, fill_value=0).reset_index(name="Minutos")
        dt["Porcentaje (%)"] = (dt["Minutos"] / tot * 100).round(2) if tot else 0.0
        st.dataframe(dt, use_container_width=True, hide_index=True)
    with d2:
        st.markdown("**⚙️ Presencia por configuración:**")
        dc = sub.groupby("Configuracion")["Duracion_Min"].sum().reset_index(name="Minutos").sort_values("Minutos", ascending=False)
        dc["Presencia (%)"] = (dc["Minutos"] / tot * 100).round(2) if tot else 0.0
        st.dataframe(dc, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Pestaña 5 - Exportación
# ---------------------------------------------------------------------------
def generar_excel(hojas):
    """Genera el .xlsx con la primera librería disponible.
    Devuelve (bytes, motor) o (None, None) si no hay ninguna instalada."""
    for motor in ("openpyxl", "xlsxwriter"):
        try:
            __import__(motor)
        except ImportError:
            continue
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine=motor) as writer:
            for nombre, df_h in hojas.items():
                df_h.to_excel(writer, index=False, sheet_name=nombre[:31])
        return out.getvalue(), motor
    return None, None


def render_tab_export(d):
    st.header("5. Exportación de Datasets y Ficheros NEST")
    guia("""
    **Qué es.** Descarga de los datos de la sesión y de los ficheros NEST generados por el Motor.

    **Dataset consolidado (Excel).** Un `.xlsx` con estas hojas:
    * **Tramos**: todos los tramos de los `.COS` cargados, con duración y turno.
    * **Auditoria_desdoble**: el detalle tramo a tramo del último desdoblamiento (si lo hay).
    * **Configuraciones_nuevas**: las configuraciones que creó ese desdoblamiento (si las hay).

    Cada hoja se puede descargar también por separado en CSV (separador `;`). Si el servidor no tiene instalada una librería de Excel (`openpyxl` o `xlsxwriter`), se avisa y solo quedan disponibles los CSV.

    **Paquete del Motor (ZIP).** Los mismos ficheros que en la pestaña Motor: `.COS` reescritos, `.CFG` con las nuevas configuraciones, `.CFG` fusionado, auditoría en CSV y `LEEME.txt`. Solo aparece si has ejecutado un desdoblamiento con los ficheros cargados ahora mismo.
    """)

    df_cos = d["df_cos"]
    if df_cos.empty:
        st.warning("⚠️ No hay datos cargados para exportar.")
        return

    res = st.session_state.get("audit_result")
    res_valido = bool(res and res.get("ok") and res.get("firma") == d["firma"])

    st.subheader("📊 Dataset consolidado")
    hojas = {"Tramos": df_cos}
    if res_valido:
        hojas["Auditoria_desdoble"] = res["df_audit"]
        if not res["df_nuevas"].empty:
            hojas["Configuraciones_nuevas"] = res["df_nuevas"]

    excel_bytes, motor = generar_excel(hojas)
    if excel_bytes:
        st.download_button("📊 Descargar Excel (.xlsx)", data=excel_bytes, file_name="atfcm_export.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True, key="btn_excel")
    else:
        st.warning("⚠️ No hay ninguna librería de Excel instalada en el servidor (`openpyxl` o `xlsxwriter`). "
                   "Añade `openpyxl` al `requirements.txt` del despliegue. Mientras tanto, puedes descargar los datos en CSV.")
    for nombre, df_h in hojas.items():
        st.download_button(f"📄 Descargar {nombre} (.csv)", data=df_h.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           file_name=f"atfcm_{nombre.lower()}.csv", mime="text/csv",
                           use_container_width=True, key=f"btn_csv_{nombre}")

    st.markdown("---")
    st.subheader("📦 Paquete del motor de desdoblamiento")
    if res_valido:
        st.success(f"✅ Paquete listo: {res['acc']} · {res['cs']} → `{';'.join(res['piezas'])}`")
        st.download_button("📦 Descargar ficheros NEST (.zip)", data=res["zip_bytes"],
                           file_name=f"desdoble_{res['acc']}_{res['cs']}.zip", mime="application/zip",
                           use_container_width=True, key="btn_descarga_global_zip_export")
    else:
        st.info("ℹ️ Ejecuta primero un desdoblamiento en la **Pestaña 3** con los ficheros actuales.")


# ---------------------------------------------------------------------------
# Pestaña 6 - Metodología
# ---------------------------------------------------------------------------
def render_tab_metodologia():
    st.header("6. Metodología")
    st.markdown(r"""
**Modelo de datos.** El `.SPC` define bloques (`A`) con sus componentes (`S`); un componente puede ser otro bloque y se
expande recursivamente hasta los sectores elementales (ES). El `.CFG` asocia a cada par **(ACC, configuración)** sus
sectores abiertos; la clave incluye el ACC porque un mismo nombre puede existir en varios centros.

**Partición mínima.** Para un CS con conjunto de ES $U$, las piezas candidatas son los bloques del SPC cuyo conjunto de
ES es un subconjunto propio de $U$, más cada ES suelto. Se buscan todas las particiones exactas de $U$
(cada ES en una sola pieza) con el **menor número de piezas**, mediante búsqueda en profundidad con poda
(recubrimiento exacto). Las soluciones empatadas se ordenan por: piezas sin bloque propio en el SPC, configuraciones
nuevas que habría que crear y minutos históricos de apertura de las piezas.

**Reescritura.** En cada tramo `.COS` del ACC cuya configuración abre el CS, los sectores pasan a ser
$(\text{sectores} \setminus \{CS\}) \cup \text{piezas}$. Si esa combinación ya existe en el CFG del ACC se reutiliza
su nombre; si no, se crea una configuración nueva renumerada con el recuento real de sectores
(`CNF3C` → `CNF5C_D`). El resto del fichero se copia byte a byte, conservando saltos de línea.

**Salida (ZIP).** `AUDIT_<fichero>.cos`, `NUEVAS_CONFIGURACIONES_<ACC>.cfg` (solo las nuevas),
`CFG_FUSIONADO_<ACC>.cfg` (original + nuevas), `AUDITORIA_<ACC>_<CS>.csv` y `LEEME.txt`.

**Uso de los sectores.** Cada tramo del `.COS` se expande en una fila por sector abierto en su configuración
(según el `.CFG` del ACC). A partir de esa tabla se calculan, para cada sector, los minutos abiertos, los días con
apertura, el número de tramos y el reparto por turno. El Motor y la Inspección Jerárquica usan exactamente este
mismo cálculo, por eso sus cifras coinciden. Un CS con 0 minutos no se abrió en el ciclo: desdoblarlo no cambiaría
el `.COS`, por lo que el Motor lo oculta por defecto y no permite ejecutarlo.

**Configuraciones que cuentan.** En el ranking de particiones solo se consideran las configuraciones que abren el CS
**y aparecen en el `.COS`**. Una configuración definida en el `.CFG` pero nunca usada no se reescribe y no cuenta como
existente ni como nueva.

**Turnos y duraciones.** Mañana 07–15 h, Tarde 15–22 h y Noche 22–07 h, según la hora de inicio del tramo. Un
tramo cuya hora de fin es menor o igual que la de inicio cruza la medianoche.

**Clasificación CS / ES.** Un sector es CS si el `.SPC` lo define con más de un ES y ES en otro caso. Sin `.SPC`
se usa una heurística por nombre (terminado en dígito → ES).
""")


# ---------------------------------------------------------------------------
def main():
    st.title("✈️ ATFCM Sector & Configuration Analyzer")
    faltan = [f for f in ENGINE_REQUIRED if not hasattr(engine, f)]
    if faltan:
        st.error("🚨 El fichero `engine.py` desplegado es anterior a este `app.py` (faltan: "
                 f"`{', '.join(faltan)}`). Sube juntos `app.py`, `engine.py` y `parsers.py` de la misma versión.")
        st.stop()
    tabs = st.tabs(["📁 Carga de Archivos", "📊 Análisis Global", "⚙️ Motor de Desdoblamiento",
                    "🔍 Inspección Jerárquica", "💾 Exportación", "📖 Metodología"])

    with tabs[0]:
        render_tab1()

    cos_items = _items(st.session_state.uploaded_cos)
    spc_items = _items(st.session_state.uploaded_spc)
    cfg_items = _items(st.session_state.uploaded_cfg)
    df_cos, cfg_map, es_map = cargar_datos(cos_items, spc_items, cfg_items)
    d = {"df_cos": df_cos, "cfg_map": cfg_map, "es_map": es_map,
         "cos_items": cos_items, "spc_items": spc_items, "cfg_items": cfg_items,
         "firma": firma(cos_items, spc_items, cfg_items)}

    for tab, render in [(tabs[1], lambda: render_tab2(d)),
                        (tabs[2], lambda: render_tab3(d)),
                        (tabs[3], lambda: render_tab_inspeccion_espacio_aereo(d)),
                        (tabs[4], lambda: render_tab_export(d)),
                        (tabs[5], render_tab_metodologia)]:
        with tab:
            try:
                render()
            except Exception as ex:  # un fallo en una pestaña no debe tumbar las demás
                if type(ex).__name__ in ("StopException", "RerunException"):
                    raise
                st.error(f"🚨 Error en esta pestaña: {type(ex).__name__}: {ex}")
                st.exception(ex)


if __name__ == "__main__":
    main()