from collections import deque
import re
import statistics
from typing import Any, Dict, List, Optional, Union

# In-memory rolling history for last 5 valid readings per field_type
_history: Dict[str, List[Union[int, float, str]]] = {}


def get_smoothed_value(field_type: str, new_value: Any) -> Optional[Union[int, float, str]]:
    """
    Returns the fresh new_value directly for instant real-time optical updates.
    """
    if field_type not in _history:
        _history[field_type] = []

    if new_value is not None:
        _history[field_type] = [new_value]
        return new_value

    if _history[field_type]:
        return _history[field_type][-1]

    return None


def clear_field_history(field_type: str):
    """Clears history for a specific field_type (e.g. when switching from fallback to real AI)."""
    if field_type in _history:
        _history[field_type].clear()


def reset_history():
    """Clears history dictionary (mainly for testing/resetting state)."""
    _history.clear()
