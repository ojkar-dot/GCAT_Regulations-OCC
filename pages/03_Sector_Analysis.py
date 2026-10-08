import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from modules.sidebar import render_export_button, render_sidebar
from modules.parser import filter_dataframe

st.set_page_config(page_title="Deep Dive por Sector", layout="wide")

st.markdown("# 🏢 Análisis Profundo por Sector (Sector Deep Dive)")
st.markdown("Audita el comportamiento operativo, las causas de regulación, los tiempos de preaviso y la duración típica de cualquier sector del ACC.")

# 1. Recuperar el DataFrame global persistente desde st.session_state
# ✅ CÓMO DEBE QUEDAR (esto ejecuta el sidebar, aplica fechas/horas y te da el df filtrado)
df = render_sidebar()

if df.empty:
    st.info("Por favor, suba un fichero Excel en la barra lateral para comenzar.")
    st.stop()

# 2. Filtros globales de barra lateral
sector_col = "Protected Location Id" if "Protected Location Id" in df.columns else df.columns[0]
st.sidebar.markdown("---")
st.sidebar.header("Filtros Globales")
mode = st.sidebar.radio("Tipo regulación", ["Todas", "HEC", "Occupancy"], key="sector_mode")
sectors = sorted(df[sector_col].dropna().unique()) if sector_col in df.columns else []
selected_sectors = st.sidebar.multiselect("Sectores", sectors, default=sectors, key="sector_sectors")

df_filtered = filter_dataframe(df, mode, selected_sectors)

# 3. Renderizar el botón de exportación en el sidebar adaptado a esta vista de sectores
render_export_button(df_filtered, filename="sector_analysis_report.xlsx")

if df_filtered.empty:
    st.warning("No hay regulaciones disponibles con los filtros seleccionados.")
    st.stop()

# --- SECCIÓN: VISIÓN COMPARATIVA GLOBAL DE SECTORES ---
st.markdown("---")
st.markdown(f"### 📊 Visión Comparativa Global de Sectores (Filtro: *{mode}*)")

# Pestañas o selector para alternar entre el gráfico de barras y el scatter plot
viz_mode = st.radio(
    "Selecciona el tipo de visualización comparativa:",
    ["Gráfico de Barras por Métrica", "Scatter Plot (Regulaciones vs Demora & Tráfico)"],
    horizontal=True,
    key="sector_viz_mode"
)

if viz_mode == "Gráfico de Barras por Métrica":
    delay_col = "ATFM Delay (min)" if "ATFM Delay (min)" in df_filtered.columns else None

    agg_dict = {sector_col: 'count'}
    if delay_col:
        agg_dict[delay_col] = 'sum'

    df_comparison = df_filtered.groupby(sector_col).agg(agg_dict).rename(
        columns={sector_col: "Num_Regulaciones", delay_col: "Total_Demora"} if delay_col else {sector_col: "Num_Regulaciones"}
    ).reset_index()

    metric_choice = st.radio(
        "Métrica de barras:",
        ["Número de Regulaciones", "Minutos Totales de Demora (ATFM Delay)"],
        horizontal=True,
        key="sector_metric_choice"
    )

    if metric_choice == "Número de Regulaciones":
        fig_comp = px.bar(
            df_comparison.sort_values(by="Num_Regulaciones", ascending=False),
            x=sector_col,
            y="Num_Regulaciones",
            text="Num_Regulaciones",
            title=f"Comparativa de Sectores: Número de Regulaciones ({mode})",
            labels={sector_col: "Sector", "Num_Regulaciones": "Número de Regulaciones"}
        )
        fig_comp.update_traces(textposition="outside")
        st.plotly_chart(fig_comp, use_container_width=True)
    else:
        if delay_col:
            fig_comp = px.bar(
                df_comparison.sort_values(by="Total_Demora", ascending=False),
                x=sector_col,
                y="Total_Demora",
                text="Total_Demora",
                title=f"Comparativa de Sectores: Minutos Totales de Demora ({mode})",
                labels={sector_col: "Sector", "Total_Demora": "Demora Total (min)"}
            )
            fig_comp.update_traces(texttemplate='%{text:,.0f}', textposition="outside")
            st.plotly_chart(fig_comp, use_container_width=True)
        else:
            st.info("La columna de demora ('ATFM Delay (min)') no está disponible.")

else:
    # --- SCATTER PLOT: REGULACIONES VS DEMORA CON TAMAÑO DE BURBUJA ---
    if "ATFM Delay (min)" in df_filtered.columns:
        df_scatter = df_filtered.groupby(sector_col).agg(
            Num_Regulaciones=(sector_col, 'count'),
            Demora_Media=("ATFM Delay (min)", 'mean'),
            Demora_Total=("ATFM Delay (min)", 'sum'),
            Trafico_Total=("Regulated Traffic", 'sum') if "Regulated Traffic" in df_filtered.columns else (sector_col, lambda x: 1)
        ).reset_index()

        df_scatter["Trafico_Total"] = df_scatter["Trafico_Total"].fillna(1)

        fig_scatter = px.scatter(
            df_scatter,
            x="Num_Regulaciones",
            y="Demora_Media",
            size="Trafico_Total",
            color=sector_col,
            hover_name=sector_col,
            title=f"Mapa Operativo ({mode}): Regulaciones vs Demora Media (Tamaño = Tráfico Regulado)",
            labels={
                "Num_Regulaciones": "Número de Regulaciones",
                "Demora_Media": "Demora Media por Regulación (min)",
                "Trafico_Total": "Tráfico Regulado Total"
            }
        )
        fig_scatter.update_layout(showlegend=False)
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption(f"💡 *Nota (Filtro: {mode}): El eje X muestra cuántas regulaciones sufre el sector, el eje Y la demora media, y el tamaño el volumen de tráfico.*")
    else:
        st.info("No se dispone de la columna de demora para generar el gráfico de dispersión.")


# --- SELECTOR DE SECTOR ESPECÍFICO ---
st.markdown("---")
available_sectors = sorted(df_filtered[sector_col].dropna().unique())
chosen_sector = st.selectbox("🎯 Selecciona el Sector a Auditar individualmente:", available_sectors, key="chosen_sector_deep_dive")

# Filtrar para el sector seleccionado
df_sector = df_filtered[df_filtered[sector_col] == chosen_sector]

if not df_sector.empty:
    st.markdown(f"### 📊 Radiografía Operativa del Sector: `{chosen_sector}` *(Tipo de Regulación: {mode})*")

    # --- MÉTRICAS CLAVE DEL SECTOR + DESGLOSE HEC / OCC SI "TODAS" ---
    col1, col2, col3, col4 = st.columns(4)
    
    total_regs = len(df_sector)
    total_delay = df_sector["ATFM Delay (min)"].sum() if "ATFM Delay (min)" in df_sector.columns else 0
    total_traffic = df_sector["Regulated Traffic"].sum() if "Regulated Traffic" in df_sector.columns else 0
    avg_delay_reg = df_sector["ATFM Delay (min)"].mean() if "ATFM Delay (min)" in df_sector.columns else 0

    col1.metric("Total Regulaciones", f"{total_regs} medidas")
    
    # Si el modo es "Todas", buscamos en todo el DataFrame del sector qué columnas contienen "HEC" u "OCC"
    if mode == "Todas":
        hec_count = 0
        occ_count = 0
        
        for col in df_sector.columns:
            vals = df_sector[col].astype(str)
            h = vals.str.contains("HEC", case=False, na=False).sum()
            o = vals.str.contains("OCC|Occupancy", case=False, na=False).sum()
            if h > 0 or o > 0:
                hec_count = max(hec_count, h)
                occ_count = max(occ_count, o)
        
        if hec_count > 0 or occ_count > 0:
            col1.caption(f"🔍 Desglose: **{hec_count} HEC** | **{occ_count} OCC**")
        else:
            col1.caption("🔍 Desglose: No clasificado como HEC/OCC en columnas")

    col2.metric("Demora ATFM Acumulada", f"{total_delay:,.0f} min")
    col3.metric("Tráfico Total Regulado", f"{total_traffic:,.0f} vuelos")
    col4.metric("Demora Media / Medida", f"{avg_delay_reg:.1f} min")

    st.markdown("---")
    st.markdown("### 📈 Relación Operativa: Tráfico Regulado, MP Traffic vs. Demora ATFM")
    st.markdown("Análisis de correlación para evaluar el impacto real del volumen de tráfico afectado frente a la demora generada en el sector seleccionado.")

    # Verificamos que las columnas necesarias existan en el DataFrame filtrado del sector
    req_cols = ["Regulated Traffic", "ATFM Delay (min)"]
    if all(col in df_sector.columns for col in req_cols) and not df_sector.empty:
        
        # Preparar columna opcional MP Regulated Traffic si existe
        mp_traffic_col = "MP Regulated Traffic" if "MP Regulated Traffic" in df_sector.columns else None
        duration_col = "Regulation Duration (min)" if "Regulation Duration (min)" in df_sector.columns else None

        fig_traffic_delay = px.scatter(
            df_sector,
            x="Regulated Traffic",
            y="ATFM Delay (min)",
            color=mp_traffic_col if mp_traffic_col else None,
            size=duration_col if duration_col else None,
            hover_data=[c for c in ["Regulation Id", "Regulation Reason Name", "Day of the Week"] if c in df_sector.columns],
            color_continuous_scale="Viridis",
            labels={
                "Regulated Traffic": "Tráfico Regulado Total (Vuelos)",
                "ATFM Delay (min)": "Demora ATFM Total (min)",
                "MP Regulated Traffic": "Tráfico MP (Sector Crítico)"
            },
            title=f"Impacto de Tráfico vs. Demora en el Sector: {chosen_sector}"  # <-- Corregido aquí
        )
        
        fig_traffic_delay.update_layout(
            xaxis_title="Tráfico Regulado Total (Vuelos)",
            yaxis_title="Demora ATFM Total (min)",
            legend_title="Métrica MP"
        )
        
        st.plotly_chart(fig_traffic_delay, use_container_width=True)
    else:
        st.info("No hay suficientes datos numéricos de tráfico o demora para generar este gráfico en el sector seleccionado.")
    
    
    st.markdown("---")

    # --- ESTADÍSTICOS DE PREAVISO Y DURACIÓN (CON GRÁFICOS GAUGE) ---
    st.markdown("#### ⏱️ Estadísticos y Tiempos Gráficos (Preaviso y Duración)")
    
    notice_col = "Regulation Activation Notice (min)"
    duration_col = "Regulation Duration (min)"
    
    stat_col1, stat_col2 = st.columns(2)
    
    with stat_col1:
        st.markdown("**🔔 Tiempo de Preaviso (min)**")
        if notice_col in df_sector.columns:
            n_series = df_sector[notice_col].dropna()
            if not n_series.empty:
                mean_n = n_series.mean()
                max_n = n_series.max()
                
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Media", f"{mean_n:.1f} m")
                s2.metric("Mediana", f"{n_series.median():.1f} m")
                s3.metric("Mínimo", f"{n_series.min():.0f} m")
                s4.metric("Máximo", f"{max_n:.0f} m")
                
                # Gráfico Gauge para Preaviso
                fig_gauge_notice = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = mean_n,
                    title = {"text": "Media de Preaviso (min)"},
                    gauge = {
                        'axis': {'range': [0, max(max_n, 100)]},
                        'bar': {'color': "darkblue"},
                        'steps': [
                            {'range': [0, max_n * 0.33], 'color': "lightcyan"},
                            {'range': [max_n * 0.33, max_n * 0.66], 'color': "royalblue"}
                        ],
                    }
                ))
                fig_gauge_notice.update_layout(height=220, margin=dict(l=20, r=20, t=30, b=10))
                st.plotly_chart(fig_gauge_notice, use_container_width=True)
            else:
                st.info("Sin datos de preaviso.")
        else:
            st.info("Columna no encontrada.")

    with stat_col2:
        st.markdown("**⏳ Duración de la Regulación (min)**")
        if duration_col in df_sector.columns:
            d_series = df_sector[duration_col].dropna()
            if not d_series.empty:
                mean_d = d_series.mean()
                max_d = d_series.max()
                
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Media", f"{mean_d:.1f} m")
                d2.metric("Mediana", f"{d_series.median():.1f} m")
                d3.metric("Mínimo", f"{d_series.min():.0f} m")
                d4.metric("Máximo", f"{max_d:.0f} m")
                
                # Gráfico Gauge para Duración
                fig_gauge_duration = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = mean_d,
                    title = {"text": "Media de Duración (min)"},
                    gauge = {
                        'axis': {'range': [0, max(max_d, 200)]},
                        'bar': {'color': "darkorange"},
                        'steps': [
                            {'range': [0, max_d * 0.33], 'color': "papayawhip"},
                            {'range': [max_d * 0.33, max_d * 0.66], 'color': "moccasin"}
                        ],
                    }
                ))
                fig_gauge_duration.update_layout(height=220, margin=dict(l=20, r=20, t=30, b=10))
                st.plotly_chart(fig_gauge_duration, use_container_width=True)
            else:
                st.info("Sin datos de duración.")
        else:
            st.info("Columna no encontrada.")

    st.markdown("---")

    # --- DISTRIBUCIÓN POR MOTIVOS Y DÍAS ---
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### 📌 Distribución por Motivo (Reason)")
        if "Regulation Reason Name" in df_sector.columns:
            reason_df = df_sector["Regulation Reason Name"].value_counts().reset_index()
            reason_df.columns = ["Motivo", "Cantidad"]
            fig_reason = px.pie(reason_df, names="Motivo", values="Cantidad", hole=0.4, title=f"Causas de Regulación en {chosen_sector} ({mode})")
            st.plotly_chart(fig_reason, use_container_width=True)
        else:
            st.info("No hay información de motivos disponible.")

    with col_g2:
        st.markdown("#### 📅 Regulaciones por Día de la Semana")
        if "Day of the Week" in df_sector.columns:
            day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_df = df_sector.groupby("Day of the Week").size().reindex(day_order).reset_index(name="Cantidad").dropna(subset=["Cantidad"])
            fig_days = px.bar(day_df, x="Day of the Week", y="Cantidad", text="Cantidad", title=f"Frecuencia Semanal en {chosen_sector} ({mode})")
            fig_days.update_traces(textposition="outside")
            st.plotly_chart(fig_days, use_container_width=True)
        else:
            st.info("No hay información del día de la semana disponible.")

    st.markdown("---")
    import plotly.express as px
    import pandas as pd
    import streamlit as st

    st.markdown("### ⏰ Distribución Horaria y Estadísticas de Regulaciones")
    st.markdown("Pasa el cursor sobre cada barra para consultar el desglose estadístico detallado de la franja.")

    if not df_sector.empty:
        # 1. Detectar columna de fecha/inicio
        date_col = None
        for col in df_sector.columns:
            if any(k in col.lower() for k in ['start', 'inicio', 'from', 'valid_from', 'date', 'fecha']):
                try:
                    pd.to_datetime(df_sector[col])
                    date_col = col
                    break
                except:
                    continue
                    
        # 2. Detectar métrica numérica (ej. Duración o Demora)
        metric_col = None
        for m in ['duration', 'duracion', 'delay', 'demora', 'atfm delay']:
            matches = [c for c in df_sector.columns if m in c.lower()]
            if matches:
                metric_col = matches[0]
                break

        if date_col:
            # Extraer hora
            df_sector['__hora_inicio'] = pd.to_datetime(df_sector[date_col], errors='coerce').dt.hour
            
            # Si tenemos métrica numérica, calculamos estadísticos por hora; si no, solo contendremos conteos
            if metric_col:
                df_grouped = df_sector.groupby('__hora_inicio').agg(
                    Cantidad=('__hora_inicio', 'size'),
                    Media=(metric_col, 'mean'),
                    Mediana=(metric_col, 'median'),
                    Minimo=(metric_col, 'min'),
                    Maximo=(metric_col, 'max')
                ).reset_index()
            else:
                df_grouped = df_sector.groupby('__hora_inicio').size().reset_index(name='Cantidad')
                df_grouped['Media'] = 0
                df_grouped['Mediana'] = 0
                df_grouped['Minimo'] = 0
                df_grouped['Maximo'] = 0

            # Rellenar las 24 horas del día (0 a 23) para que el eje X esté completo
            all_hours = pd.DataFrame({'__hora_inicio': range(24)})
            df_grouped = pd.merge(all_hours, df_grouped, on='__hora_inicio', how='left').fillna(0)
            df_grouped['Hora_Str'] = df_grouped['__hora_inicio'].apply(lambda h: f"{int(h):02d}:00")

            # Crear el gráfico con Plotly
            fig_hours = px.bar(
                df_grouped,
                x='Hora_Str',
                y='Cantidad',
                title="Frecuencia y Estadísticos por Hora de Inicio",
                labels={'Hora_Str': 'Hora UTC (Inicio)', 'Cantidad': 'Número de Regulaciones'},
                color='Cantidad',
                color_continuous_scale='Blues',
                custom_data=['Cantidad', 'Media', 'Mediana', 'Minimo', 'Maximo']
            )
            
            # Personalizar el Tooltip flotante con formato limpio
            metric_label = metric_col if metric_col else "Métrica"
            fig_hours.update_traces(
                hovertemplate=(
                    "<b>Hora UTC: %{x}</b><br>" +
                    "──────────────────────────<br>" +
                    "📌 Regulaciones: <b>%{customdata[0]}</b><br>" +
                    f"📊 Mediana ({metric_label}): <b>%{{customdata[2]:.1f}} min</b><br>" +
                    f"📈 Media ({metric_label}): <b>%{{customdata[1]:.1f}} min</b><br>" +
                    f"📉 Mín / Máx: <b>%{{customdata[3]:.0f}} / %{{customdata[4]:.0f}} min</b>" +
                    "<extra></extra>"
                )
            )
            
            fig_hours.update_layout(
                xaxis_title="Hora UTC",
                yaxis_title="Cantidad de Regulaciones",
                coloraxis_showscale=False,
                plot_bgcolor='rgba(0,0,0,0)',
                hovermode='x unified'
            )
            
            st.plotly_chart(fig_hours, use_container_width=True)
        else:
            st.info("No se ha encontrado una columna temporal de inicio válida.")
    else:
        st.info("No hay datos disponibles para el sector seleccionado.")
    # --- TABLA DETALLADA DE REGULACIONES DEL SECTOR ---
    with st.expander(f"Ver todas las regulaciones aplicadas a {chosen_sector} ({mode}) (Tabla Completa)"):
        st.dataframe(df_sector, use_container_width=True)

else:
    st.info("Seleccione un sector válido para ver su análisis profundo.")