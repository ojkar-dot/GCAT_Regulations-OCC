import streamlit as st
import pandas as pd
import numpy as np

@st.cache_data
def load_and_parse_data(uploaded_file) -> pd.DataFrame:
    try:
        df = pd.read_excel(
            uploaded_file,
            sheet_name="Sheet1",
            header=0
        )
    except Exception as e:
        st.error(f"Error al leer el archivo Excel: {e}")
        return pd.DataFrame()

    # Limpieza de nombres de columnas
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
    )

    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")

    # 1. Mapeo de la columna de ubicación exacta ("Protected Location Id")
    if "Protected Location Id" in df.columns:
        loc_data = df["Protected Location Id"]
        if isinstance(loc_data, pd.DataFrame):
            loc_data = loc_data.iloc[:, 0]
        df["Regulation Location"] = loc_data

    # 2. Identificación inteligente de la columna de ID de Regulación (la que contiene códigos como OLEMN28I, etc.)
    reg_id_col = None
    for col in df.columns:
        sample_vals = df[col].dropna().astype(str)
        # Buscamos columnas cuyos valores parezcan códigos de regulación (ej. empiezan por O o T, o tienen longitud típica)
        if any(v.upper().startswith("O") or v.upper().startswith("T") for v in sample_vals):
            reg_id_col = col
            break
            
    if not reg_id_col:
        # Fallback a la primera columna si no encuentra patrón
        reg_id_col = df.columns[0]

    reg_val = df[reg_id_col]
    if isinstance(reg_val, pd.DataFrame):
        reg_val = reg_val.iloc[:, 0]
    df["Regulation"] = reg_val

    # 3. Regla de clasificación: si empieza por 'o' / 'O' -> Occupancy, resto -> HEC
    df["Regulation_Type"] = np.where(
        reg_val.astype(str).str.strip().str.upper().str.startswith("O"),
        "Occupancy",
        "HEC"
    )

    # 4. Conversión segura de columnas numéricas
    numeric_cols = [
        "Regulation Activation Notice (min)",
        "Regulation Duration (min)",
        "MP Regulated Traffic",
        "Regulated Traffic",
        "ATFM Delay (min)",
        "MP Delayed Traffic",
        "AVG Delay per Regulated Traffic (min)"
    ]

    for col in numeric_cols:
        if col not in df.columns:
            continue
        
        val_series = df[col]
        if isinstance(val_series, pd.DataFrame):
            val_series = val_series.iloc[:, 0]

        s = val_series.astype(str)
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        df[col] = pd.to_numeric(s, errors="coerce")

    # 5. Conversión de fecha usando 'Regulation Activation Date' o 'Regulation Start Time'
    date_col = "Regulation Activation Date" if "Regulation Activation Date" in df.columns else None
    if not date_col and "Regulation Start Time" in df.columns:
        date_col = "Regulation Start Time"

    if date_col:
        date_data = df[date_col]
        if isinstance(date_data, pd.DataFrame):
            date_data = date_data.iloc[:, 0]
        df["Regulation Start Date"] = pd.to_datetime(
            date_data,
            errors="coerce"
        )
    else:
        df["Regulation Start Date"] = pd.NaT

    return df


def filter_dataframe(df: pd.DataFrame, mode: str, selected_sectors: list) -> pd.DataFrame:
    if df.empty:
        return df

    filtered_df = df.copy()
    sector_col = "Regulation Location" if "Regulation Location" in filtered_df.columns else None

    if sector_col and selected_sectors:
        filtered_df = filtered_df[filtered_df[sector_col].isin(selected_sectors)]

    if mode == "HEC":
        filtered_df = filtered_df[filtered_df["Regulation_Type"] == "HEC"]
    elif mode == "Occupancy":
        filtered_df = filtered_df[filtered_df["Regulation_Type"] == "Occupancy"]

    return filtered_df