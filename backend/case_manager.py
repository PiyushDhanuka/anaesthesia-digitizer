import re
import time
from typing import Any, Dict, Optional, Tuple, Union

try:
    from database import create_case, end_case, get_active_case, save_reading
except ImportError:
    from backend.database import create_case, end_case, get_active_case, save_reading

# In-memory counters and per-field freshness tracking
_good_cycles_count: int = 0
_stale_cycles_count: int = 0
_is_manual_mode: bool = False

_last_read_timestamps: Dict[str, float] = {
    "heart_rate": 0.0,
    "spo2": 0.0,
    "blood_pressure": 0.0,
    "etco2": 0.0
}

_last_read_values: Dict[str, Optional[float]] = {
    "heart_rate": None,
    "spo2": None,
    "bp_systolic": None,
    "bp_diastolic": None,
    "etco2": None
}

_all_stale_start_time: Optional[float] = None


def reset_counters():
    """Resets in-memory cycle counters and freshness trackers (mainly for testing)."""
    global _good_cycles_count, _stale_cycles_count, _is_manual_mode, _all_stale_start_time
    _good_cycles_count = 0
    _stale_cycles_count = 0
    _is_manual_mode = False
    _all_stale_start_time = None
    for k in _last_read_timestamps:
        _last_read_timestamps[k] = 0.0
    for k in _last_read_values:
        _last_read_values[k] = None


def start_manual_case(
    patient_id: Optional[str] = None,
    anesthetist_id: Optional[str] = None,
    or_room: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manually starts a new case with optional clinical metadata, ending any previous active case.
    """
    global _is_manual_mode, _good_cycles_count, _stale_cycles_count

    active_id = get_active_case()
    if active_id is not None:
        end_case(active_id)

    active_id = create_case(patient_id=patient_id, anesthetist_id=anesthetist_id, or_room=or_room)

    _is_manual_mode = True
    _good_cycles_count = 0
    _stale_cycles_count = 0

    return {
        "status": "case_started",
        "case_id": active_id,
        "message": "Case Started — Recording",
        "manual": True,
        "patient_id": patient_id,
        "anesthetist_id": anesthetist_id,
        "or_room": or_room
    }


def end_manual_case() -> Dict[str, Any]:
    """
    Manually ends the current active case, overriding automatic detection.
    Resets manual mode flag to allow future manual or automatic case creation.
    """
    global _is_manual_mode, _good_cycles_count, _stale_cycles_count

    active_id = get_active_case()
    if active_id is not None:
        end_case(active_id)
        ended_id = active_id
    else:
        ended_id = None

    _is_manual_mode = False
    _good_cycles_count = 0
    _stale_cycles_count = 0

    return {
        "status": "case_ended",
        "case_id": ended_id,
        "message": "Case Ended",
        "manual": False
    }


def _parse_reading_values(readings_dict: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Helper to extract numeric values from both flat and nested cycle readings dict.
    ONLY status == 'ok' produces a valid non-None float.
    'signal_lost', 'unreadable', 'bad_frame', 'invalid_range', and 'fallback_estimated'
    result in None.
    """
    extracted = {
        "heart_rate": None,
        "spo2": None,
        "bp_systolic": None,
        "bp_diastolic": None,
        "etco2": None
    }

    # 1. Parse flat format (e.g. {"heart_rate": 78, "bp_systolic": 120, ...})
    for key in ["heart_rate", "spo2", "bp_systolic", "bp_diastolic", "etco2"]:
        val = readings_dict.get(key)
        if val is not None and not isinstance(val, dict):
            try:
                extracted[key] = float(val)
            except (ValueError, TypeError):
                pass

    # 2. Parse nested dict format (e.g. {"heart_rate": {"raw_value": 78, "smoothed_value": 78.0, "status": "ok"}})
    valid_statuses = ("ok", "fallback_estimated")

    hr_item = readings_dict.get("heart_rate")
    if isinstance(hr_item, dict) and hr_item.get("status") in valid_statuses:
        val = hr_item.get("smoothed_value") if hr_item.get("smoothed_value") is not None else hr_item.get("raw_value")
        if val is not None:
            try:
                extracted["heart_rate"] = float(val)
            except (ValueError, TypeError):
                pass

    spo2_item = readings_dict.get("spo2")
    if isinstance(spo2_item, dict) and spo2_item.get("status") in valid_statuses:
        val = spo2_item.get("smoothed_value") if spo2_item.get("smoothed_value") is not None else spo2_item.get("raw_value")
        if val is not None:
            try:
                extracted["spo2"] = float(val)
            except (ValueError, TypeError):
                pass

    etco2_item = readings_dict.get("etco2")
    if isinstance(etco2_item, dict) and etco2_item.get("status") in valid_statuses:
        val = etco2_item.get("smoothed_value") if etco2_item.get("smoothed_value") is not None else etco2_item.get("raw_value")
        if val is not None:
            try:
                extracted["etco2"] = float(val)
            except (ValueError, TypeError):
                pass

    bp_item = readings_dict.get("blood_pressure")
    if isinstance(bp_item, dict) and bp_item.get("status") in valid_statuses:
        val = bp_item.get("smoothed_value") if bp_item.get("smoothed_value") is not None else bp_item.get("raw_value")
        if isinstance(val, str):
            match = re.match(r"^(\d+)/(\d+)$", val.strip())
            if match:
                try:
                    extracted["bp_systolic"] = float(match.group(1))
                    extracted["bp_diastolic"] = float(match.group(2))
                except (ValueError, TypeError):
                    pass

    # Support bp_systolic and bp_diastolic as separate nested dict items
    sys_item = readings_dict.get("bp_systolic")
    if isinstance(sys_item, dict) and sys_item.get("status") in valid_statuses:
        val = sys_item.get("smoothed_value") if sys_item.get("smoothed_value") is not None else sys_item.get("raw_value")
        if val is not None:
            try:
                extracted["bp_systolic"] = float(val)
            except (ValueError, TypeError):
                pass

    dia_item = readings_dict.get("bp_diastolic")
    if isinstance(dia_item, dict) and dia_item.get("status") in valid_statuses:
        val = dia_item.get("smoothed_value") if dia_item.get("smoothed_value") is not None else dia_item.get("raw_value")
        if val is not None:
            try:
                extracted["bp_diastolic"] = float(val)
            except (ValueError, TypeError):
                pass

    return extracted


def _normalize_readings(readings_dict: Dict[str, Any], vals: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """
    Constructs per-field status dictionary so no field status ('signal_lost',
    'unreadable', 'bad_frame', 'invalid_range', 'ok') is silently dropped from the
    /process-cycle response.
    """
    fields = ["heart_rate", "spo2", "blood_pressure", "etco2"]
    normalized = {}

    for field in fields:
        item = readings_dict.get(field)
        if isinstance(item, dict):
            normalized[field] = {
                "raw_value": item.get("raw_value"),
                "smoothed_value": item.get("smoothed_value"),
                "status": item.get("status", "unreadable")
            }
        else:
            if field == "blood_pressure":
                sys_val = vals.get("bp_systolic")
                dia_val = vals.get("bp_diastolic")
                if sys_val is not None and dia_val is not None:
                    bp_str = f"{int(sys_val)}/{int(dia_val)}"
                    normalized[field] = {"raw_value": bp_str, "smoothed_value": bp_str, "status": "ok"}
                else:
                    normalized[field] = {"raw_value": None, "smoothed_value": None, "status": "unreadable"}
            else:
                val = vals.get(field)
                if val is not None:
                    normalized[field] = {"raw_value": val, "smoothed_value": val, "status": "ok"}
                else:
                    normalized[field] = {"raw_value": None, "smoothed_value": None, "status": "unreadable"}

    return normalized


def process_cycle(readings_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processes a monitoring cycle dictionary containing field results.
    Tracks per-field freshness timestamps (15-second window) to accommodate
    sequential rotation polling without requiring same-cycle joint readings.
    """
    global _good_cycles_count, _stale_cycles_count, _is_manual_mode, _all_stale_start_time

    now = time.time()
    vals = _parse_reading_values(readings_dict)
    normalized_readings = _normalize_readings(readings_dict, vals)

    # 1. Update last-read timestamps and values for valid ('ok') fields
    if vals["heart_rate"] is not None:
        _last_read_timestamps["heart_rate"] = now
        _last_read_values["heart_rate"] = vals["heart_rate"]

    if vals["spo2"] is not None:
        _last_read_timestamps["spo2"] = now
        _last_read_values["spo2"] = vals["spo2"]

    if vals["bp_systolic"] is not None and vals["bp_diastolic"] is not None:
        _last_read_timestamps["blood_pressure"] = now
        _last_read_values["bp_systolic"] = vals["bp_systolic"]
        _last_read_values["bp_diastolic"] = vals["bp_diastolic"]

    if vals["etco2"] is not None:
        _last_read_timestamps["etco2"] = now
        _last_read_values["etco2"] = vals["etco2"]

    # 2. Evaluate per-field freshness within 15-second sliding window
    FRESHNESS_WINDOW = 15.0
    fresh_status = {}
    fresh_count = 0
    fresh_log_parts = []

    field_labels = [
        ("heart_rate", "HR"),
        ("spo2", "SpO2"),
        ("blood_pressure", "BP"),
        ("etco2", "EtCO2")
    ]

    for field_key, label in field_labels:
        ts = _last_read_timestamps[field_key]
        if ts > 0 and (now - ts) <= FRESHNESS_WINDOW:
            fresh_status[field_key] = True
            fresh_count += 1
            age = int(now - ts)
            fresh_log_parts.append(f"{label}: fresh ({age}s ago)")
        else:
            fresh_status[field_key] = False
            age_str = f"{int(now - ts)}s ago" if ts > 0 else "never"
            fresh_log_parts.append(f"{label}: stale ({age_str})")

    # Terminal logging per cycle for live visual feedback during testing
    print(f"[FRESHNESS TRACKER] {' | '.join(fresh_log_parts)} (Fresh fields: {fresh_count}/4)")

    active_case_id = get_active_case()

    # Reset manual mode if case was ended elsewhere
    if active_case_id is None and _is_manual_mode:
        _is_manual_mode = False

    # MANUAL MODE CYCLE HANDLING
    if _is_manual_mode and active_case_id is not None:
        save_reading(
            active_case_id,
            heart_rate=_last_read_values["heart_rate"] if fresh_status["heart_rate"] else None,
            spo2=_last_read_values["spo2"] if fresh_status["spo2"] else None,
            bp_systolic=_last_read_values["bp_systolic"] if fresh_status["blood_pressure"] else None,
            bp_diastolic=_last_read_values["bp_diastolic"] if fresh_status["blood_pressure"] else None,
            etco2=_last_read_values["etco2"] if fresh_status["etco2"] else None
        )

        return {
            "status": "recording",
            "case_id": active_case_id,
            "message": "Case Started — Recording",
            "readings": normalized_readings,
            "manual": True
        }

    # AUTOMATIC MODE LIFECYCLE
    # Trigger case-start once at least 3 of the 4 fields are fresh within the 15s window
    if active_case_id is None and fresh_count >= 3:
        new_case_id = create_case()
        _all_stale_start_time = None

        save_reading(
            new_case_id,
            heart_rate=_last_read_values["heart_rate"],
            spo2=_last_read_values["spo2"],
            bp_systolic=_last_read_values["bp_systolic"],
            bp_diastolic=_last_read_values["bp_diastolic"],
            etco2=_last_read_values["etco2"]
        )

        return {
            "status": "case_started",
            "case_id": new_case_id,
            "message": "Case Started — Recording",
            "readings": normalized_readings,
            "manual": False
        }

    # Auto end-of-case stale detection: triggers only if ALL 4 fields remain stale for >30s
    if active_case_id is not None and not _is_manual_mode:
        if fresh_count == 0:
            if _all_stale_start_time is None:
                _all_stale_start_time = now
            elif (now - _all_stale_start_time) >= 30.0:
                ended_case_id = active_case_id
                end_case(ended_case_id)
                _all_stale_start_time = None

                return {
                    "status": "case_ended",
                    "case_id": ended_case_id,
                    "message": "Case Ended",
                    "readings": normalized_readings,
                    "manual": False
                }
        else:
            _all_stale_start_time = None

    if active_case_id is not None:
        save_reading(
            active_case_id,
            heart_rate=_last_read_values["heart_rate"] if fresh_status["heart_rate"] else None,
            spo2=_last_read_values["spo2"] if fresh_status["spo2"] else None,
            bp_systolic=_last_read_values["bp_systolic"] if fresh_status["blood_pressure"] else None,
            bp_diastolic=_last_read_values["bp_diastolic"] if fresh_status["blood_pressure"] else None,
            etco2=_last_read_values["etco2"] if fresh_status["etco2"] else None
        )

        return {
            "status": "recording",
            "case_id": active_case_id,
            "message": "Case Started — Recording",
            "readings": normalized_readings,
            "manual": False
        }

    return {
        "status": "waiting",
        "case_id": None,
        "message": "Waiting for stable signal",
        "readings": normalized_readings,
        "manual": False
    }
