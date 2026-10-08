import pandas as pd
import streamlit as st

def render_occupancy_dss_insights(df: pd.DataFrame):
    """
    Analiza el DataFrame filtrado y genera recomendaciones automáticas 
    para las FMPs basadas en el uso de Occupancy frente a HEC.
    """
    if df.empty:
        return

    st.markdown("### 🧠 DSS: Asistente de Decisiones y Recomendaciones Operativas")
    st.markdown("Evaluación inteligente del impacto de las medidas de *Occupancy* frente a la normativa tradicional.")

    # 1. Filtrar métricas de Occupancy de forma estricta
    occ_df = df[df['Regulation_Type'].str.contains('Occupancy', case=False, na=False)] if 'Regulation_Type' in df.columns else pd.DataFrame()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_regs = len(df)
        occ_regs = len(occ_df)
        occ_pct = (occ_regs / total_regs * 100) if total_regs > 0 else 0
        st.metric("Cuota de Uso (Occupancy)", f"{occ_pct:.1f}%", f"{occ_regs} de {total_regs} regulaciones")

    with col2:
        # Búsqueda robusta de la columna de demora para Occupancy
        delay_col = None
        for c in occ_df.columns:
            if any(k in c.lower() for k in ['avg_delay', 'delay', 'demora', 'average']):
                delay_col = c
                break
        
        avg_delay_occ = occ_df[delay_col].mean() if delay_col and not occ_df.empty else 0.0
        st.metric("Demora Media (Occupancy)", f"{avg_delay_occ:.1f} min", "Impacto operativo medio")

    with col3:
        # Búsqueda robusta de preaviso FILTRADO EXCLUSIVAMENTE por Occupancy
        pre_cols = [c for c in occ_df.columns if any(k in c.lower() for k in ['preaviso', 'notice', 'lead', 'anticipacion'])]
        avg_notice_occ = occ_df[pre_cols[0]].mean() if pre_cols and not occ_df.empty else 0.0
        st.metric("Preaviso Medio (Occupancy)", f"{avg_notice_occ:.1f} min", "Antelación táctica (OCC)")

    st.markdown("#### 🚨 Recomendaciones Automáticas para FMPs")

    # 2. Motor de reglas heurísticas para generar alertas operativas
    insights = []

    # Si no hay regulaciones de Occupancy en este filtro, indicarlo claramente en las recomendaciones
    if occ_regs == 0:
        insights.append({
            "type": "info",
            "title": "Sin actividad de Occupancy en el periodo",
            "text": "El rango de fechas o filtros seleccionados no contiene medidas de *Occupancy*. Todas las regulaciones registradas corresponden a tipología tradicional (HEC)."
        })
    else:
        # Regla A: Dependencia excesiva de última hora en Occupancy
        if pre_cols and not occ_df.empty:
            short_notice_count = len(occ_df[occ_df[pre_cols[0]] < 30])
            if (short_notice_count / occ_regs) > 0.3:
                insights.append({
                    "type": "warning",
                    "title": "Alta dependencia táctica de última hora en Occupancy",
                    "text": f"El **{(short_notice_count/occ_regs)*100:.1f}%** de las regulaciones por Occupancy se emiten con menos de 30 minutos de preaviso. **Recomendación:** Revisar la pre-planificación."
                })

        # Regla B: Comparativa de Occupancy por Sector
        sector_col = 'Protected Location Id' if 'Protected Location Id' in occ_df.columns else next((c for c in occ_df.colors if 'sector' in c.lower() or 'location' in c.lower()), None)
        if sector_col:
            sector_counts = occ_df[sector_col].value_counts()
            if not sector_counts.empty:
                top_sector = sector_counts.idxmax()
                top_count = sector_counts.iloc[0]
                insights.append({
                    "type": "info",
                    "title": f"Concentración de Occupancy en Sector ({top_sector})",
                    "text": f"El sector **{top_sector}** concentra el mayor volumen de uso de *Occupancy* ({top_count} medidas)."
                })

    if not insights:
        insights.append({
            "type": "success",
            "title": "Comportamiento Estándar",
            "text": "Los indicadores se encuentran dentro de los parámetros previstos."
        })

    # Renderizar tarjetas
    for ins in insights:
        if ins["type"] == "warning":
            st.warning(f"**{ins['title']}**: {ins['text']}")
        elif ins["type"] == "info":
            st.info(f"**{ins['title']}**: {ins['text']}")
        else:
            st.success(f"**{ins['title']}**: {ins['text']}")