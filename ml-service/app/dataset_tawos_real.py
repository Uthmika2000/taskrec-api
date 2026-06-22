"""
Real TAWOS + Stack Overflow Dataset Loader
==========================================
Replaces the TAWOSSimulator with a real MySQL reader that queries your
TAWOS database (the schema you provided in tawos.sql).

It produces the same interface as CombinedDataset so you can drop it
straight into train.py / recommender_v2.py without changing anything else.

HOW TO GET THE DATA
───────────────────
1. TAWOS (MySQL)
   • Clone  : https://github.com/SOLAR-group/TAWOS
   • Follow the README to restore the SQL dump into MySQL/MariaDB.
   • Set the four DB_ env-vars (or edit defaults below) and run train.py.

2. Stack Overflow Survey (Kaggle)
   • URL    : https://www.kaggle.com/datasets/berkayalan/
               stack-overflow-annual-developer-survey-2024
   • Option A (automatic) — set KAGGLE_USERNAME + KAGGLE_KEY env-vars,
     and kagglehub downloads it on first run.
   • Option B (manual)    — download the ZIP, unzip to ./data/so_survey/,
     and set SO_CSV_PATH to the path of the main .csv file.

USAGE
─────
# Instead of dataset_v2.py / CombinedDataset use:
from app.dataset_tawos_real import RealCombinedDataset

dataset = RealCombinedDataset(
    db_host="localhost", db_port=3306,
    db_user="root",      db_password="yourpassword",
    db_name="TAWOS",
    so_profile_limit=1000,
)
combined   = dataset.build()
developers = dataset.get_all_developers()
tasks      = dataset.get_all_tasks()
assignments= dataset.get_all_assignments()

# Then pass to the existing trainer exactly as before:
from app.model_trainer import RecommenderModelTrainer
trainer = RecommenderModelTrainer(model_dir="./models")
trainer.train_full_pipeline(developers, tasks, assignments)
"""

import os
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove Jira/Confluence wiki markup and HTML tags from descriptions."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)          # HTML tags
    text = re.sub(r"\{[^}]+\}", " ", text)          # {code}, {panel}, etc.
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]                               # cap at 2 000 chars


# ─────────────────────────────────────────────────────────────────────────────
# TAWOS MySQL reader
# ─────────────────────────────────────────────────────────────────────────────

class TAWOSRealDataset:
    """
    Reads from a real TAWOS MySQL database.

    Schema assumptions (from your tawos.sql):
      Issue   : ID, Issue_Key, Title, Description_Text, Type,
                Priority, Status, Resolution, Story_Point,
                Creator_ID, Reporter_ID, Assignee_ID, Project_ID, Sprint_ID
      User    : ID, Project_ID
      Project : ID, Name
      Comment : Issue_ID, Comment_Text, Author_ID
      Change_Log : Issue_ID, Field, To_String, Author_ID, Creation_Date

    Developer skill tags are inferred from:
      • programming languages / tech mentioned in issues they resolved
      • component names attached to resolved issues
      • project names
    """

    # SQL skill keywords to look for in issue text
    SKILL_KEYWORDS = [
        "Python", "JavaScript", "TypeScript", "Java", "C#", "C++", "Go",
        "Rust", "Kotlin", "Swift", "Ruby", "PHP", "Scala",
        "React", "Vue", "Angular", "Next.js", "Svelte",
        "Node.js", "Express", "FastAPI", "Django", "Flask",
        "Spring", "ASP.NET", "Laravel",
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
        "SQLite", "Cassandra", "DynamoDB", "Firebase",
        "AWS", "Azure", "GCP", "Docker", "Kubernetes",
        "Terraform", "Ansible", "Jenkins", "GitHub Actions",
        "TensorFlow", "PyTorch", "scikit-learn", "Pandas", "NumPy",
        "React Native", "Flutter", "iOS", "Android",
        "REST", "GraphQL", "gRPC", "WebSocket",
        "Kafka", "RabbitMQ", "Airflow",
        "Jest", "Pytest", "Cypress", "Selenium", "Playwright",
        "OAuth", "JWT", "OWASP",
        "Git", "Linux", "Bash", "SQL", "Agile", "Scrum",
    ]

    def __init__(
        self,
        host: str     = "localhost",
        port: int     = 3306,
        user: str     = "root",
        password: str = "",
        db_name: str  = "TAWOS",
        max_issues: int    = 10_000,   # cap to avoid OOM on huge datasets
        max_developers: int = 2_000,
    ):
        self.host           = host
        self.port           = port
        self.user           = user
        self.password       = password
        self.db_name        = db_name
        self.max_issues     = max_issues
        self.max_developers = max_developers

        self._developers: List[Dict] = []
        self._tasks:       List[Dict] = []
        self._assignments: List[Dict] = []

    # ------------------------------------------------------------------
    def _connect(self):
        """Return a live MySQL connection (requires mysql-connector-python)."""
        try:
            import mysql.connector
        except ImportError:
            raise ImportError(
                "mysql-connector-python not installed.\n"
                "Run:  pip install mysql-connector-python"
            )
        conn = mysql.connector.connect(
            host=self.host, port=self.port,
            user=self.user, password=self.password,
            database=self.db_name,
            connection_timeout=30,
        )
        logger.info(f"Connected to MySQL: {self.db_name} @ {self.host}:{self.port}")
        return conn

    # ------------------------------------------------------------------
    def load(self) -> Dict:
        conn = self._connect()
        try:
            self._developers  = self._load_developers(conn)
            self._tasks       = self._load_tasks(conn)
            self._assignments = self._load_assignments(conn)
        finally:
            conn.close()

        logger.info(
            f"TAWOS loaded — "
            f"{len(self._developers)} devs, "
            f"{len(self._tasks)} tasks, "
            f"{len(self._assignments)} assignments"
        )
        return {
            "developers":  self._developers,
            "tasks":       self._tasks,
            "assignments": self._assignments,
        }

    # ------------------------------------------------------------------
    def _load_developers(self, conn) -> List[Dict]:
        """
        Load developers (Users) who have been assigned at least one issue.
        Infer skill tags from the text of issues they resolved.
        """
        cursor = conn.cursor(dictionary=True)

        # Step 1: Get users who were assignees
        cursor.execute(f"""
            SELECT DISTINCT u.ID as user_id
            FROM   User u
            JOIN   Issue i ON i.Assignee_ID = u.ID
            LIMIT  {self.max_developers}
        """)
        user_rows = cursor.fetchall()
        logger.info(f"   Found {len(user_rows)} assignee users in TAWOS")

        # Step 2: For each user, collect issue text to infer skills
        kw_pattern = re.compile(
            "|".join(re.escape(k) for k in self.SKILL_KEYWORDS),
            re.IGNORECASE
        )

        developers = []
        for row in user_rows:
            uid = row["user_id"]

            # Fetch titles + descriptions of issues this user resolved
            cursor.execute("""
                SELECT COALESCE(i.Title, '') as title,
                       COALESCE(i.Description_Text, '') as body
                FROM   Issue i
                WHERE  i.Assignee_ID = %s
                  AND  i.Status IN ('Done','Resolved','Closed')
                LIMIT  50
            """, (uid,))
            issue_rows = cursor.fetchall()

            raw_text = " ".join(
                f"{r['title']} {r['body']}" for r in issue_rows
            )
            found = kw_pattern.findall(raw_text)
            skills = list({s.title() for s in found})[:15]  # dedupe, cap 15

            developers.append({
                "id":   f"tawos_user_{uid}",
                "name": f"TAWOS_User_{uid}",
                "skills": skills or ["General"],
                "experience_years": 0,   # not available in TAWOS schema
                "source": "tawos",
            })

        cursor.close()
        return developers

    # ------------------------------------------------------------------
    def _load_tasks(self, conn) -> List[Dict]:
        """
        Load issues as tasks.
        Uses Description_Text (plain text) if available, else Description.
        """
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT i.ID, i.Issue_Key, i.Title,
                   COALESCE(i.Description_Text, i.Description, '') AS body,
                   i.Type, i.Priority, i.Status, i.Story_Point,
                   i.Resolution
            FROM   Issue i
            WHERE  i.Title IS NOT NULL
            LIMIT  {self.max_issues}
        """)
        rows = cursor.fetchall()
        cursor.close()

        tasks = []
        for r in rows:
            raw_desc = _strip_html(r["body"])
            title    = (r["Title"] or "").strip()
            description = f"{title}. {raw_desc}".strip() if raw_desc else title

            tasks.append({
                "id":          f"tawos_issue_{r['ID']}",
                "title":       title,
                "description": description,
                "type":        r["Type"] or "Task",
                "priority":    r["Priority"] or "Medium",
                "status":      r["Status"] or "Open",
                "story_points": float(r["Story_Point"] or 0),
                "resolved":    r["Resolution"] in ("Fixed", "Done", "Resolved"),
                "source":      "tawos",
            })

        logger.info(f"   Loaded {len(tasks)} issues from TAWOS as tasks")
        return tasks

    # ------------------------------------------------------------------
    def _load_assignments(self, conn) -> List[Dict]:
        """
        Build assignment records from:
          • Issues where an Assignee is set  → real assignments
          • Change_Log rows where Field='assignee' → historical re-assignments
        accepted = True  if the issue was ultimately resolved/done
                   False otherwise
        """
        cursor = conn.cursor(dictionary=True)

        # Direct assignments (Assignee_ID on Issue)
        cursor.execute(f"""
            SELECT i.ID        AS issue_id,
                   i.Assignee_ID AS user_id,
                   i.Status,
                   i.Resolution
            FROM   Issue i
            WHERE  i.Assignee_ID IS NOT NULL
            LIMIT  {self.max_issues}
        """)
        direct = cursor.fetchall()

        assignments = []
        for r in direct:
            accepted = r["Resolution"] in ("Fixed", "Done", "Resolved") \
                       or r["Status"] in ("Done", "Resolved", "Closed")
            assignments.append({
                "developer_id": f"tawos_user_{r['user_id']}",
                "task_id":      f"tawos_issue_{r['issue_id']}",
                "accepted":     bool(accepted),
                "source":       "tawos_direct",
            })

        # Historical re-assignments from Change_Log
        cursor.execute(f"""
            SELECT cl.Issue_ID, cl.Author_ID, cl.To_String,
                   i.Resolution, i.Status
            FROM   Change_Log cl
            JOIN   Issue i ON i.ID = cl.Issue_ID
            WHERE  cl.Field = 'assignee'
              AND  cl.Author_ID IS NOT NULL
            LIMIT  50000
        """)
        changelog = cursor.fetchall()
        cursor.close()

        for r in changelog:
            accepted = r["Resolution"] in ("Fixed", "Done", "Resolved") \
                       or r["Status"] in ("Done", "Resolved", "Closed")
            assignments.append({
                "developer_id": f"tawos_user_{r['Author_ID']}",
                "task_id":      f"tawos_issue_{r['Issue_ID']}",
                "accepted":     bool(accepted),
                "source":       "tawos_changelog",
            })

        logger.info(
            f"   Loaded {len(direct)} direct + "
            f"{len(changelog)} changelog assignments"
        )
        return assignments

    # Accessors (same interface as TAWOSSimulator)
    def get_developers(self)  -> List[Dict]: return self._developers
    def get_tasks(self)       -> List[Dict]: return self._tasks
    def get_assignments(self) -> List[Dict]: return self._assignments


# ─────────────────────────────────────────────────────────────────────────────
# Kaggle Stack Overflow loader  (same as dataset_v2 but with fallback path)
# ─────────────────────────────────────────────────────────────────────────────

class SOSurveyDataset:
    """
    Loads the Stack Overflow Annual Developer Survey from Kaggle.

    Two ways to provide the data:
      A) Automatic  – set KAGGLE_USERNAME + KAGGLE_KEY in your environment
         and the dataset is downloaded via kagglehub on first run.
      B) Manual     – download the ZIP from Kaggle yourself, unzip it,
         and set the env-var SO_CSV_PATH to the absolute path of the CSV.

    The CSV should be the primary survey responses file (usually named
    "survey_results_public.csv" or similar).
    """

    KAGGLE_DATASET = "berkayalan/stack-overflow-annual-developer-survey-2024"

    def __init__(self, cache_dir: str = "./data/so_survey"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.df: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    def _find_csv(self, root: Path) -> Optional[Path]:
        """Return the first .csv file found under root."""
        candidates = sorted(root.glob("**/*.csv"))
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    def load(self) -> Optional[pd.DataFrame]:
        # Option B: manual path
        manual_path = os.environ.get("SO_CSV_PATH")
        if manual_path:
            csv_path = Path(manual_path)
            if csv_path.exists():
                logger.info(f"Loading SO survey from manual path: {csv_path}")
                self.df = pd.read_csv(csv_path, low_memory=False)
                logger.info(f"SO survey loaded: {self.df.shape[0]:,} rows")
                return self.df
            else:
                logger.warning(f"SO_CSV_PATH set but file not found: {csv_path}")

        # Option A: automatic via kagglehub
        try:
            import kagglehub
            logger.info(f"Downloading SO survey from Kaggle: {self.KAGGLE_DATASET}")
            dl_path = kagglehub.dataset_download(self.KAGGLE_DATASET)
            csv_path = self._find_csv(Path(dl_path))
            if csv_path:
                self.df = pd.read_csv(csv_path, low_memory=False)
                logger.info(f"SO survey downloaded and loaded: {self.df.shape[0]:,} rows")
                return self.df
            else:
                logger.warning("No CSV found in Kaggle download")
        except Exception as e:
            logger.warning(f"Kaggle download failed: {e}")
            logger.info(
                "   To fix: set KAGGLE_USERNAME + KAGGLE_KEY env-vars,\n"
                "   OR download manually and set SO_CSV_PATH."
            )

        return None

    # ------------------------------------------------------------------
    def get_developer_profiles(self, limit: int = 1000) -> List[Dict]:
        if self.df is None:
            self.load()
        if self.df is None:
            logger.warning("SO data unavailable — skipping SO profiles")
            return []

        skill_cols = [
            c for c in self.df.columns
            if any(kw in c for kw in [
                "LanguageHaveWorkedWith",
                "WebframeHaveWorkedWith",
                "DatabaseHaveWorkedWith",
                "ToolsTechHaveWorkedWith",
                "PlatformHaveWorkedWith",
                "MiscTechHaveWorkedWith",
            ])
        ]

        profiles: List[Dict] = []
        for idx, row in self.df.iterrows():
            if idx >= limit:
                break

            skills: List[str] = []
            for col in skill_cols:
                raw = row.get(col)
                if pd.notna(raw):
                    skills.extend(str(raw).split(";"))

            skills = list({s.strip() for s in skills if s.strip()})[:20]
            if not skills:
                continue

            yc = row.get("YearsCodePro", row.get("YearsCode", 0))
            try:
                years_exp = int(float(yc)) if pd.notna(yc) else 0
            except Exception:
                years_exp = 0

            profiles.append({
                "id":               f"so_dev_{idx}",
                "name":             f"SO_Dev_{idx}",
                "skills":           skills,
                "experience_years": max(0, years_exp),
                "developer_type":   str(row.get("DevType", "Developer")),
                "country":          str(row.get("Country", "Unknown")),
                "employment":       str(row.get("Employment", "Unknown")),
                "source":           "stackoverflow",
            })

        logger.info(f"Extracted {len(profiles)} SO developer profiles")
        return profiles

    # ------------------------------------------------------------------
    def get_training_assignments(self, limit: int = 500) -> List[Dict]:
        """
        Create synthetic assignment records from SO profiles
        (same heuristic as dataset_v2.py).
        """
        profiles = self.get_developer_profiles(limit)
        records: List[Dict] = []
        rng = np.random.default_rng(42)
        for idx, profile in enumerate(profiles):
            for skill_idx in range(min(len(profile["skills"]), 8)):
                records.append({
                    "developer_id": profile["id"],
                    "task_id":      f"so_task_{idx}_{skill_idx}",
                    "accepted":     bool(rng.choice([True, False], p=[0.7, 0.3])),
                    "source":       "stackoverflow",
                })
        return records


# ─────────────────────────────────────────────────────────────────────────────
# Combined dataset  (same public API as CombinedDataset in dataset_v2.py)
# ─────────────────────────────────────────────────────────────────────────────

class RealCombinedDataset:
    """
    Drop-in replacement for CombinedDataset that uses:
      • Real TAWOS MySQL data  instead of the TAWOSSimulator
      • Real Kaggle SO data    (same as before)

    Constructor reads DB credentials from keyword args OR env-vars:
      DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
    """

    def __init__(
        self,
        db_host:     str = None,
        db_port:     int = None,
        db_user:     str = None,
        db_password: str = None,
        db_name:     str = None,
        use_stackoverflow:  bool = True,
        so_profile_limit:   int  = 1000,
        so_training_limit:  int  = 500,
        max_issues:         int  = 10_000,
        max_developers:     int  = 2_000,
    ):
        self.tawos = TAWOSRealDataset(
            host     = db_host     or os.environ.get("DB_HOST",     "localhost"),
            port     = db_port     or int(os.environ.get("DB_PORT", "3306")),
            user     = db_user     or os.environ.get("DB_USER",     "root"),
            password = db_password or os.environ.get("DB_PASSWORD", ""),
            db_name  = db_name     or os.environ.get("DB_NAME",     "TAWOS"),
            max_issues     = max_issues,
            max_developers = max_developers,
        )
        self.so = SOSurveyDataset() if use_stackoverflow else None
        self.so_profile_limit  = so_profile_limit
        self.so_training_limit = so_training_limit
        self.use_stackoverflow = use_stackoverflow

        self._so_profiles:    List[Dict] = []
        self._so_assignments: List[Dict] = []

    # ------------------------------------------------------------------
    def build(self) -> Dict:
        logger.info("Building REAL combined dataset (TAWOS + SO)...")

        # 1. Load real TAWOS data
        logger.info("Step 1: Loading real TAWOS MySQL data...")
        tawos_data = self.tawos.load()

        # 2. Load Stack Overflow data
        if self.use_stackoverflow and self.so is not None:
            logger.info("Step 2: Loading Stack Overflow survey data...")
            self.so.load()
            self._so_profiles    = self.so.get_developer_profiles(self.so_profile_limit)
            self._so_assignments = self.so.get_training_assignments(self.so_training_limit)
        else:
            logger.info("Stack Overflow data skipped")

        logger.info(
            f"Dataset ready — "
            f"TAWOS: {len(tawos_data['developers'])} devs / "
            f"{len(tawos_data['tasks'])} tasks / "
            f"{len(tawos_data['assignments'])} assignments | "
            f"SO: {len(self._so_profiles)} profiles"
        )
        return {"tawos": tawos_data, "stackoverflow": {"profiles": self._so_profiles}}

    # ------------------------------------------------------------------
    def get_all_developers(self) -> List[Dict]:
        devs = list(self.tawos.get_developers())
        for p in self._so_profiles:
            devs.append({
                "id":               p["id"],
                "name":             p["name"],
                "skills":           p["skills"],
                "experience_years": p["experience_years"],
                "source":           "stackoverflow",
            })
        return devs

    def get_all_tasks(self) -> List[Dict]:
        return list(self.tawos.get_tasks())

    def get_all_assignments(self) -> List[Dict]:
        assignments = list(self.tawos.get_assignments())
        assignments.extend(self._so_assignments)
        return assignments
