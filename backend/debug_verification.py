from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
try:
    from database import get_active_case, get_latest_case, get_case_readings, save_ground_truth_db, get_ground_truth_db
except ImportError:
    from backend.database import get_active_case, get_latest_case, get_case_readings, save_ground_truth_db, get_ground_truth_db

# In-memory fallback/cache storage
_ground_truth_logs: List[Dict[str, Any]] = []

FIELD_TOLERANCES = {
    "heart_rate": 2.0,
    "spo2": 1.0,
    "bp_systolic": 3.0,
    "bp_diastolic": 3.0,
    "etco2": 2.0
}


def store_ground_truth(field: str, value: Any, timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Stores a ground-truth entry received from simulator side-channel into memory & SQLite."""
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "field": field,
        "value": value,
        "timestamp": timestamp
    }
    _ground_truth_logs.append(entry)
    case_id = get_active_case() or get_latest_case()
    try:
        save_ground_truth_db(field, value, timestamp, case_id)
    except Exception as e:
        pass
    return entry


def get_ground_truth_logs() -> List[Dict[str, Any]]:
    db_logs = get_ground_truth_db()
    if db_logs:
        return db_logs
    return _ground_truth_logs


def clear_ground_truth_logs():
    global _ground_truth_logs
    _ground_truth_logs = []


def _parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        ts_clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def generate_verification_report() -> Dict[str, Any]:
    """
    Pulls ground-truth entries and actual OCR readings for current active or most recent case,
    finds closest matching ground truth within 5 seconds for each OCR reading,
    evaluates exact matches, close matches (within field tolerance), and mismatches,
    and returns a comprehensive JSON report.
    """
    case_id = get_active_case() or get_latest_case()
    ocr_readings = get_case_readings(case_id) if case_id else []

    target_fields = ["heart_rate", "spo2", "bp_systolic", "bp_diastolic", "etco2"]

    field_stats = {
        field: {
            "total": 0,
            "exact_matches": 0,
            "close_matches": 0,
            "mismatches": 0,
            "exact_match_pct": 0.0,
            "close_match_pct": 0.0,
            "mismatch_pct": 0.0
        } for field in target_fields
    }

    total_comparisons = 0
    total_exact = 0
    total_close = 0
    total_mismatches = 0
    mismatch_details = []

    gt_source = get_ground_truth_db(case_id) or get_ground_truth_db() or _ground_truth_logs

    # Convert ground truth timestamps for fast lookup
    parsed_gt_logs = []
    for gt in gt_source:
        gt_dt = _parse_iso_timestamp(gt.get("timestamp"))
        if gt_dt:
            parsed_gt_logs.append({
                "field": gt.get("field"),
                "value": gt.get("value"),
                "timestamp_str": gt.get("timestamp"),
                "dt": gt_dt
            })

    for reading in ocr_readings:
        ocr_dt = _parse_iso_timestamp(reading.get("timestamp"))
        if not ocr_dt:
            continue

        for field in target_fields:
            ocr_val = reading.get(field)
            if ocr_val is None:
                continue

            try:
                ocr_num = float(ocr_val)
            except (ValueError, TypeError):
                continue

            # Find closest ground-truth entry within 5-second window
            candidate_gts = [
                gt for gt in parsed_gt_logs
                if gt["field"] == field and abs((gt["dt"] - ocr_dt).total_seconds()) <= 5.0
            ]

            if not candidate_gts:
                continue

            best_gt = min(candidate_gts, key=lambda gt: abs((gt["dt"] - ocr_dt).total_seconds()))
            time_diff = abs((best_gt["dt"] - ocr_dt).total_seconds())

            try:
                gt_num = float(best_gt["value"])
            except (ValueError, TypeError):
                continue

            diff = abs(ocr_num - gt_num)
            tolerance = FIELD_TOLERANCES.get(field, 2.0)

            total_comparisons += 1
            field_stats[field]["total"] += 1

            if diff == 0:
                total_exact += 1
                field_stats[field]["exact_matches"] += 1
            elif diff <= tolerance:
                total_close += 1
                field_stats[field]["close_matches"] += 1
            else:
                total_mismatches += 1
                field_stats[field]["mismatches"] += 1
                mismatch_details.append({
                    "field": field,
                    "ocr_timestamp": reading.get("timestamp"),
                    "ground_truth_timestamp": best_gt["timestamp_str"],
                    "ocr_value": ocr_num,
                    "ground_truth_value": gt_num,
                    "difference": round(diff, 2),
                    "time_diff_seconds": round(time_diff, 2)
                })

    # Calculate overall percentages
    exact_pct = round((total_exact / total_comparisons * 100), 2) if total_comparisons > 0 else 0.0
    close_pct = round((total_close / total_comparisons * 100), 2) if total_comparisons > 0 else 0.0
    mismatch_pct = round((total_mismatches / total_comparisons * 100), 2) if total_comparisons > 0 else 0.0

    # Calculate per-field percentages
    for field, stats in field_stats.items():
        cnt = stats["total"]
        if cnt > 0:
            stats["exact_match_pct"] = round((stats["exact_matches"] / cnt * 100), 2)
            stats["close_match_pct"] = round((stats["close_matches"] / cnt * 100), 2)
            stats["mismatch_pct"] = round((stats["mismatches"] / cnt * 100), 2)

    return {
        "case_id": case_id,
        "total_ground_truth_logs": len(_ground_truth_logs),
        "total_comparisons": total_comparisons,
        "exact_match_count": total_exact,
        "exact_match_pct": exact_pct,
        "close_match_count": total_close,
        "close_match_pct": close_pct,
        "mismatch_count": total_mismatches,
        "mismatch_pct": mismatch_pct,
        "by_field": field_stats,
        "mismatches": mismatch_details
    }
