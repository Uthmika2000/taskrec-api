"""
Real TAWOS + Stack Overflow Dataset Loader  (v3 — split queries, no OOM)
=========================================================================
Fix from v2: replaced the single heavy GROUP BY + GROUP_CONCAT query
with two lightweight queries — avoids MySQL sort buffer OOM error.

Query 1: load issues in batches (no JOIN, no GROUP BY)
Query 2: load component names separately, merge in Python
"""

import os, re, logging
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Skill keywords ─────────────────────────────────────────────────────────────
SKILLS = [
    "Python","JavaScript","TypeScript","Java","Go","Rust","C#","C++","Kotlin","Swift",
    "Ruby","PHP","Scala","Dart","R",
    "React","Vue","Angular","Next.js","Svelte","Node.js","Express",
    "FastAPI","Django","Flask","Spring","ASP.NET","Laravel","Rails",
    "PostgreSQL","MySQL","MongoDB","Redis","Elasticsearch","SQLite",
    "Cassandra","DynamoDB","Firebase","Oracle",
    "AWS","Azure","GCP","Docker","Kubernetes","Terraform","Ansible",
    "Jenkins","GitHub Actions","Linux","Bash","Git",
    "TensorFlow","PyTorch","scikit-learn","Pandas","NumPy","Spark","Kafka","Airflow",
    "React Native","Flutter","iOS","Android",
    "REST","GraphQL","gRPC","OAuth","JWT",
    "Jest","Pytest","Cypress","Selenium",
    "Sharding","Replication","Indexing","Aggregation","Querying",
]
KW_PAT = re.compile("|".join(re.escape(k) for k in SKILLS), re.IGNORECASE)

# Component name → skill tag
COMPONENT_MAP = {
    "ios":"iOS","android":"Android","mobile":"React Native",
    "sharding":"Sharding","replication":"Replication","querying":"Querying",
    "indexing":"Indexing","aggregation":"Aggregation","storage":"Storage",
    "administration":"Administration","security":"Security",
    "authentication":"OAuth","api":"REST","ui":"JavaScript",
    "frontend":"JavaScript","backend":"Python","app":"Mobile",
    "quiz":"JavaScript","documentation":"Documentation",
    "test":"Testing","testing":"Testing","performance":"Performance",
    "network":"Networking","cloud":"AWS","deploy":"Docker","devops":"Kubernetes",
}

def _map_component(name: str) -> str:
    key = name.strip().lower()
    return COMPONENT_MAP.get(key, name.strip().title())

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\{[^}]+\}", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:500]

def _infer_skills(text: str) -> List[str]:
    return list({s.title() for s in KW_PAT.findall(text)})


# ── TAWOS MySQL reader ─────────────────────────────────────────────────────────

class TAWOSRealDataset:

    def __init__(
        self,
        host="localhost", port=3306, user="root", password="", db_name="TAWOS",
        max_issues=10_000, max_developers=2_000, batch_size=2_000,
    ):
        self.host, self.port   = host, port
        self.user, self.password = user, password
        self.db_name           = db_name
        self.max_issues        = max_issues
        self.max_developers    = max_developers
        self.batch_size        = batch_size          # rows per query — keeps memory low

        self._developers:  List[Dict] = []
        self._tasks:       List[Dict] = []
        self._assignments: List[Dict] = []

    # ── connection ─────────────────────────────────────────────────────────────
    def _connect(self):
        try:
            import mysql.connector
        except ImportError:
            raise ImportError("Run:  pip install mysql-connector-python")
        conn = mysql.connector.connect(
            host=self.host, port=self.port,
            user=self.user, password=self.password,
            database=self.db_name, connection_timeout=30,
        )
        logger.info(f"✅ Connected to MySQL: {self.db_name} @ {self.host}:{self.port}")
        return conn

    # ── public ─────────────────────────────────────────────────────────────────
    def load(self) -> Dict:
        conn = self._connect()
        try:
            # Step A: load issues in small batches (no JOIN, no GROUP BY)
            all_rows = self._load_issues_batched(conn)
            logger.info(f"   Loaded {len(all_rows):,} issues")

            # Step B: load issue→component mapping separately
            issue_ids   = [r['issue_id'] for r in all_rows]
            comp_map    = self._load_components(conn, issue_ids)
            logger.info(f"   Loaded components for {len(comp_map):,} issues")

            # Step C: load project names separately
            proj_map    = self._load_projects(conn)
            logger.info(f"   Loaded {len(proj_map):,} project names")

        finally:
            conn.close()

        # Step D: build tasks / developers / assignments in Python
        self._tasks, self._developers, self._assignments = \
            self._build_records(all_rows, comp_map, proj_map)

        logger.info(
            f"✅ TAWOS loaded — "
            f"{len(self._developers)} devs, "
            f"{len(self._tasks)} tasks, "
            f"{len(self._assignments)} assignments"
        )
        return {
            "developers":  self._developers,
            "tasks":       self._tasks,
            "assignments": self._assignments,
        }

    # ── query A: issues in batches ────────────────────────────────────────────
    def _load_issues_batched(self, conn) -> List[Dict]:
        """
        Load issues in small batches using LIMIT + OFFSET.
        No JOIN, no GROUP BY → no sort-buffer OOM.
        """
        cursor = conn.cursor(dictionary=True)
        all_rows = []
        offset   = 0

        while len(all_rows) < self.max_issues:
            fetch = min(self.batch_size, self.max_issues - len(all_rows))
            cursor.execute(f"""
                SELECT
                    ID          AS issue_id,
                    Assignee_ID AS user_id,
                    Project_ID  AS project_id,
                    COALESCE(Title, '')                            AS title,
                    COALESCE(Description_Text, Description, '')   AS body,
                    COALESCE(Type, 'Task')       AS type,
                    COALESCE(Priority, 'Medium') AS priority,
                    COALESCE(Status, 'Open')     AS status,
                    COALESCE(Resolution, '')     AS resolution,
                    COALESCE(Story_Point, 0)     AS story_points
                FROM Issue
                WHERE Assignee_ID IS NOT NULL
                  AND Title IS NOT NULL
                LIMIT {fetch} OFFSET {offset}
            """)
            batch = cursor.fetchall()
            if not batch:
                break
            all_rows.extend(batch)
            offset += len(batch)
            if len(batch) < fetch:
                break

        cursor.close()
        return all_rows

    # ── query B: components (batched by issue IDs) ───────────────────────────
    def _load_components(self, conn, issue_ids: List[int]) -> Dict[int, List[str]]:
        """
        Returns {issue_id: [component_name, ...]}
        Queries in chunks of 1,000 IDs to stay within MySQL limits.
        """
        if not issue_ids:
            return {}

        cursor   = conn.cursor(dictionary=True)
        comp_map = defaultdict(list)
        chunk_sz = 1_000

        for i in range(0, len(issue_ids), chunk_sz):
            chunk = issue_ids[i : i + chunk_sz]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(f"""
                SELECT ic.Issue_ID, c.Name
                FROM   Issue_Component ic
                JOIN   Component c ON c.ID = ic.Component_ID
                WHERE  ic.Issue_ID IN ({placeholders})
                  AND  c.Name IS NOT NULL
            """, chunk)
            for row in cursor.fetchall():
                comp_map[row['Issue_ID']].append(row['Name'])

        cursor.close()
        return dict(comp_map)

    # ── query C: project names ────────────────────────────────────────────────
    def _load_projects(self, conn) -> Dict[int, str]:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT ID, COALESCE(Name,'') AS name FROM Project")
        result = {r['ID']: r['name'] for r in cursor.fetchall()}
        cursor.close()
        return result

    # ── Step D: build final records in Python ─────────────────────────────────
    def _build_records(self, rows, comp_map, proj_map):
        dev_skill_text  = defaultdict(set)
        dev_skill_comp  = defaultdict(set)
        dev_skill_proj  = defaultdict(set)
        dev_issue_count = defaultdict(int)

        tasks       = []
        assignments = []

        for r in rows:
            uid   = r['user_id']
            iid   = r['issue_id']
            title = (r['title'] or "").strip()
            body  = _strip_html(r['body'])
            res   = r['resolution']
            proj  = proj_map.get(r['project_id'], "")
            comps = comp_map.get(iid, [])

            # ── enriched task description ──────────────────────────────────────
            enriched = f"{title}. {body}"
            if comps:
                enriched += " Components: " + ", ".join(comps)
            if proj:
                enriched += f" Project: {proj}"

            tasks.append({
                "id":          f"tawos_issue_{iid}",
                "title":       title,
                "description": enriched.strip(),
                "type":        r['type'],
                "priority":    r['priority'],
                "status":      r['status'],
                "story_points": float(r['story_points'] or 0),
                "resolved":    res in ("Fixed","Done","Resolved"),
                "source":      "tawos",
            })

            accepted = res in ("Fixed","Done","Resolved") or \
                       r['status'] in ("Done","Resolved","Closed")
            assignments.append({
                "developer_id": f"tawos_user_{uid}",
                "task_id":      f"tawos_issue_{iid}",
                "accepted":     bool(accepted),
                "source":       "tawos",
            })

            # ── skill accumulation ─────────────────────────────────────────────
            dev_issue_count[uid] += 1

            # 1. keyword scan on text
            dev_skill_text[uid].update(_infer_skills(f"{title} {body}"))

            # 2. component names (most reliable)
            for c in comps:
                dev_skill_comp[uid].add(_map_component(c))

            # 3. project name
            if proj:
                dev_skill_proj[uid].update(_infer_skills(proj))
                dev_skill_proj[uid].add(proj.strip().title()[:30])

        # ── build developer list ───────────────────────────────────────────────
        top_devs = sorted(
            dev_issue_count.items(), key=lambda x: x[1], reverse=True
        )[:self.max_developers]

        developers = []
        for uid, count in top_devs:
            merged = (
                dev_skill_comp[uid] |
                dev_skill_proj[uid] |
                dev_skill_text[uid]
            )
            skill_list = [s for s in merged if s and len(s) > 1][:18]
            if not skill_list:
                skill_list = ["General"]

            developers.append({
                "id":          f"tawos_user_{uid}",
                "name":        f"TAWOS_Dev_{uid}",
                "skills":      skill_list,
                "skillTags":   skill_list,
                "source":      "tawos",
                "issue_count": count,
            })

        # Log sample
        for d in developers[:3]:
            logger.info(f"   Sample dev {d['id']}: {d['skills'][:8]}")

        return tasks, developers, assignments

    def get_developers(self)  -> List[Dict]: return self._developers
    def get_tasks(self)       -> List[Dict]: return self._tasks
    def get_assignments(self) -> List[Dict]: return self._assignments


# ── Stack Overflow loader ──────────────────────────────────────────────────────

class SOSurveyDataset:
    KAGGLE_DATASET = "berkayalan/stack-overflow-annual-developer-survey-2024"

    def __init__(self, cache_dir="./data/so_survey"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.df = None

    def _find_csv(self, root):
        candidates = sorted(Path(root).glob("**/*.csv"))
        return candidates[0] if candidates else None

    def load(self):
        manual = os.environ.get("SO_CSV_PATH")
        if manual and Path(manual).exists():
            self.df = pd.read_csv(manual, low_memory=False)
            logger.info(f"✅ SO survey loaded: {self.df.shape[0]:,} rows")
            return self.df
        try:
            import kagglehub
            logger.info("📥 Downloading SO survey from Kaggle...")
            dl = kagglehub.dataset_download(self.KAGGLE_DATASET)
            csv = self._find_csv(dl)
            if csv:
                self.df = pd.read_csv(csv, low_memory=False)
                logger.info(f"✅ SO survey downloaded: {self.df.shape[0]:,} rows")
                return self.df
        except Exception as e:
            logger.warning(f"⚠️  Kaggle download failed: {e}")
        return None

    def get_developer_profiles(self, limit=1000) -> List[Dict]:
        if self.df is None:
            self.load()
        if self.df is None:
            return []

        skill_cols = [c for c in self.df.columns if any(
            kw in c for kw in [
                "LanguageHaveWorkedWith","WebframeHaveWorkedWith",
                "DatabaseHaveWorkedWith","ToolsTechHaveWorkedWith",
                "PlatformHaveWorkedWith","MiscTechHaveWorkedWith",
            ]
        )]

        profiles = []
        for idx, row in self.df.iterrows():
            if idx >= limit:
                break
            skills = []
            for col in skill_cols:
                raw = row.get(col)
                if pd.notna(raw):
                    skills.extend(str(raw).split(";"))
            skills = list({s.strip() for s in skills if s.strip()})[:20]
            if not skills:
                continue
            try:
                yc = row.get("YearsCodePro", row.get("YearsCode", 0))
                years = int(float(yc)) if pd.notna(yc) else 0
            except Exception:
                years = 0
            profiles.append({
                "id":       f"so_dev_{idx}",
                "name":     f"SO_Dev_{idx}",
                "skills":   skills,
                "skillTags": skills,
                "experience_years": max(0, years),
                "source":   "stackoverflow",
            })

        logger.info(f"✅ Extracted {len(profiles)} SO developer profiles")
        return profiles

    def get_training_assignments(self, limit=500) -> List[Dict]:
        profiles = self.get_developer_profiles(limit)
        rng = np.random.default_rng(42)
        records = []
        for idx, p in enumerate(profiles):
            for si in range(min(len(p["skills"]), 8)):
                records.append({
                    "developer_id": p["id"],
                    "task_id":      f"so_task_{idx}_{si}",
                    "accepted":     bool(rng.choice([True, False], p=[0.7, 0.3])),
                    "source":       "stackoverflow",
                })
        return records


# ── Combined dataset ───────────────────────────────────────────────────────────

class RealCombinedDataset:
    """Drop-in replacement for CombinedDataset in dataset_v2.py"""

    def __init__(
        self,
        db_host=None, db_port=None, db_user=None, db_password=None, db_name=None,
        use_stackoverflow=True,
        so_profile_limit=1000, so_training_limit=500,
        max_issues=10_000, max_developers=2_000,
    ):
        self.tawos = TAWOSRealDataset(
            host     = db_host     or os.environ.get("DB_HOST",     "localhost"),
            port     = db_port     or int(os.environ.get("DB_PORT", "3306")),
            user     = db_user     or os.environ.get("DB_USER",     "root"),
            password = db_password or os.environ.get("DB_PASSWORD", ""),
            db_name  = db_name     or os.environ.get("DB_NAME",     "TAWOS"),
            max_issues=max_issues, max_developers=max_developers,
        )
        self.so = SOSurveyDataset() if use_stackoverflow else None
        self.so_profile_limit  = so_profile_limit
        self.so_training_limit = so_training_limit
        self.use_stackoverflow = use_stackoverflow
        self._so_profiles:    List[Dict] = []
        self._so_assignments: List[Dict] = []

    def build(self) -> Dict:
        logger.info("🔨 Building REAL combined dataset (TAWOS v3 + SO)...")

        logger.info("📊 Step 1: Loading TAWOS from MySQL (batched queries)...")
        tawos_data = self.tawos.load()

        if self.use_stackoverflow and self.so:
            logger.info("📊 Step 2: Loading Stack Overflow survey...")
            self.so.load()
            self._so_profiles    = self.so.get_developer_profiles(self.so_profile_limit)
            self._so_assignments = self.so.get_training_assignments(self.so_training_limit)
        else:
            logger.info("ℹ️  Stack Overflow skipped")

        logger.info(
            f"✅ Dataset ready — "
            f"TAWOS: {len(tawos_data['developers'])} devs / "
            f"{len(tawos_data['tasks'])} tasks / "
            f"{len(tawos_data['assignments'])} assignments | "
            f"SO: {len(self._so_profiles)} profiles"
        )
        return {"tawos": tawos_data, "stackoverflow": {"profiles": self._so_profiles}}

    def get_all_developers(self) -> List[Dict]:
        devs = list(self.tawos.get_developers())
        for p in self._so_profiles:
            devs.append({
                "id": p["id"], "name": p["name"],
                "skills": p["skills"], "skillTags": p["skillTags"],
                "experience_years": p.get("experience_years", 0),
                "source": "stackoverflow",
            })
        return devs

    def get_all_tasks(self)       -> List[Dict]: return list(self.tawos.get_tasks())
    def get_all_assignments(self) -> List[Dict]:
        return list(self.tawos.get_assignments()) + self._so_assignments
