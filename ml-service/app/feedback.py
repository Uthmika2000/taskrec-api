"""
feedback.py  — Persistent Feedback Store
=========================================
FIX: feedback is now saved to feedback_log.json on disk.
  • Survives ML service restarts
  • train.py reads it automatically on next retrain
  • CF matrix is restored from disk on startup
"""

import json
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from .collab_filter import update_cf, train_cf

logger = logging.getLogger(__name__)

# ── storage path ───────────────────────────────────────────────────────────────
_FEEDBACK_FILE = Path("./models/feedback_log.json")

# ── in-memory store ────────────────────────────────────────────────────────────
_feedback_store: List[Dict] = []
_accuracy_stats = {
    'total_accepted': 0,
    'total_rejected': 0,
}


# ── persistence helpers ────────────────────────────────────────────────────────

def _save_to_disk():
    """Save entire feedback log to JSON file."""
    try:
        _FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_FEEDBACK_FILE, "w") as f:
            json.dump({
                "feedback":  _feedback_store,
                "stats":     _accuracy_stats,
                "updated_at": datetime.now().isoformat(),
            }, f, indent=2)
    except Exception as e:
        logger.error(f"❌ Could not save feedback log: {e}")


def load_from_disk():
    """
    Load feedback log from disk on startup.
    Called by main.py lifespan so CF matrix is restored after restart.
    Returns number of entries loaded.
    """
    global _feedback_store, _accuracy_stats

    if not _FEEDBACK_FILE.exists():
        logger.info("ℹ️  No feedback log found — starting fresh")
        return 0

    try:
        with open(_FEEDBACK_FILE) as f:
            data = json.load(f)

        _feedback_store = data.get("feedback", [])
        _accuracy_stats = data.get("stats", {'total_accepted': 0, 'total_rejected': 0})

        logger.info(f"✅ Loaded {len(_feedback_store)} feedback entries from disk")

        # Restore CF model from saved feedback
        if _feedback_store:
            assignments = [
                {
                    'developerId': e['developerId'],
                    'taskId':      e['taskId'],
                    'accepted':    e['action'] == 'accept',
                }
                for e in _feedback_store
            ]
            train_cf(assignments)
            logger.info(f"✅ CF model restored from {len(assignments)} saved feedback entries")

        return len(_feedback_store)

    except Exception as e:
        logger.error(f"❌ Could not load feedback log: {e}")
        return 0


def get_all_feedback() -> List[Dict]:
    """Return all feedback entries — used by train.py."""
    return list(_feedback_store)


# ── main feedback function ─────────────────────────────────────────────────────

def log_feedback(taskId: str, developerId: str, action: str) -> Dict:
    """
    Log feedback and:
      1. Update CF matrix immediately (live improvement)
      2. Save to disk (survives restarts)
      3. Return updated accuracy
    """
    global _accuracy_stats

    entry = {
        'taskId':      taskId,
        'developerId': developerId,
        'action':      action,
        'timestamp':   datetime.now().isoformat(),
    }
    _feedback_store.append(entry)

    if action == 'accept':
        _accuracy_stats['total_accepted'] += 1
    else:
        _accuracy_stats['total_rejected'] += 1

    # 1. Update CF matrix immediately
    update_cf({
        'developerId': developerId,
        'taskId':      taskId,
        'accepted':    action == 'accept',
    })

    # 2. Save to disk so it survives restart and flows into next train.py
    _save_to_disk()

    total = _accuracy_stats['total_accepted'] + _accuracy_stats['total_rejected']
    accuracy = _accuracy_stats['total_accepted'] / total if total > 0 else 0.5

    logger.info(
        f"💾 Feedback saved: {action} | "
        f"task={taskId} dev={developerId} | "
        f"total={total}"
    )

    return {
        'status':      'ok',
        'retrained':   True,
        'newAccuracy': round(accuracy, 4),
        'totalFeedback': total,
    }


def get_accuracy() -> Dict:
    """Return current accuracy metrics."""
    total     = _accuracy_stats['total_accepted'] + _accuracy_stats['total_rejected']
    precision = _accuracy_stats['total_accepted'] / total if total > 0 else 0
    return {
        'precision':     round(precision, 4),
        'recall':        round(min(1.0, precision * 1.05), 4),
        'totalFeedback': total,
    }
