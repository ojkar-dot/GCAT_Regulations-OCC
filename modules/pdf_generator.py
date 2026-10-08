from io import BytesIO
from fpdf import FPDF
import datetime
import pandas as pd

class PDFReport(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 12)
        self.set_text_color(40, 80, 120)
        self.cell(0, 10, 'GCAT REGULATIONS 2026 - INFORME EJECUTIVO GLOBAL', 0, 1, 'L')
        self.set_font('helvetica', '', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Fecha de generacion: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}', 0, 1, 'L')
        self.line(10, 22, 200, 22)
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

def generate_comprehensive_pdf(df_filtered: pd.DataFrame, insights_list: list) -> bytes:
    """
    Genera un informe PDF completo con los KPIs globales de la vista y las recomendaciones del DSS.
    """
    pdf = PDFReport()
    pdf.add_page()
    
    # Título principal
    pdf.set_font('helvetica', 'B', 15)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 8, 'Resumen Ejecutivo y Auditoria Operativa (FMPs)', 0, 1, 'L')
    pdf.ln(3)

    # --- 1. BLOQUE DE KPIs GLOBALES ---
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_fill_color(240, 245, 250)
    pdf.cell(0, 7, ' Indicadores Globales del Periodo Filtrado', 0, 1, 'L', fill=True)
    pdf.set_font('helvetica', '', 10)
    pdf.ln(2)

    # Calcular métricas globales del df_filtered
    total_regs = len(df_filtered)
    total_sectors = df_filtered['Protected Location Id'].nunique() if 'Protected Location Id' in df_filtered.columns else 0
    
    traffic_col = next((c for c in df_filtered.columns if 'traffic' in c.lower() or 'trafico' in c.lower()), None)
    total_traffic = int(df_filtered[traffic_col].sum()) if traffic_col and not df_filtered.empty else 0

    delay_col = next((c for c in df_filtered.columns if 'total_delay' in c.lower() or 'delay' in c.lower() or 'demora' in c.lower()), None)
    total_delay = int(df_filtered[delay_col].sum()) if delay_col and not df_filtered.empty else 0

    kpi_data = [
        ("Total Regulaciones", f"{total_regs:,}"),
        ("Sectores Afectados", f"{total_sectors}"),
        ("Tráfico Regulado (Vuelos)", f"{total_traffic:,}"),
        ("Demora Total", f"{total_delay:,} min")
    ]

    # Pintar KPIs en formato de tabla compacta de 2 columnas
    for label, val in kpi_data:
        pdf.cell(95, 6, f'  - {label}:', 0, 0)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(95, 6, f'{val}', 0, 1)
        pdf.set_font('helvetica', '', 10)

    pdf.ln(6)

    # --- 2. BLOQUE DE OCUPANCY Y ANTELACIÓN ---
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_fill_color(240, 245, 250)
    pdf.cell(0, 7, ' Metricas Especificas de Occupancy (vs HEC)', 0, 1, 'L', fill=True)
    pdf.set_font('helvetica', '', 10)
    pdf.ln(2)

    occ_df = df_filtered[df_filtered['Regulation_Type'].str.contains('Occupancy', case=False, na=False)] if 'Regulation_Type' in df_filtered.columns else pd.DataFrame()
    occ_regs = len(occ_df)
    occ_pct = (occ_regs / total_regs * 100) if total_regs > 0 else 0

    occ_delay_col = next((c for c in occ_df.columns if any(k in c.lower() for k in ['avg_delay', 'delay', 'demora'])), None)
    avg_delay_occ = occ_df[occ_delay_col].mean() if occ_delay_col and not occ_df.empty else 0.0

    pre_cols = [c for c in occ_df.columns if any(k in c.lower() for k in ['preaviso', 'notice', 'lead'])]
    avg_notice_occ = occ_df[pre_cols[0]].mean() if pre_cols and not occ_df.empty else 0.0

    occ_kpis = [
        ("Cuota de Uso (Occupancy)", f"{occ_pct:.1f}% ({occ_regs} de {total_regs} regs)"),
        ("Demora Media (Occupancy)", f"{avg_delay_occ:.1f} min"),
        ("Preaviso Medio (Occupancy)", f"{avg_notice_occ:.1f} min")
    ]

    for label, val in occ_kpis:
        pdf.cell(95, 6, f'  - {label}:', 0, 0)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(95, 6, f'{val}', 0, 1)
        pdf.set_font('helvetica', '', 10)

    pdf.ln(6)

    # --- 3. BLOQUE DE RECOMENDACIONES DEL DSS ---
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_fill_color(240, 245, 250)
    pdf.cell(0, 7, ' Recomendaciones Operativas para FMPs', 0, 1, 'L', fill=True)
    pdf.ln(4)

    for idx, ins in enumerate(insights_list, 1):
        pdf.set_font('helvetica', 'B', 10)
        pdf.set_text_color(30, 80, 130)
        pdf.cell(0, 5, f'{idx}. {ins["title"]}', 0, 1, 'L')
        
        pdf.set_font('helvetica', '', 9)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 4.5, ins['text'])
        pdf.ln(3)

    return bytes(pdf.output())