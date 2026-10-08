import streamlit as st
import pandas as pd
import plotly.express as px
from modules.sidebar import render_export_button, render_sidebar
from modules.parser import filter_dataframe

st.set_page_config(page_title="Deep Dive por Regulación", layout="wide")

st.markdown("# 🔍 Ficha Detallada de Regulación (Deep Dive)")
st.markdown("Selecciona una regulación específica mediante filtros en cascada para auditar sus características operativas y de impacto.")

# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

# 2. Filtros globales de barra lateral con claves únicas
sector_col = "Protected Location Id" if "Protected Location Id" in df.columns else df.columns[0]
st.sidebar.markdown("---")
st.sidebar.header("Filtros Globales")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="reg_deep_mode")
sectors = sorted(df[sector_col].dropna().unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="reg_deep_sectors")

df_filtered = filter_dataframe(df, mode, selected_sectors)

# 3. Renderizar el botón de exportación en el sidebar adaptado a esta vista
render_export_button(df_filtered, filename="regulation_deep_dive_report.xlsx")

if df_filtered.empty:
    st.warning("No hay regulaciones disponibles con los filtros seleccionados.")
    st.stop()

# --- FILTROS EN CASCADA EN LA PÁGINA ---
st.markdown("---")
st.markdown("### 🎛️ Selector en Cascada por Sector y Día")

col_f1, col_f2 = st.columns(2)

with col_f1:
    available_sectors_cascade = sorted(df_filtered["Protected Location Id"].dropna().unique()) if "Protected Location Id" in df_filtered.columns else []
    chosen_sector = st.selectbox("1️⃣ Filtrar por Sector:", ["Todos los sectores"] + list(available_sectors_cascade), key="reg_cascade_sector")

if chosen_sector != "Todos los sectores":
    df_step1 = df_filtered[df_filtered["Protected Location Id"] == chosen_sector]
else:
    df_step1 = df_filtered

# --- HISTOGRAMA / DISTRIBUCIÓN POR DÍA DE LA SEMANA ---
if not df_step1.empty and "Day of the Week" in df_step1.columns:
    st.markdown("#### 📊 Prioridad Semanal: Carga de Regulaciones por Día")
    
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    df_grouped = df_step1.groupby("Day of the Week").agg(
        Num_Regulaciones=("Regulation Id", "count"),
        Demora_Total=("ATFM Delay (min)", "sum")
    ).reindex(day_order).reset_index().dropna(subset=["Num_Regulaciones"])

    if not df_grouped.empty:
        fig_days = px.bar(
            df_grouped,
            x="Day of the Week",
            y="Num_Regulaciones",
            text="Num_Regulaciones",
            color="Demora_Total",
            color_continuous_scale="Reds",
            labels={"Day of the Week": "Día de la Semana", "Num_Regulaciones": "Nº de Regulaciones", "Demora_Total": "Demora Total (min)"},
            title=f"Distribución y Criticidad por Día (Sector: {chosen_sector})"
        )
        fig_days.update_traces(textposition="outside")
        fig_days.update_layout(xaxis_categoryorder="array", xaxis_categoryarray=day_order)
        st.plotly_chart(fig_days, use_container_width=True)

with col_f2:
    day_col = "Day of the Week" if "Day of the Week" in df_step1.columns else None
    if day_col:
        available_days = sorted(df_step1[day_col].dropna().unique())
        chosen_day = st.selectbox("2️⃣ Filtrar por Día de la Semana:", ["Todos los días"] + list(available_days), key="reg_cascade_day")
        if chosen_day != "Todos los días":
            df_step2 = df_step1[df_step1[day_col] == chosen_day]
        else:
            df_step2 = df_step1
    else:
        df_step2 = df_step1

if df_step2.empty:
    st.warning("No hay regulaciones que coincidan con la combinación de sector y día seleccionados.")
    st.stop()

# --- SELECTOR ENRIQUECIDO DE REGULACIÓN ---
st.markdown("---")
reg_id_col = "Regulation Id" if "Regulation Id" in df_step2.columns else df_step2.columns[0]

def make_label(row):
    r_id = row.get(reg_id_col, "N/A")
    sec = row.get("Protected Location Id", "N/A")
    date = str(row.get("Regulation Start Date", "N/A"))[:10]
    delay = row.get("ATFM Delay (min)", 0)
    traffic = row.get("Regulated Traffic", 0)
    return f"[{r_id}] — Sector: {sec} | Fecha: {date} | Demora: {delay:,.0f} min | Vuelos: {traffic}"

df_step2 = df_step2.copy()
df_step2["Display_Label"] = df_step2.apply(make_label, axis=1)

if "ATFM Delay (min)" in df_step2.columns:
    df_step2 = df_step2.sort_values(by="ATFM Delay (min)", ascending=False)

selected_label = st.selectbox(
    "🎯 Selecciona la Regulación (ordenadas de mayor a menor impacto):",
    df_step2["Display_Label"].tolist(),
    key="reg_deep_selector"
)

selected_reg_id = selected_label.split("]")[0].replace("[", "")
reg_record = df_step2[df_step2[reg_id_col] == selected_reg_id]

if not reg_record.empty:
    rec = reg_record.iloc[0]

    st.markdown(f"### 📋 Expediente Operativo: `{selected_reg_id}`")

    # --- MÉTRICAS CLAVE DE LA REGULACIÓN ---
    col1, col2, col3, col4 = st.columns(4)
    
    traffic = rec.get("Regulated Traffic", 0)
    delay = rec.get("ATFM Delay (min)", 0)
    duration = rec.get("Regulation Duration (min)", 0)
    avg_delay = rec.get("AVG Delay per Regulated Traffic (min)", 0)

    col1.metric("Tráfico Regulado", f"{traffic:,.0f} vuelos", f"MP: {rec.get('MP Regulated Traffic', 'N/A')}")
    col2.metric("Demora ATFM Total", f"{delay:,.0f} min", f"MP Demorados: {rec.get('MP Delayed Traffic', 'N/A')}")
    col3.metric("Duración", f"{duration} min")
    col4.metric("Demora Media / Vuelo", f"{avg_delay:.1f} min")

    st.markdown("---")

    # --- CRONOLOGÍA VISUAL CON TEXTO INTERNO ---
    st.markdown("### ⏱️ Línea de Tiempo y Ciclo de Vida Operativo")
    
    act_time = rec.get("Regulation Activation Date")
    start_time = rec.get("Regulation Start Time")
    end_time = rec.get("Regulation End Date")
    notice_min = rec.get("Regulation Activation Notice (min)", 0)
    duration_min = rec.get("Regulation Duration (min)", 0)

    if pd.notna(act_time) and pd.notna(start_time) and pd.notna(end_time):
        timeline_data = pd.DataFrame([
            {
                "Hito": "1. Activación (Preaviso)", 
                "Inicio": act_time, 
                "Fin": start_time, 
                "Tipo": "Preaviso",
                "Texto_Barra": f"Preaviso: {notice_min} min"
            },
            {
                "Hito": "2. Ventana de Regulación", 
                "Inicio": start_time, 
                "Fin": end_time, 
                "Tipo": "Regulación Activa",
                "Texto_Barra": f"Duración: {duration_min} min"
            }
        ])

        fig_timeline = px.timeline(
            timeline_data, 
            x_start="Inicio", 
            x_end="Fin", 
            y="Hito", 
            color="Tipo",
            text="Texto_Barra",
            title=f"Cronología de la Medida {selected_reg_id}"
        )
        fig_timeline.update_yaxes(categoryorder="array", categoryarray=["2. Ventana de Regulación", "1. Activación (Preaviso)"])
        fig_timeline.update_traces(textposition="inside", insidetextanchor="middle")
        st.plotly_chart(fig_timeline, use_container_width=True)
    else:
        st.info("No hay suficientes marcas de tiempo continuas para generar la línea de tiempo gráfica.")

    st.markdown("---")

    # --- CARACTERÍSTICAS DETALLADAS EN BLOQUES ---
    c_left, c_right = st.columns(2)

    with c_left:
        st.markdown("#### 🏢 Ubicación y Sectorización")
        st.write(f"**TVS ID (ACC):** {rec.get('TVS Id', 'N/A')}")
        st.write(f"**Sector Regulado (Protected Location):** {rec.get('Protected Location Id', 'N/A')}")
        st.write(f"**Tipo de Localización:** {rec.get('Protected Location Type', 'N/A')}")
        st.write(f"**TV ID (Sector que regula):** {rec.get('TV Id', 'N/A')}")

        st.markdown("#### 📌 Causa y Descripción")
        st.write(f"**Motivo Principal (Reason):** {rec.get('Regulation Reason Name', 'N/A')}")
        desc = rec.get('Regulation Description', 'N/A')
        if pd.isna(desc):
            desc = "Sin descripción adicional"
        st.write(f"**Descripción:** {desc}")

    with c_right:
        st.markdown("#### ⏱️ Dimensiones Temporales y Preaviso")
        st.write(f"**Fecha de Inicio (Start Date):** {str(rec.get('Regulation Start Date', 'N/A'))[:10]}")
        st.write(f"**Hora de Inicio (Start Time):** {str(rec.get('Regulation Start Time', 'N/A'))}")
        st.write(f"**Hora de Fin (End Date):** {str(rec.get('Regulation End Date', 'N/A'))}")
        st.write(f"**Fecha/Hora de Activación:** {rec.get('Regulation Activation Date', 'N/A')}")
        st.write(f"**Tiempo de Preaviso:** {notice_min} minutos")
        st.write(f"**Día de la Semana:** {rec.get('Day of the Week', 'N/A')}")

        st.markdown("#### ❌ Estado y Cancelación")
        cancel_status = rec.get('Regulation Cancel Status', 'Activa / Ejecutada')
        if pd.isna(cancel_status):
            cancel_status = "Activa / Ejecutada (No Cancelada)"
        st.write(f"**Estado de Cancelación:** {cancel_status}")
        st.write(f"**Fecha de Cancelación:** {rec.get('Reg. Cancel Date', 'N/A')}")

    st.markdown("---")
    
    with st.expander("Ver registro completo en formato tabla (Raw Data)"):
        st.dataframe(reg_record, use_container_width=True)

else:
    st.info("No se ha encontrado información para el identificador seleccionado.")