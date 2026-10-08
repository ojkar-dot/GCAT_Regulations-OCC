import streamlit as st
from modules.sidebar import render_file_uploader_sidebar

# Configuración inicial de la página
st.set_page_config(
    page_title="GCAT Regulations 2026",
    page_icon="✈️",
    layout="wide"
)

# 1. CARGA ÚNICA GLOBAL: El sidebar se ejecuta aquí una sola vez
df_global = render_file_uploader_sidebar()

# 2. Definición de la navegación multipágina
pg = st.navigation([
    st.Page("pages/01_Executive_Summary.py", title="Executive Summary", icon="📊"),
    st.Page("pages/02_Temporal_Analysis.py", title="Temporal Analysis", icon="📈"),
    st.Page("pages/03_Sector_Analysis.py", title="Sector Analysis", icon="🗺️"),
    st.Page("pages/04_Regulation_Deep_Dive.py", title="Regulation Deep Dive", icon="🔍"),
    st.Page("pages/05_Occupancy_Insights.py", title="Occupancy Insights", icon="💡"),
    st.Page("pages/06_Cancelled_Regulations.py", title="Cancelled Regulations", icon="❌"),
])

# 3. Ejecutar la página seleccionada
pg.run()