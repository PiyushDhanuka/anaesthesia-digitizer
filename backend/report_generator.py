from datetime import datetime
from html import escape as html_escape
import base64
import io
from typing import Any, Dict, List, Optional

try:
    from database import get_case, get_case_readings
except ImportError:
    from backend.database import get_case, get_case_readings

try:
    from ai_summary import get_case_summary
except ImportError:
    from backend.ai_summary import get_case_summary


def _calc_stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "avg": None}
    return {
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "avg": round(sum(values) / len(values), 1)
    }


def _abnormal_parameters(reading: Dict[str, Any]) -> List[str]:
    """Return display-only alert labels using the dashboard's vital thresholds."""
    alerts = []
    hr = reading.get("heart_rate")
    spo2 = reading.get("spo2")
    etco2 = reading.get("etco2")

    if hr is not None and (hr > 120 or hr < 50):
        alerts.append("Heart Rate")
    if spo2 is not None and spo2 < 92:
        alerts.append("SpO2")
    if etco2 is not None and (etco2 < 30 or etco2 > 45):
        alerts.append("EtCO2")
    return alerts


def _format_timestamp(iso_str: Optional[str]) -> str:
    """Format every displayed report timestamp consistently."""
    if not iso_str or iso_str == "--":
        return "--"
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(iso_str)


def _format_duration(started_at: Optional[str], ended_at: Optional[str]) -> str:
    if not started_at or not ended_at:
        return "--"
    try:
        duration = datetime.fromisoformat(ended_at.replace("Z", "+00:00")) - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        total_seconds = max(0, int(duration.total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (TypeError, ValueError):
        return "--"


def _generate_trend_chart_data_uri(readings: List[Dict[str, Any]]) -> Optional[str]:
    """Create a PNG chart in memory for embedding in the HTML/PDF report."""
    if not readings:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt

        times = []
        for index, reading in enumerate(readings):
            try:
                times.append(datetime.fromisoformat(reading.get("timestamp", "").replace("Z", "+00:00")))
            except (AttributeError, TypeError, ValueError):
                times.append(index)

        figure, axis = plt.subplots(figsize=(9.2, 3.35), dpi=160)
        figure.patch.set_facecolor("#ffffff")
        axis.set_facecolor("#ffffff")
        for label, key, color in [
            ("Heart Rate (bpm)", "heart_rate", "#3f8b75"),
            ("SpO2 (%)", "spo2", "#4c91b0"),
            ("Blood Pressure (Systolic)", "bp_systolic", "#b6656c"),
            ("EtCO2 (mmHg)", "etco2", "#ad9348"),
        ]:
            values = [reading.get(key) for reading in readings]
            if any(value is not None for value in values):
                axis.plot(times, values, label=label, color=color, linewidth=1.7, marker="o", markersize=2.5)

        axis.set_ylabel("Measurement value", fontsize=8, color="#475569")
        axis.grid(True, color="#e2e8f0", linewidth=0.65)
        axis.tick_params(axis="both", labelsize=7, colors="#64748b")
        for spine in axis.spines.values():
            spine.set_color("#cbd5e1")
        if times and isinstance(times[0], datetime):
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            figure.autofmt_xdate(rotation=0, ha="center")
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=4, frameon=False, fontsize=7)
        figure.tight_layout(pad=1.0)

        image_buffer = io.BytesIO()
        figure.savefig(image_buffer, format="png", dpi=160, bbox_inches="tight")
        plt.close(figure)
        return f"data:image/png;base64,{base64.b64encode(image_buffer.getvalue()).decode('ascii')}"
    except Exception as error:
        print(f"[REPORT WARNING] Could not generate vital signs trend chart: {error}")
        return None


def generate_report_html(case_id: str) -> str:
    """
    Generates a clean HTML string styled like a hospital anaesthesia chart.
    Includes case info, summary statistics (min/max/avg), and full readings log.
    """
    case_info = get_case(case_id) or {"case_id": case_id, "started_at": "--", "ended_at": "--", "status": "unknown"}
    readings = get_case_readings(case_id)

    is_completed = case_info.get("status") == "ended"
    started_at_str = _format_timestamp(case_info.get("started_at"))
    ended_at_str = _format_timestamp(case_info.get("ended_at")) if is_completed else "In Progress"
    duration_str = _format_duration(case_info.get("started_at"), case_info.get("ended_at")) if is_completed else "In Progress"
    status_str = "COMPLETED" if is_completed else "ACTIVE"
    status_badge_class = "ended" if is_completed else "active"

    hrs = [r["heart_rate"] for r in readings if r.get("heart_rate") is not None]
    spo2s = [r["spo2"] for r in readings if r.get("spo2") is not None]
    sbps = [r["bp_systolic"] for r in readings if r.get("bp_systolic") is not None]
    dbps = [r["bp_diastolic"] for r in readings if r.get("bp_diastolic") is not None]
    etco2s = [r["etco2"] for r in readings if r.get("etco2") is not None]

    hr_stats = _calc_stats(hrs)
    spo2_stats = _calc_stats(spo2s)
    sbp_stats = _calc_stats(sbps)
    dbp_stats = _calc_stats(dbps)
    etco2_stats = _calc_stats(etco2s)
    abnormal_events = [(r, _abnormal_parameters(r)) for r in readings]
    abnormal_events = [(r, alerts) for r, alerts in abnormal_events if alerts]
    trend_chart_uri = _generate_trend_chart_data_uri(readings)
    case_summary = get_case_summary(case_id, readings)

    rows_html = ""
    for idx, r in enumerate(readings, 1):
        ts = _format_timestamp(r.get("timestamp"))
        hr = f"{int(round(r['heart_rate']))}" if r.get("heart_rate") is not None else "--"
        spo2 = f"{int(round(r['spo2']))}%" if r.get("spo2") is not None else "--"
        if r.get("bp_systolic") is not None and r.get("bp_diastolic") is not None:
            bp = f"{int(round(r['bp_systolic']))}/{int(round(r['bp_diastolic']))}"
        else:
            bp = "--"
        etco2 = f"{int(round(r['etco2']))}" if r.get("etco2") is not None else "--"
        alerts = _abnormal_parameters(r)
        alert_text = f"⚠ {', '.join(alerts)}" if alerts else "—"
        row_class = "abnormal-row" if alerts else ""

        rows_html += f"""
        <tr class="{row_class}">
            <td style="text-align: center;">{idx}</td>
            <td>{ts}</td>
            <td style="color: #047857; font-weight: bold; text-align: center;">{hr}</td>
            <td style="color: #0284c7; font-weight: bold; text-align: center;">{spo2}</td>
            <td style="color: #b91c1c; font-weight: bold; text-align: center;">{bp}</td>
            <td style="color: #b45309; font-weight: bold; text-align: center;">{etco2}</td>
            <td class="alert-cell">{alert_text}</td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="7" style="text-align: center; color: #6b7280;">No readings recorded for this case.</td></tr>'

    def fmt_stat(stat_dict, unit=""):
        if stat_dict["min"] is None:
            return "--"
        return f"Min: {stat_dict['min']}{unit} | Max: {stat_dict['max']}{unit} | Avg: {stat_dict['avg']}{unit}"

    bp_stat_str = "--"
    if sbp_stats["min"] is not None and dbp_stats["min"] is not None:
        bp_stat_str = f"SBP (Min: {sbp_stats['min']} | Max: {sbp_stats['max']} | Avg: {sbp_stats['avg']}) / DBP (Min: {dbp_stats['min']} | Max: {dbp_stats['max']} | Avg: {dbp_stats['avg']})"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Digital Anaesthesia Record - {case_id}</title>
    <style>
        @page {{
            size: A4;
            margin: 15mm;
        }}
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #1f2937;
            margin: 0;
            padding: 0;
            font-size: 12px;
            line-height: 1.4;
        }}
        .header-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            border-bottom: 2px solid #0284c7;
            padding-bottom: 10px;
        }}
        .header-title {{
            font-size: 20px;
            font-weight: bold;
            color: #0284c7;
            margin: 0;
        }}
        .header-sub {{
            font-size: 11px;
            color: #6b7280;
            margin-top: 2px;
        }}
        .meta-box {{
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 20px;
        }}
        .meta-grid {{
            width: 100%;
            border-collapse: collapse;
        }}
        .meta-grid td {{
            padding: 4px 0;
            vertical-align: top;
        }}
        .meta-label {{
            font-weight: bold;
            color: #475569;
            width: 120px;
        }}
        .meta-val {{
            color: #0f172a;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            background-color: #e2e8f0;
            color: #334155;
        }}
        .status-ended {{
            background-color: #fee2e2;
            color: #991b1b;
        }}
        .status-active {{
            background-color: #dcfce7;
            color: #166534;
        }}
        .section-title {{
            font-size: 14px;
            font-weight: bold;
            color: #0f172a;
            margin-top: 15px;
            margin-bottom: 8px;
            border-left: 4px solid #0284c7;
            padding-left: 8px;
        }}
        .summary-card {{
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 20px;
        }}
        .summary-item {{
            margin-bottom: 6px;
        }}
        .summary-item:last-child {{
            margin-bottom: 0;
        }}
        .summary-name {{
            font-weight: bold;
            color: #334155;
        }}
        .readings-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            margin-top: 10px;
        }}
        .readings-table col.index-col {{ width: 5%; }}
        .readings-table col.timestamp-col {{ width: 21%; }}
        .readings-table col.hr-col {{ width: 13%; }}
        .readings-table col.spo2-col {{ width: 11%; }}
        .readings-table col.bp-col {{ width: 16%; }}
        .readings-table col.etco2-col {{ width: 10%; }}
        .readings-table col.alert-col {{ width: 24%; }}
        .readings-table thead {{ display: table-header-group; }}
        .readings-table tbody {{ display: table-row-group; }}
        .readings-table tr {{ page-break-inside: avoid; }}
        .readings-table th {{
            background-color: #0f172a;
            color: #ffffff;
            font-weight: bold;
            text-align: left;
            padding: 8px 7px;
            font-size: 11px;
        }}
        .readings-table td {{
            padding: 7px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 11px;
            vertical-align: middle;
            overflow-wrap: break-word;
        }}
        .readings-table tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        .readings-table tr.abnormal-row {{
            background-color: #fef2f2;
        }}
        .alert-cell {{
            color: #b91c1c;
            font-weight: bold;
            font-size: 10px;
        }}
        .alert-summary {{
            margin-top: 10px;
            padding: 8px 10px;
            border: 1px solid #fca5a5;
            border-radius: 4px;
            background-color: #fef2f2;
            color: #991b1b;
            font-weight: bold;
        }}
        .trend-chart-card {{
            margin-bottom: 20px;
            padding: 12px 14px 10px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            background: #ffffff;
            page-break-inside: avoid;
        }}
        .trend-chart-card img {{
            display: block;
            width: 100%;
            height: auto;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            font-size: 10px;
            color: #94a3b8;
            border-top: 1px solid #e2e8f0;
            padding-top: 10px;
        }}
    </style>
</head>
<body>
    <table class="header-table">
        <tr>
            <td>
                <div class="header-title">Digital Anaesthesia Record</div>
                <div class="header-sub">Automated Patient Vital Signs Charting Report</div>
            </td>
            <td style="text-align: right; vertical-align: bottom;">
                <span class="status-badge status-{status_badge_class}">Status: {status_str}</span>
            </td>
        </tr>
    </table>

    <div class="meta-box">
        <table class="meta-grid">
            <tr>
                <td class="meta-label">Case ID:</td>
                <td class="meta-val"><strong>{case_info.get('case_id')}</strong></td>
                <td class="meta-label">Patient ID:</td>
                <td class="meta-val"><strong>{case_info.get('patient_id') or 'Not specified'}</strong></td>
            </tr>
            <tr>
                <td class="meta-label">Anesthetist:</td>
                <td class="meta-val">{case_info.get('anesthetist_id') or 'Not specified'}</td>
                <td class="meta-label">OR Room:</td>
                <td class="meta-val">{case_info.get('or_room') or 'Not specified'}</td>
            </tr>
            <tr>
                <td class="meta-label">Start Time:</td>
                <td class="meta-val">{started_at_str}</td>
                <td class="meta-label">End Time:</td>
                <td class="meta-val">{ended_at_str}</td>
            </tr>
            <tr>
                <td class="meta-label">Duration:</td>
                <td class="meta-val">{duration_str}</td>
                <td class="meta-label">Total Readings:</td>
                <td class="meta-val"><strong>{len(readings)} cycles</strong></td>
            </tr>
        </table>
        <div style="margin-top: 8px; color: #64748b; font-size: 10px;">Data Source: Camera-based monitor digitization | Validation: Physiological range checks | Storage: Local processing</div>
    </div>

    <div class="section-title">Case Vital Signs Statistical Summary</div>
    <div class="summary-card">
        <div class="summary-item"><span class="summary-name" style="color: #047857;">Heart Rate (bpm):</span> {fmt_stat(hr_stats, " bpm")}</div>
        <div class="summary-item"><span class="summary-name" style="color: #0284c7;">SpO2 (%):</span> {fmt_stat(spo2_stats, "%")}</div>
        <div class="summary-item"><span class="summary-name" style="color: #b91c1c;">Blood Pressure (mmHg):</span> {bp_stat_str}</div>
        <div class="summary-item"><span class="summary-name" style="color: #b45309;">EtCO2 (mmHg):</span> {fmt_stat(etco2_stats, " mmHg")}</div>
        <div class="alert-summary">⚠ Abnormal events detected: {len(abnormal_events)} reading{'s' if len(abnormal_events) != 1 else ''}</div>
    </div>

    <div class="section-title">Case Narrative Summary</div>
    <div class="summary-card">
        <div style="font-size: 12px; line-height: 1.5;">{html_escape(case_summary['text'])}</div>
        <div style="margin-top: 6px; color: #64748b; font-size: 10px;">Source: {html_escape(case_summary['source'])}. Generated from the recorded readings; clinician review required.</div>
    </div>

    {f'''<div class="section-title">Vital Signs Trend</div><div class="trend-chart-card"><img src="{trend_chart_uri}" alt="Vital signs trend chart"></div>''' if trend_chart_uri else ''}

    <div class="section-title">Detailed Time-Series Vitals Log</div>
    <table class="readings-table">
        <colgroup>
            <col class="index-col">
            <col class="timestamp-col">
            <col class="hr-col">
            <col class="spo2-col">
            <col class="bp-col">
            <col class="etco2-col">
            <col class="alert-col">
        </colgroup>
        <thead>
            <tr>
                <th style="width: 35px; text-align: center;">#</th>
                <th style="width: 140px;">Timestamp</th>
                <th style="text-align: center;">Heart Rate (bpm)</th>
                <th style="text-align: center;">SpO2 (%)</th>
                <th style="text-align: center;">Blood Pressure (mmHg)</th>
                <th style="text-align: center;">EtCO2 (mmHg)</th>
                <th style="text-align: center;">Alert</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <div class="footer">
        Generated by Digital Anaesthesia Digitizer System &bull; Confidential Medical Chart
    </div>
</body>
</html>
"""
    return html_content


def generate_report_pdf(case_id: str) -> bytes:
    """
    Generates a standalone clinical PDF report using ReportLab.
    Includes case metadata, statistical summary, embedded trend chart image, and readings log.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0284c7'),
        fontName='Helvetica-Bold'
    )
    sub_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#6b7280'),
        fontName='Helvetica'
    )
    section_style = ParagraphStyle(
        'SecTitle',
        parent=styles['Heading2'],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#0f172a'),
        fontName='Helvetica-Bold',
        spaceBefore=10,
        spaceAfter=6
    )

    story.append(Paragraph("Digital Anaesthesia Record", title_style))
    story.append(Paragraph("Automated Patient Vital Signs Charting Report", sub_style))
    story.append(Spacer(1, 10))

    case_info = get_case(case_id) or {"case_id": case_id, "started_at": "--", "ended_at": "--", "status": "unknown"}
    readings = get_case_readings(case_id)

    is_completed = case_info.get("status") == "ended"
    started_at_str = _format_timestamp(case_info.get("started_at"))
    ended_at_str = _format_timestamp(case_info.get("ended_at")) if is_completed else "In Progress"
    duration_str = _format_duration(case_info.get("started_at"), case_info.get("ended_at")) if is_completed else "In Progress"
    status_str = "COMPLETED" if is_completed else "ACTIVE"

    patient_id_str = case_info.get("patient_id") or "Not specified"
    anesthetist_str = case_info.get("anesthetist_id") or "Not specified"
    or_room_str = case_info.get("or_room") or "Not specified"

    meta_data = [
        [Paragraph(f"<b>Case ID:</b> {case_info.get('case_id')}", styles['Normal']), Paragraph(f"<b>Patient ID:</b> {patient_id_str}", styles['Normal'])],
        [Paragraph(f"<b>Anesthetist:</b> {anesthetist_str}", styles['Normal']), Paragraph(f"<b>OR Room:</b> {or_room_str}", styles['Normal'])],
        [Paragraph(f"<b>Start Time:</b> {started_at_str}", styles['Normal']), Paragraph(f"<b>End Time:</b> {ended_at_str}", styles['Normal'])],
        [Paragraph(f"<b>Duration:</b> {duration_str}", styles['Normal']), Paragraph(f"<b>Total Readings:</b> {len(readings)} cycles", styles['Normal'])]
    ]
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Case Vital Signs Statistical Summary", section_style))

    hrs = [r["heart_rate"] for r in readings if r.get("heart_rate") is not None]
    spo2s = [r["spo2"] for r in readings if r.get("spo2") is not None]
    sbps = [r["bp_systolic"] for r in readings if r.get("bp_systolic") is not None]
    dbps = [r["bp_diastolic"] for r in readings if r.get("bp_diastolic") is not None]
    etco2s = [r["etco2"] for r in readings if r.get("etco2") is not None]

    hr_s = _calc_stats(hrs)
    spo2_s = _calc_stats(spo2s)
    sbp_s = _calc_stats(sbps)
    dbp_s = _calc_stats(dbps)
    etco2_s = _calc_stats(etco2s)
    abnormal_events = [(r, _abnormal_parameters(r)) for r in readings if _abnormal_parameters(r)]

    def s_str(s, unit=""):
        return f"Min: {s['min']}{unit} | Max: {s['max']}{unit} | Avg: {s['avg']}{unit}" if s['min'] is not None else "--"

    bp_s_str = "--"
    if sbp_s['min'] is not None and dbp_s['min'] is not None:
        bp_s_str = f"SBP ({s_str(sbp_s)}) / DBP ({s_str(dbp_s)})"

    sum_data = [
        [Paragraph("<b>Heart Rate (bpm):</b>", styles['Normal']), Paragraph(s_str(hr_s, " bpm"), styles['Normal'])],
        [Paragraph("<b>SpO2 (%):</b>", styles['Normal']), Paragraph(s_str(spo2_s, "%"), styles['Normal'])],
        [Paragraph("<b>Blood Pressure:</b>", styles['Normal']), Paragraph(bp_s_str, styles['Normal'])],
        [Paragraph("<b>EtCO2 (mmHg):</b>", styles['Normal']), Paragraph(s_str(etco2_s, " mmHg"), styles['Normal'])]
    ]
    sum_table = Table(sum_data, colWidths=[140, 400])
    sum_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ffffff')),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 8))

    alert_summary_style = ParagraphStyle(
        'AlertSummary',
        parent=styles['Normal'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#991b1b'),
        backColor=colors.HexColor('#fef2f2'),
        borderColor=colors.HexColor('#fca5a5'),
        borderWidth=0.5,
        borderPadding=6,
        spaceAfter=12
    )
    event_count = len(abnormal_events)
    story.append(Paragraph(f"<b>ALERT:</b> {event_count} abnormal reading{'s' if event_count != 1 else ''} detected.", alert_summary_style))

    case_summary = get_case_summary(case_id, readings)
    story.append(Paragraph("Case Narrative Summary", section_style))
    story.append(Paragraph(html_escape(case_summary["text"]), styles['Normal']))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"<font size=8 color='#64748b'>Source: {html_escape(case_summary['source'])}. Generated from the recorded readings; clinician review required.</font>",
        styles['Normal']))
    story.append(Spacer(1, 10))

    # Embed Vital Signs Trend Chart Image into ReportLab PDF
    trend_chart_uri = _generate_trend_chart_data_uri(readings)
    if trend_chart_uri:
        try:
            header, encoded = trend_chart_uri.split(",", 1)
            img_data = base64.b64decode(encoded)
            img_buffer = io.BytesIO(img_data)
            trend_img = RLImage(img_buffer, width=540, height=195)
            story.append(Paragraph("Vital Signs Trend Chart", section_style))
            story.append(trend_img)
            story.append(Spacer(1, 12))
        except Exception as img_err:
            print(f"[REPORT WARNING] Could not embed trend chart image in ReportLab PDF: {img_err}")

    story.append(Paragraph("Detailed Time-Series Vitals Log", section_style))

    table_data = [["#", "Timestamp", "Heart Rate", "SpO2", "Blood Pressure", "EtCO2", "Alert"]]
    abnormal_row_indexes = []
    for idx, r in enumerate(readings, 1):
        ts = _format_timestamp(r.get("timestamp"))
        hr = f"{int(round(r['heart_rate']))}" if r.get("heart_rate") is not None else "--"
        spo2 = f"{int(round(r['spo2']))}%" if r.get("spo2") is not None else "--"
        bp = f"{int(round(r['bp_systolic']))}/{int(round(r['bp_diastolic']))}" if r.get("bp_systolic") is not None and r.get("bp_diastolic") is not None else "--"
        etco2 = f"{int(round(r['etco2']))}" if r.get("etco2") is not None else "--"
        alerts = _abnormal_parameters(r)
        alert_text = f"ALERT: {', '.join(alerts)}" if alerts else "—"
        table_data.append([str(idx), ts, hr, spo2, bp, etco2, alert_text])
        if alerts:
            abnormal_row_indexes.append(idx)

    if len(table_data) == 1:
        table_data.append(["-", "--", "--", "--", "--", "--", "--"])

    t = Table(table_data, colWidths=[25, 105, 75, 65, 100, 65, 105])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]))
    for row_index in abnormal_row_indexes:
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#fef2f2')),
            ('TEXTCOLOR', (6, row_index), (6, row_index), colors.HexColor('#b91c1c')),
            ('FONTNAME', (6, row_index), (6, row_index), 'Helvetica-Bold'),
        ]))
    story.append(t)

    doc.build(story)
    return buffer.getvalue()
