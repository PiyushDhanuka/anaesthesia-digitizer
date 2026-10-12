from datetime import datetime, timezone
import os
import time
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, firestore

# --- FIREBASE INITIALIZATION ---
current_dir = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(current_dir, "firebase_key.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()
print("[DB] Running 100% on Firebase Firestore")


def init_db():
    """No-op for NoSQL. Kept so main.py doesn't crash on import."""
    pass


def create_case(
    patient_id: Optional[str] = None,
    anesthetist_id: Optional[str] = None,
    or_room: Optional[str] = None
) -> str:
    """Creates a new case document in the 'cases' collection."""
    now_iso = datetime.now(timezone.utc).isoformat()
    case_id = f"case_{int(time.time() * 1000)}"
    
    doc_data = {
        "case_id": case_id,
        "started_at": now_iso,
        "ended_at": None,
        "status": "active",
        "patient_id": patient_id,
        "anesthetist_id": anesthetist_id,
        "or_room": or_room
    }
    db.collection("cases").document(case_id).set(doc_data)
    return case_id


def save_reading(
    case_id: str,
    heart_rate: Optional[float] = None,
    spo2: Optional[float] = None,
    bp_systolic: Optional[float] = None,
    bp_diastolic: Optional[float] = None,
    etco2: Optional[float] = None
):
    """Saves a reading to cases -> case_id -> readings subcollection."""
    now_iso = datetime.now(timezone.utc).isoformat()
    doc_data = {
        "case_id": case_id,
        "timestamp": now_iso,
        "heart_rate": heart_rate,
        "spo2": spo2,
        "bp_systolic": bp_systolic,
        "bp_diastolic": bp_diastolic,
        "etco2": etco2
    }
    db.collection("cases").document(case_id).collection("readings").add(doc_data)


def end_case(case_id: str):
    """Marks a case as ended."""
    now_iso = datetime.now(timezone.utc).isoformat()
    db.collection("cases").document(case_id).update({
        "status": "ended",
        "ended_at": now_iso
    })


def get_case_readings(case_id: str) -> List[Dict[str, Any]]:
    """Returns all readings for a case, ordered chronologically."""
    docs = db.collection("cases").document(case_id).collection("readings")\
             .order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
    
    readings = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id  # Map Firestore doc ID to the expected 'id' field
        readings.append(data)
    return readings


def get_active_case() -> Optional[str]:
    """Finds the active case. Sorted locally to avoid Firestore missing index errors."""
    docs = db.collection("cases").where("status", "==", "active").stream()
    active_cases = [doc.to_dict() for doc in docs]
    
    if not active_cases:
        return None
        
    # Sort descending by started_at and grab the first one
    active_cases.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return active_cases[0].get("case_id")


def get_latest_case() -> Optional[str]:
    """Returns the most recently created case."""
    docs = db.collection("cases").order_by("started_at", direction=firestore.Query.DESCENDING).limit(1).stream()
    for doc in docs:
        return doc.to_dict().get("case_id")
    return None


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    """Returns metadata for a specific case."""
    doc = db.collection("cases").document(case_id).get()
    return doc.to_dict() if doc.exists else None


def save_ground_truth_db(field: str, value: Any, timestamp: str, case_id: Optional[str] = None):
    """Saves a ground truth entry to the 'ground_truth' collection."""
    doc_data = {
        "case_id": case_id,
        "field": field,
        "value": float(value) if value is not None else 0.0,
        "timestamp": timestamp
    }
    db.collection("ground_truth").add(doc_data)


def get_ground_truth_db(case_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves ground truth entries. Sorted locally to avoid index errors."""
    if case_id:
        docs = db.collection("ground_truth").where("case_id", "==", case_id).stream()
    else:
        docs = db.collection("ground_truth").stream()
        
    rows = [doc.to_dict() for doc in docs]
    rows.sort(key=lambda x: x.get("timestamp", ""))
    return rows