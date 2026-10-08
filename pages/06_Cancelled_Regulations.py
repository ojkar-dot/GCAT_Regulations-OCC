import streamlit as st
import plotly.express as px
from modules.sidebar import render_export_button, render_sidebar
from modules.parser import filter_dataframe
from modules.analytics import get_cancelled_regulations_analysis

st.set_page_config(page_title="Regulaciones Canceladas", layout="wide")

st.markdown("# ❌ Análisis de Regulaciones Canceladas")
st.markdown("Auditoría cuantitativa, temporal y de repercusión operativa de los eventos que finalmente fueron cancelados.")

# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

# 2. Filtros de barra lateral con claves únicas
sector_col = "Regulation Location" if "Regulation Location" in df.columns else df.columns[0]
st.sidebar.markdown("---")
st.sidebar.header("Filtros")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="canc_mode")
sectors = sorted(df[sector_col].dropna().unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="canc_sectors")

df_filtered = filter_dataframe(df, mode, selected_sectors)

# 3. Renderizar el botón de exportación en el sidebar adaptado a esta vista
render_export_button(df_filtered, filename="cancelled_regulations_report.xlsx")

analysis = get_cancelled_regulations_analysis(df_filtered)

if analysis.get("status") == "success":
    df_canc = analysis["df_cancelled"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Regulaciones Canceladas", f"{analysis['total_cancelled']:,}", f"{analysis['cancel_rate']:.1f}% del filtro")
    c2.metric("Demora Acumulada Previa", f"{analysis['total_delay_cancelled']:,.0f} min")
    c3.metric("Demora Media por Cancelada", f"{analysis['avg_delay_cancelled']:.1f} min")
    c4.metric("Sector con más Anulaciones", analysis['top_sector_cancel'])

    st.markdown("---")
    st.subheader("💡 Repercusión Operativa")
    st.info("""
    > Un alto volumen de cancelaciones suele indicar correcciones tácticas tardías o cambios rápidos en la demanda/meteorología. 
    > Analizar la demora acumulada antes de la cancelación ayuda a auditar si las medidas preventivas se activaron con demasiada antelación o rigidez.
    """)

    # Gráfico de distribución de cancelaciones por sector
    if not df_canc.empty and "Regulation Location" in df_canc.columns:
        fig_canc = px.bar(
            df_canc["Regulation Location"].value_counts().reset_index(),
            x="count",
            y="Regulation Location",
            orientation="h",
            title="Volumen de Cancelaciones por Sector",
            labels={"count": "Número de Cancelaciones", "Regulation Location": "Sector"}
        )
        fig_canc.update_layout(yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig_canc, use_container_width=True)

    st.markdown("---")

    # --- NUEVO GRÁFICO COMPLEMENTARIO ---
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### ⏳ Distribución del Preaviso en Regulaciones Canceladas")
        if "Regulation Activation Notice (min)" in df_canc.columns and not df_canc.empty:
            fig_notice = px.box(
                df_canc,
                y="Regulation Activation Notice (min)",
                title="Dispersión del Tiempo de Preaviso (min) antes de Cancelar",
                labels={"Regulation Activation Notice (min)": "Minutos de Preaviso"}
            )
            st.plotly_chart(fig_notice, use_container_width=True)
        else:
            st.info("No hay datos suficientes de preaviso.")

    with col_g2:
        st.markdown("#### 📅 Cancelaciones por Día de la Semana")
        if "Day of the Week" in df_canc.columns and not df_canc.empty:
            day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            df_days_canc = df_canc["Day of the Week"].value_counts().reindex(day_order).reset_index()
            df_days_canc.columns = ["Día", "Cancelaciones"]
            
            fig_days = px.bar(
                df_days_canc,
                x="Día",
                y="Cancelaciones",
                text="Cancelaciones",
                title="Volumen de Cancelaciones por Día de la Semana",
                color="Cancelaciones",
                color_continuous_scale="Reds"
            )
            fig_days.update_traces(textposition="outside")
            st.plotly_chart(fig_days, use_container_width=True)
        else:
            st.info("No hay datos suficientes de días de la semana.")
    st.subheader("📋 Detalle de Registros Cancelados")
    st.dataframe(df_canc, use_container_width=True)
else:
    st.warning("No hay datos disponibles para el análisis de cancelaciones con los filtros actuales.")