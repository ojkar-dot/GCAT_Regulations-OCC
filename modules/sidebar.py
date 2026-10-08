import streamlit as st
from modules.parser import load_and_parse_data
import pandas as pd
import io
from modules.pdf_generator import generate_comprehensive_pdf

def render_file_uploader_sidebar():
    """
    Renderiza únicamente el cargador de ficheros en el archivo principal (app.py).
    """
    st.sidebar.markdown("---")
    st.sidebar.subheader("Gestión de Fichero NM")
    
    if "df_raw" not in st.session_state:
        uploaded_file = st.sidebar.file_uploader(
            "Seleccione fichero Excel NM",
            type=["xlsx"],
            key="main_file_uploader"  # Key única para app.py
        )
        if uploaded_file is not None:
            with st.spinner("Procesando fichero Excel..."):
                df = load_and_parse_data(uploaded_file)
                st.session_state["df_raw"] = df
                st.session_state["current_file_name"] = uploaded_file.name
                st.rerun()
    else:
        st.sidebar.success(f"📂 {st.session_state.get('current_file_name', 'Fichero cargado')}")
        if st.sidebar.button("🔄 Cambiar Fichero", use_container_width=True):
            del st.session_state["df_raw"]
            if "current_file_name" in st.session_state:
                del st.session_state["current_file_name"]
            st.rerun()


def render_export_button(df_filtered: pd.DataFrame, filename: str = "gcat_reporte_filtrado.xlsx"):
    """
    Renderiza un botón en la barra lateral para exportar a Excel 
    los datos filtrados por los controles globales laterales.
    """
    if df_filtered is not None and not df_filtered.empty:
        st.sidebar.markdown("---")
        st.sidebar.subheader("📤 Exportación de Datos")
        st.sidebar.caption("💡 Se exportarán los registros aplicando los filtros globales de fecha, hora y tipología.")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_filtered.to_excel(writer, index=False, sheet_name='Datos_Filtrados')
        processed_data = output.getvalue()
        
        st.sidebar.download_button(
            label="📥 Exportar Vista Filtrada (XLSX)",
            data=processed_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descarga en Excel los datos filtrados por los controles globales de la barra lateral.",
            use_container_width=True
        )

def render_sidebar() -> pd.DataFrame:
    """
    Renderiza los filtros globales de fecha/hora, exportación a Excel y el informe PDF (DSS)
    en las páginas secundarias (sin volver a invocar el file_uploader).
    """
    # Si ya se cargó en app.py, mostramos indicador visual limpio
    if "current_file_name" in st.session_state:
        st.sidebar.markdown("---")
        st.sidebar.caption(f"📂 Fichero activo: **{st.session_state['current_file_name']}**")

    # Obtener el DataFrame base de la sesión
    df = st.session_state.get("df_raw", pd.DataFrame())

    # --- FILTRO GLOBAL DE PERIODO TEMPORAL Y HORA ---
    if not df.empty:
        date_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ['date', 'fecha', 'start', 'inicio', 'valid']):
                try:
                    pd.to_datetime(df[col])
                    date_col = col
                    break
                except:
                    continue
        
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            valid_dates = df[date_col].dropna().dt.date
            
            if not valid_dates.empty:
                # --- A. FILTRO DE FECHAS ---
                st.sidebar.markdown("---")
                st.sidebar.subheader("📅 Periodo de Análisis")
                
                min_date = valid_dates.min()
                max_date = valid_dates.max()
                
                selected_dates = st.sidebar.date_input(
                    "Rango de fechas",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date,
                    key="global_date_range",
                    help="Filtra el periodo temporal de análisis para todo el cuadro de mando."
                )
                
                if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                    start_date, end_date = selected_dates
                    df = df[(df[date_col].dt.date >= start_date) & (df[date_col].dt.date <= end_date)]

                # --- B. FILTRO DE HORA DEL DÍA ---
                st.sidebar.markdown("---")
                st.sidebar.subheader("⏰ Franja Horaria (UTC)")
                
                selected_hours = st.sidebar.slider(
                    "Seleccione horas",
                    min_value=0,
                    max_value=23,
                    value=(0, 23),
                    key="global_hour_range",
                    help="Filtra las regulaciones según su hora de inicio."
                )
                
                hour_col = date_col
                for col in df.columns:
                    if any(k in col.lower() for k in ['start', 'inicio', 'from', 'valid_from']):
                        try:
                            temp_dt = pd.to_datetime(df[col], errors='coerce')
                            if temp_dt.dt.hour.max() > 0:
                                hour_col = col
                                break
                        except:
                            continue

                df['__hour_temp'] = pd.to_datetime(df[hour_col], errors='coerce').dt.hour
                if df['__hour_temp'].notna().any():
                    df = df[(df['__hour_temp'] >= selected_hours[0]) & (df['__hour_temp'] <= selected_hours[1])]
                
                df = df.drop(columns=['__hour_temp'])

    # --- 1. BOTÓN DE EXPORTACIÓN A EXCEL ---
    render_export_button(df)

    # --- 2. BOTÓN DE INFORME PDF (DSS) ---
    if not df.empty:
        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 Informes y DSS")
        st.sidebar.caption("💡 Genera un informe formal en PDF con las métricas de Occupancy y recomendaciones.")
        
        # Calcular métricas rápidas de Occupancy sobre el DataFrame filtrado
        occ_df = df[df['Regulation_Type'].str.contains('Occupancy', case=False, na=False)] if 'Regulation_Type' in df.columns else pd.DataFrame()
        total_regs = len(df)
        occ_regs = len(occ_df)
        occ_pct = (occ_regs / total_regs * 100) if total_regs > 0 else 0
        
        delay_col = next((c for c in occ_df.columns if any(k in c.lower() for k in ['avg_delay', 'delay', 'demora'])), None)
        avg_delay_occ = occ_df[delay_col].mean() if delay_col and not occ_df.empty else 0.0
        
        pre_cols = [c for c in occ_df.columns if any(k in c.lower() for k in ['preaviso', 'notice', 'lead'])]
        avg_notice_occ = occ_df[pre_cols[0]].mean() if pre_cols and not occ_df.empty else 0.0
        
        metrics_data = {
            "Cuota de Uso (Occupancy)": f"{occ_pct:.1f}% ({occ_regs} de {total_regs} regs)",
            "Demora Media (Occupancy)": f"{avg_delay_occ:.1f} min",
            "Preaviso Medio (Occupancy)": f"{avg_notice_occ:.1f} min"
        }
        
        insights_list = []
        if occ_regs == 0:
            insights_list.append({
                "title": "Sin actividad de Occupancy",
                "text": "El rango de filtros seleccionado no contiene medidas de Occupancy en este periodo."
            })
        else:
            insights_list.append({
                "title": "Resumen Operativo de Occupancy",
                "text": f"Se han auditado {occ_regs} regulaciones de Occupancy con un preaviso medio de {avg_notice_occ:.1f} minutos y una penalización media de {avg_delay_occ:.1f} minutos."
            })
            
        pdf_bytes = generate_comprehensive_pdf(df, insights_list)
        
        st.sidebar.download_button(
            label="📥 Descargar Informe PDF (DSS)",
            data=pdf_bytes,
            file_name="GCAT_Informe_DSS_Occupancy.pdf",
            mime="application/pdf",
            help="Descarga el informe ejecutivo en PDF basado en los filtros globales de la barra lateral.",
            use_container_width=True
        )

    return df




def render_export_button(df_filtered: pd.DataFrame, filename: str = "gcat_reporte_filtrado.xlsx"):
    if df_filtered is not None and not df_filtered.empty:
        st.sidebar.markdown("---")
        st.sidebar.subheader("📤 Exportación")
        
        # Pequeño texto explicativo para dar total transparencia
        st.sidebar.caption("💡 Se exportarán los registros aplicando los filtros de fecha, hora y tipología de la barra lateral.")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_filtered.to_excel(writer, index=False, sheet_name='Datos_Filtrados')
        processed_data = output.getvalue()
        
        st.sidebar.download_button(
            label="📥 Exportar Vista Filtrada (XLSX)",
            data=processed_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descarga en Excel los datos filtrados por los controles globales de la barra lateral."
        )


@st.dialog("📐 Metodología y Fundamentos Técnicos", width="large")
def render_methodology_modal():
    st.markdown("Marco analítico, fuentes de datos y modelos de decisión implementados en el **Decision Support System (DSS)** para ATFCM.")
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📥 1. Ingesta y Procesamiento")
        st.markdown("* **Fuentes Eurocontrol (DDR2):** Ingesta de ficheros normalizados COS/CFG.\n* **Escenarios Dinámicos:** Auditoría de sectorización (*Cell1*).\n* **Limpieza Automatizada:** Python/Pandas para integridad temporal.")
    with col2:
        st.markdown("### 🧠 2. Tipología de Medidas")
        st.markdown("* **HEC:** Mitigación de complejidad geométrica.\n* **Occupancy:** Control de densidad de aeronaves.\n* **Cancelaciones:** Auditoría de medidas anuladas.")
    st.markdown("---")
    st.success("🎯 **Ventaja Operativa:** Transición de análisis estático a entorno interactivo en tiempo real.")


def render_methodology_sidebar_button():
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Presentación")
    if st.sidebar.button("📖 Ver Metodología del Proyecto", use_container_width=True, type="secondary"):
        render_methodology_modal()