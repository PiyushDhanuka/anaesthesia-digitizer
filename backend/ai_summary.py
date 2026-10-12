"""
Case summary for the anaesthesia report.

Facts (min/max/avg, abnormal episodes, durations) are computed deterministically
in code. Gemini (Google Cloud) is only asked to rephrase those facts as a short
narrative, so it cannot invent numbers. If Gemini is unavailable or errors out,
a rule-based narrative built from the same facts is returned, so reports always work.

Configuration (environment variables):
  GEMINI_API_KEY        use the Gemini API with an API key, or
  GOOGLE_CLOUD_PROJECT  use Vertex AI with Application Default Credentials
                        (automatic on Cloud Run); GOOGLE_CLOUD_LOCATION optional
  GEMINI_MODEL          default: gemini-2.5-flash
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

_cache: Dict[Any, Dict[str, str]] = {}


def _parse(ts: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _stats(values: List[float]) -> Optional[Dict[str, float]]:
    if not values:
        return None
    return {"min": round(min(values), 1), "max": round(max(values), 1),
            "avg": round(sum(values) / len(values), 1)}


def _episodes(readings: List[Dict[str, Any]], label: str, key: str, is_abnormal, unit: str):
    """Group consecutive abnormal readings into episodes with start time and duration."""
    out, cur = [], None
    for r in readings:
        v = r.get(key)
        bad = v is not None and is_abnormal(v)
        t = _parse(r.get("timestamp"))
        if bad:
            if cur is None:
                cur = {"start": t, "end": t, "worst": v}
            cur["end"] = t
            cur["worst"] = min(cur["worst"], v) if label in ("SpO2", "low HR") else max(cur["worst"], v)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    res = []
    for e in out:
        secs = int((e["end"] - e["start"]).total_seconds()) if e["start"] and e["end"] else None
        res.append({
            "parameter": label,
            "start": e["start"].strftime("%H:%M:%S") if e["start"] else "--",
            "duration_s": secs,
            "worst": f"{round(e['worst'])}{unit}",
        })
    return res


def build_facts(readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    facts: Dict[str, Any] = {
        "reading_count": len(readings),
        "heart_rate": _stats([r["heart_rate"] for r in readings if r.get("heart_rate") is not None]),
        "spo2": _stats([r["spo2"] for r in readings if r.get("spo2") is not None]),
        "etco2": _stats([r["etco2"] for r in readings if r.get("etco2") is not None]),
        "bp_systolic": _stats([r["bp_systolic"] for r in readings if r.get("bp_systolic") is not None]),
        "bp_diastolic": _stats([r["bp_diastolic"] for r in readings if r.get("bp_diastolic") is not None]),
    }
    # Same thresholds as the report's alert logic (report_generator._abnormal_parameters)
    eps = []
    eps += _episodes(readings, "SpO2", "spo2", lambda v: v < 92, "%")
    eps += _episodes(readings, "high HR", "heart_rate", lambda v: v > 120, " bpm")
    eps += _episodes(readings, "low HR", "heart_rate", lambda v: v < 50, " bpm")
    eps += _episodes(readings, "EtCO2 low", "etco2", lambda v: v < 30, " mmHg")
    eps += _episodes(readings, "EtCO2 high", "etco2", lambda v: v > 45, " mmHg")
    facts["episodes"] = eps
    return facts


def _rule_based(facts: Dict[str, Any]) -> str:
    if not facts["reading_count"]:
        return "No readings were recorded for this case."
    parts = [f"{facts['reading_count']} readings were recorded."]
    for key, name, unit in (("heart_rate", "Heart rate", " bpm"), ("spo2", "SpO2", "%"), ("etco2", "EtCO2", " mmHg")):
        s = facts.get(key)
        if s:
            parts.append(f"{name} ranged {s['min']}-{s['max']}{unit} (mean {s['avg']}{unit}).")
    eps = facts["episodes"]
    if not eps:
        parts.append("No readings crossed the alert thresholds.")
    else:
        parts.append(f"{len(eps)} abnormal episode(s) were detected:")
        for e in eps:
            dur = f" lasting about {e['duration_s']} s" if e["duration_s"] is not None else ""
            parts.append(f"{e['parameter']} episode at {e['start']}{dur}, worst value {e['worst']}.")
    return " ".join(parts)


def _gemini(facts: Dict[str, Any]) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not api_key and not project:
        return None
    try:
        from google import genai
        client = (genai.Client(api_key=api_key) if api_key else
                  genai.Client(vertexai=True, project=project,
                               location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")))
        prompt = (
            "You are helping document an anaesthesia case. Using ONLY the facts in the JSON below, "
            "write a 3-4 sentence neutral clinical summary of the case's vital-sign course. "
            "Mention each abnormal episode with its start time and duration. "
            "Do not add numbers, diagnoses, causes or treatment advice that are not in the facts. "
            "Plain text, no markdown.\n\nFACTS:\n" + str(facts)
        )
        resp = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), contents=prompt)
        text = (resp.text or "").strip()
        return text or None
    except Exception as exc:  # never let the AI layer break report generation
        print(f"[AI SUMMARY] Gemini unavailable, using rule-based summary: {exc}")
        return None


def get_case_summary(case_id: str, readings: List[Dict[str, Any]]) -> Dict[str, str]:
    """Returns {"text": ..., "source": "Gemini" | "Rule-based"}. Cached per case and reading count."""
    key = (case_id, len(readings))
    if key in _cache:
        return _cache[key]
    facts = build_facts(readings)
    text = _gemini(facts)
    result = {"text": text, "source": "Gemini (Google Cloud)"} if text else \
             {"text": _rule_based(facts), "source": "Rule-based"}
    _cache[key] = result
    return result
