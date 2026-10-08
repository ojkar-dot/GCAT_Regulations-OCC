import streamlit as st
import plotly.express as px
import pandas as pd
from modules.sidebar import render_export_button, render_sidebar
from modules.parser import filter_dataframe
from modules.analytics import (
    get_occupancy_insights, 
    get_capacity_audit_recommendations,
    get_occupancy_traffic_distribution
)

st.set_page_config(page_title="Occupancy Insights & Traffic Patterns", layout="wide")

st.markdown("# 🧠 Patrones, Tráfico y Auditoría de Regulaciones Occupancy")
st.markdown("Análisis avanzado de flujos, distribución horaria, días de la semana y volumen de vuelos regulados en Madrid ACC.")

# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

# 2. Configuración de Filtros en la barra lateral con claves únicas
sector_col = "Regulation Location" if "Regulation Location" in df.columns else df.columns[0]
st.sidebar.markdown("---")
st.sidebar.header("Filtros")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="occ_mode")
sectors = sorted(df[sector_col].dropna().unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="occ_sectors")

df_filtered = filter_dataframe(df, mode, selected_sectors)

# 3. Renderizar el botón de exportación en el sidebar adaptado a esta vista
render_export_button(df_filtered, filename="occupancy_insights_report.xlsx")

insights = get_occupancy_insights(df_filtered)

if insights.get("status") == "success":
    df_occ = insights["df_occ"]

    st.subheader("📌 Indicadores Globales de Occupancy")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Regulaciones", f"{insights['total_occ']:,}", f"{insights['occ_share']:.1f}% del total")
    c2.metric("Demora Total", f"{insights['total_delay_occ']:,.0f} min")
    c3.metric("Demora Media", f"{insights['avg_delay_occ']:.1f} min/reg")
    c4.metric("Tráfico Afectado", f"{insights['total_traffic_occ']:,.0f} vuelos")

    st.markdown("---")

    # --- SECCIÓN DE FILTRO DE SECTOR Y PATRONES TEMPORALES ---
    st.subheader("⏰ Análisis Temporal y Patrones por Sector")
    
    available_sectors = sorted(df_occ["Protected Location Id"].dropna().unique()) if "Protected Location Id" in df_occ.columns else []
    chosen_sector = st.selectbox("🔍 Seleccionar sector específico:", ["Todos los sectores"] + list(available_sectors), key="occ_chosen_sector")

    if chosen_sector != "Todos los sectores":
        df_occ_analysis = df_occ[df_occ["Protected Location Id"] == chosen_sector]
        st.info(f"Mostrando datos filtrados exclusivamente para el sector: **{chosen_sector}**")
    else:
        df_occ_analysis = df_occ

    if "Regulation Start Time" in df_occ_analysis.columns and not df_occ_analysis.empty:
        df_occ_analysis = df_occ_analysis.copy()
        df_occ_analysis["Start_Hour"] = pd.to_datetime(df_occ_analysis["Regulation Start Time"]).dt.hour

        col_t1, col_t2 = st.columns(2)

        with col_t1:
            st.markdown("#### 📊 Distribución por Hora del Día (UTC)")
            hourly_counts = df_occ_analysis["Start_Hour"].value_counts().reset_index()
            hourly_counts.columns = ["Hora", "Regulaciones"]
            hourly_counts = hourly_counts.sort_values("Hora")

            fig_hour = px.bar(
                hourly_counts, x="Hora", y="Regulaciones",
                title="Concentración horaria de regulaciones Occupancy",
                labels={"Hora": "Hora UTC", "Regulaciones": "Número de Regulaciones"}
            )
            st.plotly_chart(fig_hour, use_container_width=True)

        with col_t2:
            st.markdown("#### ⏱️ Distribución de Duración (minutos)")
            if "Regulation Duration (min)" in df_occ_analysis.columns:
                fig_dur = px.box(
                    df_occ_analysis, y="Regulation Duration (min)",
                    title="Dispersión de la Duración de las Regulaciones",
                    labels={"Regulation Duration (min)": "Duración (min)"}
                )
                st.plotly_chart(fig_dur, use_container_width=True)

    st.markdown("---")

    # --- GRÁFICO POTENTE ADICIONAL: MAPA DE CALOR DE TRÁFICO REGULADO (DÍA vs HORA) ---
    st.markdown("### 🗺️ Mapa de Calor: Tráfico Regulado por Día de la Semana y Hora UTC")
    st.markdown("Identifica visualmente los bloques semanales donde mayor volumen de **vuelos regulados** se concentra.")
    
    heatmap_matrix = get_occupancy_traffic_distribution(df_occ_analysis)
    if not heatmap_matrix.empty:
        fig_heat = px.imshow(
            heatmap_matrix,
            labels=dict(x="Hora UTC", y="Día de la Semana", color="Vuelos Regulados"),
            x=heatmap_matrix.columns,
            y=heatmap_matrix.index,
            color_continuous_scale="Reds",
            aspect="auto",
            title="Intensidad de Vuelos Regulados por Franja Semanal"
        )
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("No hay suficientes datos temporales para generar el mapa de calor.")

    st.markdown("---")

    # --- GRÁFICO DE BURBUJAS: TRÁFICO REGULADO VS DEMORA ATFM ---
    st.markdown("### 🫧 Análisis de Impacto: Vuelos Regulados vs Demora ATFM")
    if "Regulated Traffic" in df_occ_analysis.columns and "ATFM Delay (min)" in df_occ_analysis.columns:
        fig_bubble = px.scatter(
            df_occ_analysis,
            x="Regulated Traffic",
            y="ATFM Delay (min)",
            size="Regulation Duration (min)" if "Regulation Duration (min)" in df_occ_analysis.columns else None,
            color="Protected Location Id" if "Protected Location Id" in df_occ_analysis.columns else None,
            hover_name="Regulation Id" if "Regulation Id" in df_occ_analysis.columns else None,
            title="Relación Tráfico Regulado vs Demora (El tamaño de la burbuja indica la duración)",
            labels={"Regulated Traffic": "Vuelos Regulados", "ATFM Delay (min)": "Demora ATFM (min)"}
        )
        st.plotly_chart(fig_bubble, use_container_width=True)

    st.markdown("---")

    # --- AUDITORÍA DE UMBRALES Y RECOMENDACIONES ---
    st.subheader("🛠️ Auditoría de Capacidad y Recomendación de Umbrales")
    audit_df = get_capacity_audit_recommendations(df_filtered)
    if not audit_df.empty:
        st.dataframe(audit_df, use_container_width=True)
    else:
        st.info("No hay suficientes datos de capacidad para generar la auditoría.")

    st.markdown("---")
    st.subheader("📋 Detalle de Registros (Occupancy)")
    st.dataframe(df_occ_analysis, use_container_width=True)
else:
    st.warning("No hay datos de regulaciones de tipo *Occupancy* disponibles con los filtros actuales.")