import streamlit as st
import plotly.graph_objects as go
from modules.sidebar import render_export_button, render_sidebar
from modules.parser import filter_dataframe
from modules.analytics import plot_temporal_evolution

st.set_page_config(page_title="Análisis Temporal", layout="wide")

st.markdown("# 📈 Evolución Temporal de Regulaciones")

# 1. Recuperar el DataFrame global persistente desde st.session_state
# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

# 2. Configuración de Filtros en la barra lateral
sector_col = "Regulation Location" if "Regulation Location" in df.columns else df.columns[0]

st.sidebar.markdown("---")
st.sidebar.header("Filtros")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="temporal_mode")

sectors = sorted(df[sector_col].dropna().unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="temporal_sectors")

# 3. Filtrado de datos
df_filtered = filter_dataframe(df, mode, selected_sectors)

# 4. Renderizar el botón de exportación en el sidebar adaptado a esta vista temporal
render_export_button(df_filtered, filename="temporal_analysis_report.xlsx")

# 5. Generación de gráficos temporales
fig_delay, fig_regs, fig_flights = plot_temporal_evolution(df_filtered)

# Validar que sea una figura válida de Plotly antes de pintar
if isinstance(fig_delay, go.Figure):
    st.plotly_chart(fig_delay, use_container_width=True)
else:
    st.info("No hay datos suficientes para generar el gráfico de demora con los filtros actuales.")

# Crear columnas para los otros dos gráficos
col1, col2 = st.columns(2)

with col1:
    if isinstance(fig_regs, go.Figure):
        st.plotly_chart(fig_regs, use_container_width=True)
    else:
        st.info("Sin datos de regulaciones.")

with col2:
    if isinstance(fig_flights, go.Figure):
        st.plotly_chart(fig_flights, use_container_width=True)
    else:
        st.info("Sin datos de vuelos.")