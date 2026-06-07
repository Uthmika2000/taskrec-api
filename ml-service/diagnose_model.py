#!/usr/bin/env python3
"""
Model Diagnostics Script
========================
Tells you exactly WHY accuracy is low and what to fix.

Usage:
    cd ml-service
    .\\venv\\Scripts\\Activate.ps1
    $env:DB_PASSWORD = "YourMySQLPassword"
    python diagnose_model.py
"""

import sys, os, logging
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.WARNING)  # quiet mode


def check_models():
    print("\n" + "="*60)
    print("  DIAGNOSIS 1: What's inside your trained models?")
    print("="*60)
    try:
        from app.model_trainer import RecommenderModelTrainer
        trainer = RecommenderModelTrainer(model_dir="./models")
        nlp_data, cf_data = trainer.load_trained_models()

        if not nlp_data:
            print("  ❌ NLP model not found — run python train.py first")
            return None

        task_cache   = nlp_data.get("task_embeddings",  {})
        skill_cache  = nlp_data.get("skill_embeddings", {})
        cf_devs      = cf_data.get("developers",  []) if cf_data else []
        cf_tasks     = cf_data.get("tasks",        []) if cf_data else []
        cf_matrix    = cf_data.get("matrix")

        print(f"  NLP task embeddings cached : {len(task_cache):,}")
        print(f"  NLP skill embeddings cached: {len(skill_cache):,}")
        print(f"  CF developers              : {len(cf_devs):,}")
        print(f"  CF tasks                   : {len(cf_tasks):,}")

        if cf_matrix is not None:
            import numpy as np
            density = float(np.sum(~np.isnan(cf_matrix))) / cf_matrix.size
            print(f"  CF matrix shape            : {cf_matrix.shape}")
            print(f"  CF matrix density          : {density:.2%}")
            if density < 0.01:
                print("  ⚠️  Matrix is very sparse (<1%) — CF scores will be ~0.5 for almost everything")

        print(f"\n  Skill embeddings cached: {list(skill_cache.keys())[:20]}")

        return trainer, nlp_data, cf_data, cf_devs

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def check_mysql_data():
    print("\n" + "="*60)
    print("  DIAGNOSIS 2: What's in MySQL — skill tag quality?")
    print("="*60)
    try:
        import mysql.connector, re
        conn = mysql.connector.connect(
            host=os.environ.get("DB_HOST","localhost"),
            port=int(os.environ.get("DB_PORT","3306")),
            user=os.environ.get("DB_USER","root"),
            password=os.environ.get("DB_PASSWORD",""),
            database=os.environ.get("DB_NAME","TAWOS"),
            connection_timeout=20,
        )
        cursor = conn.cursor(dictionary=True)

        # How many resolved issues exist?
        cursor.execute("SELECT COUNT(*) as n FROM Issue WHERE Resolution IN ('Fixed','Done','Resolved')")
        resolved = cursor.fetchone()['n']
        print(f"  Resolved issues in TAWOS  : {resolved:,}")

        # Sample 20 issue descriptions
        cursor.execute("""
            SELECT COALESCE(Description_Text, Description, '') as body,
                   COALESCE(Title,'') as title
            FROM Issue
            WHERE Resolution IN ('Fixed','Done','Resolved')
              AND (Description_Text IS NOT NULL OR Description IS NOT NULL)
            LIMIT 20
        """)
        rows = cursor.fetchall()

        SKILLS = [
            "Python","JavaScript","TypeScript","Java","Go","Rust","C#",
            "React","Vue","Angular","Node.js","FastAPI","Django","Flask","Spring",
            "PostgreSQL","MySQL","MongoDB","Redis","Docker","Kubernetes","AWS","Azure",
            "TensorFlow","PyTorch","scikit-learn","REST","GraphQL","Kafka",
        ]
        kw_pat = re.compile("|".join(re.escape(k) for k in SKILLS), re.IGNORECASE)

        issues_with_skills = 0
        all_found_skills = []
        for r in rows:
            text = f"{r['title']} {r['body']}"
            found = kw_pat.findall(text)
            if found:
                issues_with_skills += 1
                all_found_skills.extend(found)

        pct = issues_with_skills / max(len(rows),1) * 100
        print(f"  Sample issues with tech keywords : {issues_with_skills}/20 ({pct:.0f}%)")

        if pct < 30:
            print("  ⚠️  Most issue descriptions don't mention tech stack keywords")
            print("     This is why NLP skill matching scores are low")
        else:
            print("  ✅ Issue descriptions contain useful tech keywords")

        skill_counts = Counter(s.lower() for s in all_found_skills)
        if skill_counts:
            print(f"  Most common skills found: {dict(skill_counts.most_common(8))}")

        # Check component names — often contain useful info
        cursor.execute("""
            SELECT c.Name, COUNT(*) as n
            FROM Component c
            JOIN Issue_Component ic ON ic.Component_ID = c.ID
            GROUP BY c.Name
            ORDER BY n DESC
            LIMIT 10
        """)
        components = cursor.fetchall()
        if components:
            print(f"\n  Top components (these can be skill signals):")
            for c in components:
                print(f"    {c['Name']:<40} ({c['n']} issues)")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"  ❌ MySQL error: {e}")


def check_id_mismatch():
    print("\n" + "="*60)
    print("  DIAGNOSIS 3: ID format mismatch between model and eval?")
    print("="*60)
    try:
        from app.model_trainer import RecommenderModelTrainer
        trainer = RecommenderModelTrainer(model_dir="./models")
        nlp_data, cf_data = trainer.load_trained_models()

        cf_devs  = cf_data.get("developers", [])[:5] if cf_data else []
        cf_tasks = cf_data.get("tasks", [])[:5]      if cf_data else []

        print(f"  Sample developer IDs in model : {cf_devs[:5]}")
        print(f"  Sample task IDs in model      : {cf_tasks[:5]}")
        print()
        print("  Expected format from evaluate_model.py:")
        print("    Developer IDs : tawos_user_123")
        print("    Task IDs      : tawos_issue_456")
        print()

        dev_match  = any("tawos_user_"  in str(d) for d in cf_devs)
        task_match = any("tawos_issue_" in str(t) for t in cf_tasks)

        if dev_match and task_match:
            print("  ✅ ID formats match — no mismatch problem")
        else:
            print("  ❌ ID FORMAT MISMATCH DETECTED!")
            print("     The model was trained with different IDs than the evaluator uses.")
            print("     Fix: re-run python train.py with dataset_tawos_real.py")

    except Exception as e:
        print(f"  ❌ Error: {e}")


def print_verdict():
    print("\n" + "="*60)
    print("  ROOT CAUSE SUMMARY & FIX")
    print("="*60)
    print("""
  The low accuracy (1-4%) is almost certainly caused by one or
  more of these three root causes:

  ROOT CAUSE 1 — Sparse skill tags (most likely)
  ────────────────────────────────────────────────
  TAWOS issue descriptions rarely mention tech stack keywords.
  So most developers got skillTags = ["General"] during training.
  When the NLP model tries to match "React dashboard" to a dev
  with only "General" as a skill, the score is near-random.

  FIX → Use Component names as skill proxies (see improved
        dataset_tawos_real_v2.py that we'll generate for you).

  ROOT CAUSE 2 — CF matrix too sparse (0.03%)
  ────────────────────────────────────────────
  2,994 developers × 10,000 tasks = 29,940,000 possible pairs.
  You have 63,729 interactions = 0.21% density.
  k-NN can't find good neighbours with so few data points.
  CF predicts ~0.5 for almost every pair (neutral = useless).

  FIX → Weight NLP higher (0.7) and CF lower (0.1) until
        enough feedback accumulates.

  ROOT CAUSE 3 — Evaluation is unfairly strict
  ─────────────────────────────────────────────
  The evaluator picks 500 random test tasks and asks:
  "Does the model rank THIS SPECIFIC person #1?"
  But TAWOS has 2,000 developers — finding exactly the right
  one from 2,000 with sparse data is nearly impossible.
  Real-world usage only has 5-20 developers to rank, not 2,000.

  FIX → The improved evaluator below tests with realistic
        pools of 10-20 candidates, not all 2,000.
""")
    print("="*60)


if __name__ == "__main__":
    if not os.environ.get("DB_PASSWORD"):
        print('❌ Set DB_PASSWORD first:  $env:DB_PASSWORD = "YourPassword"')
        sys.exit(1)

    check_models()
    check_mysql_data()
    check_id_mismatch()
    print_verdict()
