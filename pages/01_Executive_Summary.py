import streamlit as st
import plotly.express as px
from modules.sidebar import render_export_button, render_methodology_sidebar_button, render_sidebar
from modules.parser import filter_dataframe
from modules.analytics import (
    calculate_kpis, 
    get_comparison_summary, 
    plot_comparison_bar, 
    plot_top_sectors_summary
)
from modules.dss_insights import render_occupancy_dss_insights

st.set_page_config(page_title="Resumen Ejecutivo", layout="wide")

st.markdown("# 📊 Resumen Ejecutivo - GCAT Regulations 2026")

# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

render_occupancy_dss_insights(df)
# 2. Configuración de Filtros en la barra lateral
sector_col = "Regulation Location" if "Regulation Location" in df.columns else df.columns[0]

st.sidebar.markdown("---")
st.sidebar.header("Filtros")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="executive_mode")

sectors = sorted(df[sector_col].dropna().astype(str).unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="executive_sectors")

# 3. Filtrado y cálculo de KPIs
df_filtered = filter_dataframe(df, mode, selected_sectors)
kpis = calculate_kpis(df_filtered)

# 4. Renderizar el botón de exportación en el sidebar adaptado a esta vista filtrada
render_export_button(df_filtered, filename="executive_summary_report.xlsx")

# 5. Visualización de Métricas (KPIs)
render_methodology_sidebar_button()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Regulaciones", f"{kpis['total_regs']:,}")
c2.metric("Sectores", f"{kpis['total_sectors']:,}")
c3.metric("Tráfico Regulado", f"{kpis['total_traffic']:,.0f}")
c4.metric("Demora Total (min)", f"{kpis['total_delay']:,.0f}")
c5.metric("Demora / Vuelo", f"{kpis['delay_per_flight']:.2f}")

st.markdown("---")

# 6. Tabla Resumen y Gráfico Comparativo
st.subheader("Resumen Global vs Desglose HEC / Occupancy")
comparison_df = get_comparison_summary(df_filtered)

if not comparison_df.empty:
    st.dataframe(comparison_df, use_container_width=True)
    fig_compare = plot_comparison_bar(comparison_df)
    st.plotly_chart(fig_compare, use_container_width=True)
else:
    st.warning("No hay datos suficientes para la comparativa.")

st.markdown("---")

# 7. Foco Operativo: Ranking y Concentración por Sector
st.subheader("🎯 Foco Operativo: Ranking y Concentración por Sector")
st.markdown("Identifica rápidamente qué sectores acumulan un mayor impacto en términos de restricciones y demora total para saber dónde poner el foco.")

col_left, col_right = st.columns([1.2, 0.8])

with col_left:
    fig_sectors = plot_top_sectors_summary(df_filtered, top_n=10)
    if fig_sectors:
        st.plotly_chart(fig_sectors, use_container_width=True)
    else:
        st.info("No hay suficientes datos para generar el ranking de sectores.")

with col_right:
    st.markdown("##### 📋 Top Sectores (Resumen)")
    if not df_filtered.empty:
        s_col = "Protected Location Id" if "Protected Location Id" in df_filtered.columns else sector_col
        delay_c = "ATFM Delay (min)" if "ATFM Delay (min)" in df_filtered.columns else None
        
        df_table = df_filtered.groupby(s_col).agg(
            Regulaciones=(s_col, "count"),
            Demora_Total=(delay_c, "sum") if delay_c else (s_col, "count")
        ).reset_index().sort_values(by="Regulaciones", ascending=False).head(8)
        
        st.dataframe(df_table, use_container_width=True, hide_index=True)
    else:
        st.write("Tabla no disponible.")

st.markdown("---")

# 8. Mapa de Dispersión (Scatter Plot) de Sectores (Regulaciones vs Demora Total)
st.markdown("### 🌐 Mapa de Dispersión: Regulaciones vs Demora Total por Sector")
st.markdown("Visualiza la relación directa entre la frecuencia de medidas restrictivas y el impacto acumulado en demora para cada sector.")

if not df_filtered.empty:
    s_col = "Protected Location Id" if "Protected Location Id" in df_filtered.columns else sector_col
    delay_c = "ATFM Delay (min)" if "ATFM Delay (min)" in df_filtered.columns else None
    traffic_c = "Regulated Traffic" if "Regulated Traffic" in df_filtered.columns else None
    
    if s_col and delay_c:
        agg_dict = {
            "Regulaciones": (s_col, "count"),
            "Demora_Total": (delay_c, "sum")
        }
        if traffic_c:
            agg_dict["Tráfico_Afectado"] = (traffic_c, "sum")
            
        df_scatter = df_filtered.groupby(s_col).agg(**agg_dict).reset_index()
        
        fig_scatter = px.scatter(
            df_scatter,
            x="Regulaciones",
            y="Demora_Total",
            size="Tráfico_Afectado" if traffic_c else "Demora_Total",
            color=s_col,
            hover_name=s_col,
            title="Relación entre Frecuencia de Regulaciones y Demora Acumulada por Sector",
            labels={
                "Regulaciones": "Número de Regulaciones",
                "Demora_Total": "Demora Total ATFM (min)",
                "Tráfico_Afectado": "Tráfico Regulado"
            }
        )
        fig_scatter.update_layout(showlegend=False)
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.info("No se encuentran las columnas necesarias para generar el gráfico de dispersión.")
else:
    st.info("No hay datos filtrados disponibles.")