#!/usr/bin/env python3
"""
Local Model Training Script - NO COLAB REQUIRED

Trains the recommendation models using REAL data:
1. Loads real TAWOS data from MySQL database
2. Fetches Stack Overflow survey data from Kaggle
3. Merges saved feedback from feedback_log.json (if exists)  ← NEW
4. Trains NLP and Collaborative Filtering models
5. Saves models for production use

Usage:
    cd ml-service
    python train.py [options]

Options:
    --skip-so           Skip Stack Overflow data
    --so-profiles INT   Stack Overflow profiles      (default: 1000)
    --output-dir PATH   Model output directory       (default: ./models)
    --max-issues  INT   Max TAWOS issues to load     (default: 10000)
    --max-devs    INT   Max TAWOS developers to load (default: 2000)

Required Environment Variables:
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
"""

import sys
import logging
import argparse
import os
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.dataset_tawos_real import RealCombinedDataset
from app.model_trainer import RecommenderModelTrainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── path to saved feedback ─────────────────────────────────────────────────────
FEEDBACK_LOG = Path("./models/feedback_log.json")


def check_env():
    if not os.environ.get("DB_PASSWORD"):
        logger.warning("="*70)
        logger.warning("⚠️  DB_PASSWORD not set!")
        logger.warning("   Windows : $env:DB_PASSWORD = 'your_password'")
        logger.warning("   Mac/Linux: export DB_PASSWORD=your_password")
        logger.warning("="*70)
        return False
    return True


def load_saved_feedback() -> list:
    """
    Load feedback that was saved to disk by feedback.py.
    Converts it into assignment format for CF training.
    Returns empty list if no feedback file exists yet.
    """
    if not FEEDBACK_LOG.exists():
        logger.info("ℹ️  No feedback_log.json found — training without feedback")
        return []

    try:
        with open(FEEDBACK_LOG) as f:
            data = json.load(f)

        entries = data.get("feedback", [])
        if not entries:
            return []

        # Convert feedback entries → assignment records
        assignments = []
        for e in entries:
            assignments.append({
                "developer_id": e.get("developerId", ""),
                "task_id":      e.get("taskId", ""),
                "accepted":     e.get("action") == "accept",
                "source":       "feedback",
            })

        logger.info(f"✅ Loaded {len(assignments)} feedback assignments from disk")
        accepted = sum(1 for a in assignments if a["accepted"])
        rejected = len(assignments) - accepted
        logger.info(f"   Accepted: {accepted}  |  Rejected: {rejected}")
        return assignments

    except Exception as e:
        logger.warning(f"⚠️  Could not load feedback log: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description='Train with real TAWOS + Kaggle + saved feedback')
    parser.add_argument('--skip-so',     action='store_true')
    parser.add_argument('--so-profiles', type=int, default=1000)
    parser.add_argument('--output-dir',  type=str, default='./models')
    parser.add_argument('--max-issues',  type=int, default=10000)
    parser.add_argument('--max-devs',    type=int, default=2000)
    args = parser.parse_args()

    logger.info("="*70)
    logger.info("🚀 AI Agile Task Recommendation System — Model Training")
    logger.info("="*70)
    logger.info(f"   DB      : {os.environ.get('DB_USER','root')}@"
                f"{os.environ.get('DB_HOST','localhost')}/"
                f"{os.environ.get('DB_NAME','TAWOS')}")
    logger.info(f"   Issues  : {args.max_issues}  |  Devs: {args.max_devs}")
    logger.info(f"   SO Data : {'skipped' if args.skip_so else f'{args.so_profiles} profiles'}")
    logger.info(f"   Output  : {args.output_dir}")
    logger.info("="*70)

    if not check_env():
        return False

    # ── STEP 1: Build dataset ──────────────────────────────────────────────────
    logger.info("\n📊 STEP 1: Building Training Dataset")
    logger.info("-"*70)

    dataset = RealCombinedDataset(
        use_stackoverflow  = not args.skip_so,
        so_profile_limit   = args.so_profiles,
        so_training_limit  = max(100, args.so_profiles // 2),
        max_issues         = args.max_issues,
        max_developers     = args.max_devs,
    )

    try:
        dataset.build()
        developers  = dataset.get_all_developers()
        tasks       = dataset.get_all_tasks()
        assignments = dataset.get_all_assignments()

        logger.info(f"\n   From TAWOS + Stack Overflow:")
        logger.info(f"   Developers  : {len(developers)}")
        logger.info(f"   Tasks       : {len(tasks)}")
        logger.info(f"   Assignments : {len(assignments)}")

        if not tasks or not developers:
            logger.error("❌ No data loaded. Check MySQL connection.")
            return False

    except Exception as e:
        logger.error(f"❌ Dataset build failed: {e}")
        import traceback; traceback.print_exc()
        return False

    # ── STEP 1b: Merge saved feedback ─────────────────────────────────────────
    logger.info("\n💬 STEP 1b: Loading saved feedback from disk...")
    logger.info("-"*70)

    feedback_assignments = load_saved_feedback()

    if feedback_assignments:
        # Merge feedback into assignments list
        assignments = assignments + feedback_assignments
        logger.info(f"   Total assignments after feedback merge: {len(assignments)}")
        logger.info(f"   (TAWOS + SO: {len(assignments) - len(feedback_assignments)}  |  "
                    f"Feedback: {len(feedback_assignments)})")
    else:
        logger.info("   No saved feedback yet — will improve after PMs start using the system")

    # ── STEP 2: Train models ───────────────────────────────────────────────────
    logger.info("\n🔨 STEP 2: Training Models")
    logger.info("-"*70)

    try:
        trainer = RecommenderModelTrainer(model_dir=args.output_dir)
        result  = trainer.train_full_pipeline(developers, tasks, assignments)

        if result['success']:
            meta = result['metadata']
            logger.info("✅ Training successful!")
            logger.info(f"\n📈 Training Report:")
            logger.info(f"   Timestamp         : {meta['timestamp']}")
            logger.info(f"   Duration          : {meta['training_time_seconds']:.1f}s")
            logger.info(f"   NLP cached tasks  : {meta['nlp_cached_tasks']}")
            logger.info(f"   NLP cached skills : {meta['nlp_cached_skills']}")
            logger.info(f"   CF matrix shape   : {meta['cf_matrix_shape']}")
            logger.info(f"   CF matrix density : {meta['cf_matrix_density']:.2%}")
            if feedback_assignments:
                logger.info(f"   Feedback included : {len(feedback_assignments)} entries ✅")
        else:
            logger.error("❌ Training failed")
            return False

    except Exception as e:
        logger.error(f"❌ Training error: {e}")
        import traceback; traceback.print_exc()
        return False

    # ── STEP 3: Verify ────────────────────────────────────────────────────────
    logger.info("\n✅ STEP 3: Verifying Models")
    logger.info("-"*70)

    try:
        nlp_data, cf_data = trainer.load_trained_models()
        if nlp_data and cf_data:
            logger.info("✅ Models verified and loaded successfully!")
        else:
            logger.warning("⚠️  Some models failed to load")
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        return False

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n" + "="*70)
    logger.info("✅ MODEL TRAINING COMPLETE")
    logger.info("="*70)
    logger.info(f"\n📦 Models saved to  : {args.output_dir}")
    logger.info(f"💬 Feedback log     : {FEEDBACK_LOG}")
    logger.info(f"\n🚀 Next steps:")
    logger.info(f"   $env:MODEL_DIR = '{args.output_dir}'")
    logger.info(f"   python -m uvicorn app.main:app --reload")
    logger.info("="*70)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
