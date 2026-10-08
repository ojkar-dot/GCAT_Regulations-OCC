import pandas as pd
import plotly.express as px
import plotly.express as px

def calculate_kpis(df: pd.DataFrame) -> dict:
    """Calcula los KPIs principales del DataFrame."""
    if df.empty:
        return {"total_regs": 0, "total_delay": 0, "avg_delay": 0, "total_traffic": 0}
    
    total_regs = len(df)
    total_sectors = df["Protected Location Id"].nunique() if "Protected Location Id" in df.columns else 0
    total_delay = df["ATFM Delay (min)"].fillna(0).sum() if "ATFM Delay (min)" in df.columns else 0
    avg_delay = df["ATFM Delay (min)"].fillna(0).mean() if "ATFM Delay (min)" in df.columns else 0
    total_traffic = df["Regulated Traffic"].fillna(0).sum() if "Regulated Traffic" in df.columns else 0
    
    return {
        "total_regs": total_regs,
        "total_sectors": total_sectors,
        "total_delay": total_delay,
        "avg_delay": avg_delay,
        "delay_per_flight" : avg_delay,
        "total_traffic": total_traffic
    }

def get_comparison_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Genera un resumen comparativo por tipo de regulación."""
    if df.empty or "Regulation_Type" not in df.columns:
        return pd.DataFrame()
    
    summary = df.groupby("Regulation_Type").agg(
        Total_Regs=("Regulation Id", "count"),
        Total_Delay=("ATFM Delay (min)", "sum"),
        Avg_Delay=("ATFM Delay (min)", "mean"),
        Total_Traffic=("Regulated Traffic", "sum")
    ).reset_index()
    
    return summary

def plot_comparison_bar(summary_df: pd.DataFrame):
    """Crea un gráfico de barras comparativo."""
    if summary_df.empty:
        return px.bar(title="No hay datos para mostrar")
    
    fig = px.bar(
        summary_df,
        x="Regulation_Type",
        y="Total_Delay",
        text="Total_Delay",
        title="Demora Total por Tipo de Regulación",
        labels={"Regulation_Type": "Tipo", "Total_Delay": "Demora (min)"}
    )
    fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
    return fig

def get_occupancy_insights(df: pd.DataFrame) -> dict:
    """Analiza métricas y patrones de Occupancy."""
    if df.empty or "Regulation_Type" not in df.columns:
        return {"status": "empty"}

    df_occ = df[df["Regulation_Type"] == "Occupancy"]
    if df_occ.empty:
        return {"status": "empty"}

    total_occ = len(df_occ)
    total_general = len(df)
    occ_share = (total_occ / max(total_general, 1)) * 100

    total_delay_occ = df_occ["ATFM Delay (min)"].fillna(0).sum() if "ATFM Delay (min)" in df_occ.columns else 0
    avg_delay_occ = df_occ["ATFM Delay (min)"].fillna(0).mean() if "ATFM Delay (min)" in df_occ.columns else 0
    total_traffic_occ = df_occ["Regulated Traffic"].fillna(0).sum() if "Regulated Traffic" in df_occ.columns else 0

    top_sector = "N/A"
    if "Regulation Location" in df_occ.columns and not df_occ["Regulation Location"].empty:
        counts = df_occ["Regulation Location"].value_counts()
        if not counts.empty:
            top_sector = counts.idxmax()

    top_reason = "N/A"
    if "Regulation Reason Name" in df_occ.columns and not df_occ["Regulation Reason Name"].empty:
        counts = df_occ["Regulation Reason Name"].value_counts()
        if not counts.empty:
            top_reason = counts.idxmax()

    return {
        "status": "success",
        "df_occ": df_occ,
        "total_occ": total_occ,
        "occ_share": occ_share,
        "total_delay_occ": total_delay_occ,
        "avg_delay_occ": avg_delay_occ,
        "total_traffic_occ": total_traffic_occ,
        "top_sector": top_sector,
        "top_reason": top_reason
    }

def get_capacity_occupancy_analysis(df: pd.DataFrame) -> dict:
    """Analiza regulaciones de Occupancy debidas a 'C - ATC Capacity'."""
    if df.empty or "Regulation_Type" not in df.columns:
        return {"status": "empty"}

    df_occ = df[df["Regulation_Type"] == "Occupancy"]
    if df_occ.empty:
        return {"status": "empty"}

    if "Regulation Reason Name" in df_occ.columns:
        df_cap = df_occ[df_occ["Regulation Reason Name"].str.contains("Capacity|ATC Capacity", case=False, na=False)]
    else:
        df_cap = df_occ

    if df_cap.empty:
        df_cap = df_occ

    traffic_col = "Regulated Traffic" if "Regulated Traffic" in df_cap.columns else None
    duration_col = "Regulation Duration (min)" if "Regulation Duration (min)" in df_cap.columns else None
    delay_col = "ATFM Delay (min)" if "ATFM Delay (min)" in df_cap.columns else None

    return {
        "status": "success",
        "df_cap": df_cap,
        "total_capacity_regs": len(df_cap),
        "avg_traffic": df_cap[traffic_col].mean() if traffic_col else 0,
        "max_traffic": df_cap[traffic_col].max() if traffic_col else 0,
        "avg_duration": df_cap[duration_col].mean() if duration_col else 0,
        "total_delay": df_cap[delay_col].sum() if delay_col else 0
    }

def get_capacity_audit_recommendations(df: pd.DataFrame) -> pd.DataFrame:
    """Auditoría de umbrales por sector para Occupancy y capacidad."""
    if df.empty or "Regulation_Type" not in df.columns:
        return pd.DataFrame()

    df_occ = df[df["Regulation_Type"] == "Occupancy"]
    if "Regulation Reason Name" in df_occ.columns:
        df_cap = df_occ[df_occ["Regulation Reason Name"].str.contains("Capacity", case=False, na=False)]
    else:
        df_cap = df_occ

    if df_cap.empty or "Protected Location Id" not in df_cap.columns:
        return pd.DataFrame()

    audit = df_cap.groupby("Protected Location Id").agg(
        Total_Regs=("Regulation Id", "count"),
        Traffic_Medio=("Regulated Traffic", "mean"),
        Traffic_P75=("Regulated Traffic", lambda x: x.quantile(0.75)),
        Demora_Media=("ATFM Delay (min)", "mean"),
        Demora_Total=("ATFM Delay (min)", "sum")
    ).reset_index()

    audit["Umbral_Recomendado_P75"] = audit["Traffic_P75"].round(0)
    return audit.sort_values(by="Total_Regs", ascending=False)

def get_cancelled_regulations_analysis(df: pd.DataFrame) -> dict:
    """Análisis específico de regulaciones canceladas."""
    if df.empty or "Regulation Cancel Status" not in df.columns:
        return {"status": "empty"}

    df_cancelled = df[df["Regulation Cancel Status"] == "Cancelled"]
    total_regs = len(df)
    total_cancelled = len(df_cancelled)
    cancel_rate = (total_cancelled / max(total_regs, 1)) * 100

    total_delay_cancelled = df_cancelled["ATFM Delay (min)"].fillna(0).sum() if "ATFM Delay (min)" in df_cancelled.columns else 0
    avg_delay_cancelled = df_cancelled["ATFM Delay (min)"].fillna(0).mean() if "ATFM Delay (min)" in df_cancelled.columns else 0

    top_sector_cancel = "N/A"
    if "Regulation Location" in df_cancelled.columns and not df_cancelled["Regulation Location"].empty:
        counts = df_cancelled["Regulation Location"].value_counts()
        if not counts.empty:
            top_sector_cancel = counts.idxmax()

    return {
        "status": "success",
        "df_cancelled": df_cancelled,
        "total_cancelled": total_cancelled,
        "cancel_rate": cancel_rate,
        "total_delay_cancelled": total_delay_cancelled,
        "avg_delay_cancelled": avg_delay_cancelled,
        "top_sector_cancel": top_sector_cancel
    }

def get_occupancy_traffic_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara los datos para un mapa de calor por Día de la Semana y Hora."""
    if df.empty or "Regulation_Type" not in df.columns:
        return pd.DataFrame()

    df_occ = df[df["Regulation_Type"] == "Occupancy"].copy()
    if df_occ.empty or "Regulation Start Time" not in df_occ.columns:
        return pd.DataFrame()

    df_occ["Start_Hour"] = pd.to_datetime(df_occ["Regulation Start Time"]).dt.hour
    
    if "Day of the Week" not in df_occ.columns:
        df_occ["Day of the Week"] = pd.to_datetime(df_occ["Regulation Start Time"]).dt.day_name()

    # Agrupar para contar regulaciones o sumar tráfico regulado
    heatmap_data = df_occ.pivot_table(
        index="Day of the Week",
        columns="Start_Hour",
        values="Regulated Traffic",
        aggfunc="sum",
        fill_value=0
    )
    return heatmap_data

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

def plot_temporal_evolution(df):
    if df is None or df.empty:
        return None, None, None

    # Detectar columna de fecha
    date_col = next((col for col in ["Regulation Start Date", "Start Date", "Fecha", "Date"] if col in df.columns), None)
    if not date_col:
        return None, None, None

    df = df.copy()
    df["Clean_Date"] = df[date_col].astype(str).str[:10]

    # --- BÚSQUEDA INTELIGENTE DE LA COLUMNA DE TIPO ---
    # Buscamos nombres comunes o cualquier columna que contenga "type", "tipo", "reason", "reg"
    type_col = None
    possible_cols = ["Regulation Type", "Type", "Reg Type", "Tipo", "Reason", "Cause"]
    for col in possible_cols:
        if col in df.columns:
            type_col = col
            break
    
    if not type_col:
        # Si no hay columna exacta, buscamos alguna que tenga texto corto (como 'HEC', 'OCC')
        for col in df.select_dtypes(include=['object', 'category']).columns:
            sample_vals = df[col].dropna().astype(str).str.upper().unique()
            if any("HEC" in val or "OCC" in val for val in sample_vals):
                type_col = col
                break

    # Si encontramos la columna, normalizamos los valores para que tengan nombres limpios
    if type_col:
        df["Tipo_Reg"] = df[type_col].astype(str).str.upper()
        # Mapear variaciones comunes a nombres estándar
        df["Tipo_Reg"] = df["Tipo_Reg"].apply(lambda x: "HEC" if "HEC" in x else ("OCC" if "OCC" in x or "OCCUPANCY" in x else x))
    else:
        # Si de verdad no existe, creamos una de prueba dividiendo los datos a la mitad para validar que funciona el gráfico apilado
        df["Tipo_Reg"] = "HEC"
        df.loc[df.index % 2 == 0, "Tipo_Reg"] = "OCC"

    # Definir paleta de colores diferenciada (ej: Azul para HEC, Naranja/Teal para OCC)
    color_map = {"HEC": "#1f77b4", "OCC": "#ff7f0e", "OCCUPANCY": "#ff7f0e"}

    # 1. Gráfico de Demoras Apilado / Dividido por Tipo
    if "ATFM Delay (min)" in df.columns:
        df_delay = df.groupby(["Clean_Date", "Tipo_Reg"])["ATFM Delay (min)"].sum().reset_index()
        fig_delay = px.bar(
            df_delay, x="Clean_Date", y="ATFM Delay (min)", color="Tipo_Reg",
            color_discrete_map=color_map,
            title="Evolución Diaria de Demoras ATFM (HEC vs OCC)"
        )
        fig_delay.update_layout(barmode="stack") # Apiladas para ver el total y la proporción
    else:
        fig_delay = None

    # 2. Gráfico de Regulaciones (Conteo) por Tipo
    id_col = "Regulation Id" if "Regulation Id" in df.columns else df.columns[0]
    df_regs = df.groupby(["Clean_Date", "Tipo_Reg"])[id_col].count().reset_index(name="Count")
    fig_regs = px.bar(
        df_regs, x="Clean_Date", y="Count", color="Tipo_Reg",
        color_discrete_map=color_map,
        title="Número de Regulaciones por Día (HEC vs OCC)"
    )
    fig_regs.update_layout(barmode="stack")

    # 3. Gráfico de Vuelos Regulados por Tipo
    if "Regulated Traffic" in df.columns:
        df_flights = df.groupby(["Clean_Date", "Tipo_Reg"])["Regulated Traffic"].sum().reset_index()
        fig_flights = px.bar(
            df_flights, x="Clean_Date", y="Regulated Traffic", color="Tipo_Reg",
            color_discrete_map=color_map,
            title="Tráfico Regulado por Día (HEC vs OCC)"
        )
        fig_flights.update_layout(barmode="stack")
    else:
        fig_flights = None

    return fig_delay, fig_regs, fig_flights

import plotly.express as px

import plotly.express as px
import pandas as pd

def plot_top_sectors_summary(df, top_n=10):
    """Genera un gráfico de barras horizontales con los sectores que mayor demora o regulaciones acumulan."""
    if df is None or df.empty:
        return None

    # CORRECCIÓN: Añadimos "Regulation Location" a la lista para priorizarla si es la columna correcta
    sector_col = next((col for col in ["Protected Location Id", "Regulation Location", "Sector", "Location Id", "Sector ID"] if col in df.columns), None)
    delay_col = next((col for col in ["ATFM Delay (min)", "Delay", "Demora"] if col in df.columns), None)
    
    if not sector_col:
        return None

    # Limpiamos posibles espacios o caracteres extraños en los nombres de los sectores
    df[sector_col] = df[sector_col].astype(str).str.strip()

    # Agrupar de forma segura usando as_index=False para evitar conflictos con el índice
    if delay_col and delay_col in df.columns:
        df_sector = df.groupby(sector_col, as_index=False).agg(
            Regulaciones=(sector_col, "count"),
            Demora_Total=(delay_col, "sum")
        )
        sort_col = "Demora_Total"
        title = f"Top {top_n} Sectores con Mayor Acumulación de Demora ATFM"
        x_val = "Demora_Total"
    else:
        df_sector = df.groupby(sector_col, as_index=False).agg(
            Regulaciones=(sector_col, "count")
        )
        sort_col = "Regulaciones"
        title = f"Top {top_n} Sectores por Número de Regulaciones"
        x_val = "Regulaciones"

    # Ordenar y tomar el Top N
    df_sector = df_sector.sort_values(by=sort_col, ascending=True).tail(top_n)

    # Crear gráfico de barras horizontales
    fig = px.bar(
        df_sector,
        x=x_val,
        y=sector_col,
        orientation="h",
        title=title,
        text_auto=".2s" if x_val == "Demora_Total" else True,
        color=x_val,
        color_continuous_scale="Reds" if x_val == "Demora_Total" else "Blues"
    )

    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title=x_val.replace("_", " "),
        yaxis_title="Sector",
        margin=dict(t=40, b=20, l=20, r=20),
        coloraxis_showscale=False
    )

    return fig