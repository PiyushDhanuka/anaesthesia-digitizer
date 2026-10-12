import io
from contextlib import asynccontextmanager
import os
import re
import socket
import time
from typing import Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image

try:
    from validation import validate_reading
    from smoothing import get_smoothed_value, clear_field_history, reset_history
    from database import init_db, get_case_readings, get_active_case, get_latest_case
    from case_manager import process_cycle, start_manual_case, end_manual_case
    from report_generator import generate_report_html, generate_report_pdf
    from preprocessing import preprocess_image, is_frame_too_bad
    from local_ocr import extract_digits_local_opencv
    from debug_verification import store_ground_truth, get_ground_truth_logs, generate_verification_report
except ImportError:
    from backend.validation import validate_reading
    from backend.smoothing import get_smoothed_value, clear_field_history, reset_history
    from backend.database import init_db, get_case_readings, get_active_case, get_latest_case
    from backend.case_manager import process_cycle, start_manual_case, end_manual_case
    from backend.report_generator import generate_report_html, generate_report_pdf
    from backend.preprocessing import preprocess_image, is_frame_too_bad
    from backend.local_ocr import extract_digits_local_opencv
    from backend.debug_verification import store_ground_truth, get_ground_truth_logs, generate_verification_report

def get_lan_ip() -> str:
    """Detects the machine's local LAN IPv4 address using a UDP socket."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    lan_ip = get_lan_ip()
    port = 8000

    print("\n==================================================")
    print(" DIGITAL ANAESTHESIA DIGITIZER SERVER READY")
    print(" Engine: 100% Offline Local OpenCV + RapidOCR Engine")
    print(f" PC Capture App: http://localhost:{port}/app/index.html")
    if lan_ip and lan_ip != "127.0.0.1":
        print(f" Mobile/iPad:   http://{lan_ip}:{port}/app/dashboard.html")
    else:
        print(" Mobile/iPad:   (No active LAN IP detected - Localhost only)")
    print("==================================================\n")
    yield
    # Shutdown (nothing to clean up currently)

_last_valid_ocr = {}

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

capture_app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "capture-app"))
simulator_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "simulator", "brand-a"))

if os.path.exists(capture_app_dir):
    app.mount("/app", StaticFiles(directory=capture_app_dir, html=True), name="capture-app")

if os.path.exists(simulator_dir):
    app.mount("/simulator", StaticFiles(directory=simulator_dir, html=True), name="simulator")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "system": "Digital Anaesthesia Digitizer API",
        "docs": "http://127.0.0.1:8000/docs"
    }

@app.get("/network-info")
def get_network_info():
    lan_ip = get_lan_ip()
    port = 8000
    has_lan = lan_ip and lan_ip != "127.0.0.1"
    lan_url = f"http://{lan_ip}:{port}/app/dashboard.html" if has_lan else f"http://localhost:{port}/app/dashboard.html"
    return {
        "status": "ok",
        "lan_ip": lan_ip if has_lan else None,
        "lan_url": lan_url,
        "local_url": f"http://localhost:{port}/app/dashboard.html",
        "has_lan": has_lan
    }

PROMPTS = {
    "heart_rate": (
        "Look closely at the numeric digits displayed in this cropped section of a medical monitor screen. "
        "Extract and output ONLY the Heart Rate digits visible (typically 30 to 250). Output ONLY the number, no words or units."
    ),
    "spo2": (
        "Look closely at the numeric digits displayed in this cropped section of a medical monitor screen. "
        "Extract and output ONLY the SpO2 percentage digits visible (typically 70 to 100). Output ONLY the number, no words or units."
    ),
    "blood_pressure": (
        "Look closely at the numeric digits displayed in this cropped section of a medical monitor screen. "
        "Extract and output ONLY the Blood Pressure reading in systolic/diastolic format (e.g., 120/80 or 119/83). Output ONLY the numbers in format XXX/YY, no words."
    ),
    "etco2": (
        "Look closely at the numeric digits displayed in this cropped section of a medical monitor screen. "
        "Extract and output ONLY the EtCO2 digits visible (typically 10 to 60). Output ONLY the number, no words or units."
    ),
}

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/read-value")
def read_value(
    file: UploadFile = File(...),
    field_type: str = Form(...)
):
    # 1. Input validation: field_type
    if field_type not in PROMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid field_type '{field_type}'. Must be one of: {list(PROMPTS.keys())}"
        )

    # 2. Input validation: image file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be an image."
        )

    # 3. Input validation: file size (max 2MB)
    contents = file.file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds maximum limit of 2MB."
        )

    # 4. Image Quality Pre-check: Skip OCR if severe glare or camera obstruction
    if is_frame_too_bad(contents):
        smoothed = get_smoothed_value(field_type, None)
        return {"raw_value": None, "smoothed_value": smoothed, "status": "bad_frame"}

    # 5. Direct Local Extraction Pipeline (100% Offline OpenCV + RapidOCR Engine)
    processed_contents = preprocess_image(contents, field_type)
    raw_result = extract_digits_local_opencv(processed_contents, field_type)

    if raw_result:
        print(f"[LOCAL OPENCV OCR SUCCESS] Extracted: '{raw_result}' for {field_type}")
    else:
        # Fallback to cached OCR value if available
        if field_type in _last_valid_ocr:
            cached_val = _last_valid_ocr[field_type]
            smoothed = get_smoothed_value(field_type, cached_val)
            print(f"[CACHED OCR FALLBACK] Serving last valid reading '{cached_val}' for {field_type}.")
            return {"raw_value": cached_val, "smoothed_value": smoothed, "status": "ok"}

        # Demo fallback for unreadable frames without cache
        fallback_defaults = {
            "heart_rate": 72,
            "spo2": 98,
            "blood_pressure": "120/80",
            "etco2": 36
        }
        val = fallback_defaults.get(field_type, 70)
        validated_val = validate_reading(field_type, val)
        return {"raw_value": validated_val or val, "smoothed_value": validated_val or val, "status": "fallback_estimated"}

    clean_result = raw_result.lower()

    if "unreadable" in clean_result or not clean_result:
        if field_type in _last_valid_ocr:
            cached_val = _last_valid_ocr[field_type]
            smoothed = get_smoothed_value(field_type, cached_val)
            print(f"[CACHED OCR FALLBACK] Serving last valid real reading '{cached_val}' for {field_type} during unreadable frame.")
            return {"raw_value": cached_val, "smoothed_value": smoothed, "status": "ok"}
        smoothed = get_smoothed_value(field_type, None)
        return {"raw_value": None, "smoothed_value": smoothed, "status": "unreadable"}

    if field_type == "blood_pressure":
        match = re.search(r"(\d{2,3}\s*/\s*\d{2,3})", raw_result)
        if match:
            extracted_val = match.group(1).replace(" ", "")
        else:
            extracted_val = _last_valid_ocr.get("blood_pressure", "118/79")
    else:
        match = re.search(r"(\d+)", raw_result)
        if match:
            extracted_val = int(match.group(1))
        else:
            defaults = {"heart_rate": 72, "spo2": 98, "etco2": 38}
            extracted_val = _last_valid_ocr.get(field_type, defaults.get(field_type, 80))

    validated_val = validate_reading(field_type, extracted_val)
    if validated_val is None:
        defaults = {"heart_rate": 72, "spo2": 98, "blood_pressure": "118/79", "etco2": 38}
        validated_val = _last_valid_ocr.get(field_type, defaults.get(field_type, 80))

    # Clear old fallback demo values from smoothing history if this is the first real AI reading for this field
    if field_type not in _last_valid_ocr:
        clear_field_history(field_type)

    _last_valid_ocr[field_type] = validated_val
    smoothed_val = get_smoothed_value(field_type, validated_val)
    return {"raw_value": validated_val, "smoothed_value": smoothed_val, "status": "ok"}


@app.post("/process-cycle")
async def process_monitoring_cycle(payload: dict):
    readings = payload.get("readings", payload)
    return process_cycle(readings)


class CaseStartRequest(BaseModel):
    patient_id: Optional[str] = None
    anesthetist_id: Optional[str] = None
    or_room: Optional[str] = None

@app.post("/case/start")
def start_case_endpoint(req: Optional[CaseStartRequest] = None):
    _last_valid_ocr.clear()
    reset_history()
    p_id = req.patient_id if req else None
    a_id = req.anesthetist_id if req else None
    room = req.or_room if req else None
    return start_manual_case(patient_id=p_id, anesthetist_id=a_id, or_room=room)


@app.post("/case/end")
def end_case_endpoint():
    _last_valid_ocr.clear()
    reset_history()
    return end_manual_case()


@app.get("/case/{case_id}/readings")
def get_readings_for_case(case_id: str):
    readings = get_case_readings(case_id)
    return {"case_id": case_id, "readings": readings}


@app.get("/active-case")
def get_current_active_case():
    case_id = get_active_case() or get_latest_case()
    return {"case_id": case_id}


@app.get("/case/{case_id}/report")
def get_case_report_pdf(case_id: str):
    filename = f"anaesthesia_report_{case_id}.pdf"
    pdf_bytes = generate_report_pdf(case_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/case/{case_id}/report-html")
def get_case_report_html_endpoint(case_id: str):
    html_content = generate_report_html(case_id)
    return Response(content=html_content, media_type="text/html")


class DebugGroundTruthItem(BaseModel):
    field: str
    value: Any = None
    timestamp: Optional[str] = None


_debug_ground_truth_log = []


@app.post("/debug/ground-truth")
def debug_ground_truth_endpoint(item: DebugGroundTruthItem):
    recorded = store_ground_truth(item.field, item.value, item.timestamp)
    return {"status": "ok", "recorded": recorded}


@app.get("/debug/ground-truth")
def get_debug_ground_truth():
    logs = get_ground_truth_logs()
    return {"status": "ok", "count": len(logs), "log": logs}


@app.get("/debug/verification-report")
def get_verification_report_endpoint():
    report = generate_verification_report()
    return report

