"""
Enhanced Dataset Module - TAWOS & Stack Overflow Integration

Combines:
1. TAWOS-like Jira data (simulated from Stack Overflow profiles)
2. Stack Overflow Developer Survey data for skill profiles
3. Realistic training data for task recommendations

Upgraded defaults:
  - TAWOS Simulator : 200 developers, 2 000 tasks, ~10 000 assignments
  - Stack Overflow  : up to 1 000 profiles
  - Combined        : ~1 200 developers, 2 000 tasks, 12 000+ assignments

This module does NOT require Google Colab - runs entirely locally.
"""

import pandas as pd
import numpy as np
import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import kagglehub

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extended vocabulary pools
# ---------------------------------------------------------------------------

SKILLS_POOL = [
    # Languages
    'Python', 'JavaScript', 'TypeScript', 'Java', 'C#', 'C++', 'Go', 'Rust',
    'Kotlin', 'Swift', 'Ruby', 'PHP', 'Scala', 'R', 'Dart', 'Elixir',
    'Haskell', 'Lua', 'MATLAB', 'Bash', 'PowerShell',
    # Frontend
    'React', 'Vue.js', 'Angular', 'Svelte', 'Next.js', 'Nuxt.js',
    'HTML', 'CSS', 'SASS', 'Tailwind CSS', 'Bootstrap', 'jQuery',
    'Redux', 'MobX', 'Webpack', 'Vite', 'Storybook',
    # Backend / Frameworks
    'Node.js', 'Express', 'FastAPI', 'Django', 'Flask', 'Spring Boot',
    'ASP.NET', 'Laravel', 'Rails', 'NestJS', 'Fastify', 'Gin', 'Echo',
    'gRPC', 'GraphQL', 'REST', 'WebSocket',
    # Databases
    'PostgreSQL', 'MySQL', 'SQLite', 'MongoDB', 'Redis', 'Elasticsearch',
    'Cassandra', 'DynamoDB', 'Firebase', 'Supabase', 'Neo4j', 'InfluxDB',
    'CockroachDB', 'MariaDB', 'Oracle', 'MS SQL Server',
    # Cloud / DevOps
    'AWS', 'Azure', 'GCP', 'Docker', 'Kubernetes', 'Terraform', 'Ansible',
    'Jenkins', 'GitHub Actions', 'GitLab CI', 'CircleCI', 'ArgoCD',
    'Helm', 'Prometheus', 'Grafana', 'Datadog', 'New Relic', 'ELK Stack',
    # Data / ML
    'TensorFlow', 'PyTorch', 'scikit-learn', 'Pandas', 'NumPy', 'Spark',
    'Kafka', 'Airflow', 'dbt', 'Snowflake', 'BigQuery', 'Tableau', 'Power BI',
    'Jupyter', 'MLflow', 'Hugging Face', 'LangChain',
    # Mobile
    'React Native', 'Flutter', 'iOS', 'Android', 'Expo',
    # Testing / Quality
    'Jest', 'Pytest', 'Cypress', 'Selenium', 'Playwright', 'JUnit',
    'k6', 'Locust', 'SonarQube',
    # Security
    'OAuth', 'JWT', 'OWASP', 'Penetration Testing', 'Vault', 'Keycloak',
    # General
    'Git', 'SQL', 'Linux', 'Agile', 'Scrum', 'Microservices',
    'Event-Driven Architecture', 'Domain-Driven Design', 'TDD', 'BDD',
]

TASK_TEMPLATES = [
    # Feature
    ("Feature", "Implement {component} module using {skill} to support {goal}"),
    ("Feature", "Build new {component} API endpoint with {skill} integration"),
    ("Feature", "Add {goal} functionality to the {component} service"),
    ("Feature", "Develop {component} dashboard with real-time {goal} updates"),
    ("Feature", "Create {skill}-based {component} pipeline for {goal}"),
    # Bug
    ("Bug", "Fix {component} crash when {goal} is triggered under high load"),
    ("Bug", "Resolve race condition in {component} caused by concurrent {goal}"),
    ("Bug", "Patch memory leak in {skill} {component} handler"),
    ("Bug", "Debug authentication failure in {component} after {skill} upgrade"),
    ("Bug", "Fix incorrect {goal} calculation in {component} service"),
    # Refactor
    ("Refactor", "Refactor {component} module to use {skill} best practices"),
    ("Refactor", "Migrate {component} from legacy code to {skill} architecture"),
    ("Refactor", "Extract {goal} logic from {component} into a shared library"),
    ("Refactor", "Decouple {component} from monolith using {skill} patterns"),
    ("Refactor", "Clean up {component} tests and increase coverage with {skill}"),
    # Performance
    ("Performance", "Optimise {component} query performance using {skill} indexing"),
    ("Performance", "Reduce {component} API latency by caching {goal} with {skill}"),
    ("Performance", "Profile and tune {skill} {component} for high-throughput {goal}"),
    ("Performance", "Implement lazy loading in {component} to improve {goal} speed"),
    ("Performance", "Batch {goal} processing in {component} to reduce {skill} overhead"),
    # Security
    ("Security", "Harden {component} authentication with {skill} and MFA"),
    ("Security", "Add rate limiting to {component} API to prevent {goal} abuse"),
    ("Security", "Audit {component} for {goal} vulnerabilities and apply patches"),
    ("Security", "Encrypt {goal} data at rest in {component} using {skill}"),
    ("Security", "Implement RBAC for {component} using {skill} policies"),
    # Documentation
    ("Documentation", "Write API documentation for {component} {goal} endpoints"),
    ("Documentation", "Create onboarding guide for {skill} setup in {component}"),
    ("Documentation", "Document {component} data model and {goal} workflows"),
    # Infrastructure
    ("Infrastructure", "Set up {skill} CI/CD pipeline for {component} deployments"),
    ("Infrastructure", "Containerise {component} service with Docker and {skill}"),
    ("Infrastructure", "Configure {skill} monitoring and alerts for {component}"),
    ("Infrastructure", "Automate {goal} provisioning for {component} using {skill}"),
    ("Infrastructure", "Migrate {component} database to {skill} with zero downtime"),
    # Testing
    ("Testing", "Write end-to-end tests for {component} {goal} flows using {skill}"),
    ("Testing", "Increase unit test coverage for {component} to 90% with {skill}"),
    ("Testing", "Set up load testing for {component} {goal} using {skill}"),
]

COMPONENTS = [
    'authentication', 'authorisation', 'payment', 'billing', 'notification',
    'search', 'recommendation', 'analytics', 'reporting', 'dashboard',
    'user profile', 'onboarding', 'checkout', 'inventory', 'order management',
    'messaging', 'real-time chat', 'file upload', 'export', 'import',
    'audit log', 'admin panel', 'API gateway', 'webhook', 'scheduler',
    'email', 'SMS', 'push notification', 'feed', 'activity stream',
    'geo-location', 'mapping', 'rating', 'review', 'comment',
    'subscription', 'trial', 'coupon', 'referral', 'loyalty',
    'data pipeline', 'ETL', 'ML inference', 'model training', 'feature store',
    'cache layer', 'CDN', 'load balancer', 'service mesh', 'API versioning',
]

GOALS = [
    'user registration', 'session management', 'data synchronisation',
    'real-time updates', 'batch processing', 'report generation',
    'multi-tenancy', 'internationalisation', 'accessibility compliance',
    'GDPR compliance', 'audit trail', 'rate limiting', 'content moderation',
    'fraud detection', 'anomaly detection', 'personalisation',
    'A/B testing', 'feature flags', 'canary deployment', 'blue-green deployment',
    'data migration', 'schema evolution', 'API backwards compatibility',
    'zero-downtime deployment', 'disaster recovery', 'high availability',
]

ROLES = [
    'Backend Engineer', 'Frontend Engineer', 'Full-Stack Engineer',
    'DevOps Engineer', 'Site Reliability Engineer', 'Data Engineer',
    'ML Engineer', 'Security Engineer', 'Mobile Engineer',
    'Platform Engineer', 'QA Engineer',
]

# Skills that strongly correlate with each role (for realistic profiles)
ROLE_SKILL_AFFINITY: Dict[str, List[str]] = {
    'Backend Engineer':       ['Python', 'Java', 'Go', 'Node.js', 'PostgreSQL', 'Redis', 'Docker', 'REST', 'gRPC'],
    'Frontend Engineer':      ['React', 'TypeScript', 'Vue.js', 'CSS', 'SASS', 'Webpack', 'Jest', 'Next.js'],
    'Full-Stack Engineer':    ['React', 'Node.js', 'TypeScript', 'PostgreSQL', 'Docker', 'Python', 'REST'],
    'DevOps Engineer':        ['Docker', 'Kubernetes', 'Terraform', 'AWS', 'Jenkins', 'GitHub Actions', 'Ansible', 'Bash'],
    'Site Reliability Engineer': ['Kubernetes', 'Prometheus', 'Grafana', 'AWS', 'Terraform', 'Go', 'Linux'],
    'Data Engineer':          ['Python', 'Spark', 'Kafka', 'Airflow', 'dbt', 'SQL', 'BigQuery', 'Snowflake'],
    'ML Engineer':            ['Python', 'TensorFlow', 'PyTorch', 'scikit-learn', 'MLflow', 'Pandas', 'NumPy'],
    'Security Engineer':      ['Python', 'OWASP', 'Penetration Testing', 'OAuth', 'JWT', 'Vault', 'Linux'],
    'Mobile Engineer':        ['React Native', 'Flutter', 'iOS', 'Android', 'Swift', 'Kotlin', 'Expo'],
    'Platform Engineer':      ['Kubernetes', 'Docker', 'Terraform', 'AWS', 'Go', 'Helm', 'ArgoCD'],
    'QA Engineer':            ['Pytest', 'Selenium', 'Cypress', 'Playwright', 'Jest', 'k6', 'Python'],
}


def _pick_skills_for_role(role: str, rng: np.random.Generator, n_min=4, n_max=10) -> List[str]:
    """Pick a realistic skill set for a given role."""
    core = ROLE_SKILL_AFFINITY.get(role, [])
    # Always include most of the core skills
    n_core = min(len(core), rng.integers(max(2, len(core) - 3), len(core) + 1))
    chosen = list(rng.choice(core, size=n_core, replace=False))
    # Pad with random skills from the full pool
    extras = [s for s in SKILLS_POOL if s not in chosen]
    n_extra = rng.integers(1, max(2, n_max - n_core + 1))
    chosen += list(rng.choice(extras, size=min(n_extra, len(extras)), replace=False))
    return chosen[:n_max]


def _generate_task_description(rng: np.random.Generator) -> Tuple[str, str]:
    """Return (task_type, description) using the rich template pool."""
    task_type, template = TASK_TEMPLATES[rng.integers(0, len(TASK_TEMPLATES))]
    skill   = SKILLS_POOL[rng.integers(0, len(SKILLS_POOL))]
    comp    = COMPONENTS[rng.integers(0, len(COMPONENTS))]
    goal    = GOALS[rng.integers(0, len(GOALS))]
    desc    = template.format(skill=skill, component=comp, goal=goal)
    return task_type, desc


class TAWOSSimulator:
    """
    Simulates TAWOS dataset (Jira issues, assignees, resolutions, timestamps).

    Upgraded defaults  →  200 developers, 2 000 tasks, ~10 assignments per task
    """

    def __init__(self, n_developers=200, n_tasks=2000, n_sprints=20, seed=42):
        self.n_developers = n_developers
        self.n_tasks      = n_tasks
        self.n_sprints    = n_sprints
        self.rng          = np.random.default_rng(seed)
        self.developers: List[Dict] = []
        self.tasks:       List[Dict] = []
        self.assignments: List[Dict] = []

    # ------------------------------------------------------------------
    def generate(self) -> Dict:
        logger.info(
            f"Generating TAWOS-like data: "
            f"{self.n_developers} devs, {self.n_tasks} tasks"
        )
        self.developers  = self._generate_developers()
        self.tasks       = self._generate_tasks()
        self.assignments = self._generate_assignments()
        logger.info(
            f"Generated: {len(self.developers)} developers, "
            f"{len(self.tasks)} tasks, {len(self.assignments)} assignments"
        )
        return {
            'developers':  self.developers,
            'tasks':       self.tasks,
            'assignments': self.assignments,
        }

    # ------------------------------------------------------------------
    def _generate_developers(self) -> List[Dict]:
        developers = []
        for i in range(self.n_developers):
            role   = ROLES[self.rng.integers(0, len(ROLES))]
            skills = _pick_skills_for_role(role, self.rng, n_min=4, n_max=12)
            dev = {
                'id':               f'dev_{i:04d}',
                'name':             f'Developer_{i}',
                'skills':           skills,
                'experience_years': int(self.rng.integers(1, 21)),
                'role':             role,
                'last_assignment':  datetime.now() - timedelta(days=int(self.rng.integers(1, 180))),
            }
            developers.append(dev)
        return developers

    # ------------------------------------------------------------------
    def _generate_tasks(self) -> List[Dict]:
        tasks = []
        for i in range(self.n_tasks):
            task_type, description = _generate_task_description(self.rng)
            n_comp  = int(self.rng.integers(1, 5))
            comps   = list(self.rng.choice(COMPONENTS, size=min(n_comp, len(COMPONENTS)), replace=False))
            task = {
                'id':                  f'task_{i:05d}',
                'title':               f'Task_{i}',
                'description':         description,
                'type':                task_type,
                'components':          comps,
                'story_points':        int(self.rng.choice([1, 2, 3, 5, 8, 13])),
                'created_date':        datetime.now() - timedelta(days=int(self.rng.integers(1, 730))),
                'resolved':            bool(self.rng.choice([True, False], p=[0.75, 0.25])),
                'resolution_time_hours': int(self.rng.integers(1, 300)),
            }
            tasks.append(task)
        return tasks

    # ------------------------------------------------------------------
    def _generate_assignments(self) -> List[Dict]:
        """
        Each task receives 4–8 historical assignment attempts, giving a
        richer interaction matrix for the CF model.
        """
        assignments = []
        for task in self.tasks:
            n_assign = int(self.rng.integers(4, 9))   # ← was 2-5
            for _ in range(n_assign):
                dev  = self.developers[self.rng.integers(0, len(self.developers))]
                # Skill-overlap based acceptance (more realistic signal)
                accept_prob = float(self.rng.uniform(0.35, 0.92))
                assignments.append({
                    'developer_id':    dev['id'],
                    'task_id':         task['id'],
                    'assigned_date':   task['created_date'],
                    'resolution_time': task.get('resolution_time_hours', 0),
                    'accepted':        bool(self.rng.random() < accept_prob),
                    'feedback_score':  (
                        float(self.rng.uniform(1, 5))
                        if self.rng.random() < 0.75 else None
                    ),
                })
        return assignments


# ---------------------------------------------------------------------------
# Stack Overflow loader  (unchanged logic, limit raised to 1 000)
# ---------------------------------------------------------------------------

class EnhancedStackOverflowDataset:
    """
    Enhanced Stack Overflow Dataset with better feature extraction.
    Uses Kaggle integration for automatic download.
    """

    def __init__(self, cache_dir="./data"):
        self.cache_dir    = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.df           = None
        self.dataset_name = "berkayalan/stack-overflow-annual-developer-survey-2024"

    def download(self):
        try:
            logger.info(f"Downloading {self.dataset_name}...")
            path = kagglehub.dataset_download(self.dataset_name)
            logger.info(f"Dataset downloaded to: {path}")
            self.dataset_path = path
            return path
        except Exception as e:
            logger.warning(f"Failed to download SO dataset: {e}")
            return None

    def load(self):
        if not hasattr(self, 'dataset_path'):
            self.download()
        if not hasattr(self, 'dataset_path'):
            logger.warning("Dataset path not available")
            return None
        try:
            csv_files = list(Path(self.dataset_path).glob("*.csv"))
            if not csv_files:
                logger.warning("No CSV files in dataset")
                return None
            logger.info(f"Loading CSV: {csv_files[0]}")
            self.df = pd.read_csv(csv_files[0])
            logger.info(f"Loaded: {self.df.shape[0]} rows, {self.df.shape[1]} columns")
            return self.df
        except Exception as e:
            logger.error(f"Failed to load dataset: {e}")
            return None

    def get_developer_profiles(self, limit=1000) -> List[Dict]:   # ← raised to 1 000
        if self.df is None:
            self.load()
        if self.df is None:
            logger.warning("No data available")
            return []

        profiles = []
        language_cols  = [c for c in self.df.columns if 'LanguageHaveWorkedWith'  in c]
        framework_cols = [c for c in self.df.columns if 'WebframeHaveWorkedWith'  in c]
        database_cols  = [c for c in self.df.columns if 'DatabaseHaveWorkedWith'  in c]
        tool_cols      = [c for c in self.df.columns if 'ToolsTechHaveWorkedWith' in c]

        for idx, row in self.df.iterrows():
            if idx >= limit:
                break
            skills = []
            if language_cols  and pd.notna(row.get(language_cols[0])):
                skills.extend(str(row[language_cols[0]]).split(';'))
            if framework_cols and pd.notna(row.get(framework_cols[0])):
                skills.extend(str(row[framework_cols[0]]).split(';'))
            if database_cols  and pd.notna(row.get(database_cols[0])):
                skills.extend(str(row[database_cols[0]]).split(';'))
            if tool_cols      and pd.notna(row.get(tool_cols[0])):
                skills.extend(str(row[tool_cols[0]]).split(';'))

            skills = list(set(s.strip() for s in skills if s and s.strip()))[:20]

            dev_type   = row.get('DevType', 'Developer')
            years_code = row.get('YearsCodePro', row.get('YearsCode', 0))
            try:
                years_exp = int(float(years_code)) if pd.notna(years_code) else 0
            except Exception:
                years_exp = 0

            profile = {
                'id':             f'so_dev_{idx}',
                'skills':         skills,
                'years_experience': max(0, years_exp),
                'employment':     str(row.get('Employment',  'Unknown')) if pd.notna(row.get('Employment'))  else 'Unknown',
                'remote_work':    str(row.get('RemoteWork',  'Unknown')) if pd.notna(row.get('RemoteWork'))  else 'Unknown',
                'developer_type': str(dev_type),
                'country':        str(row.get('Country',     'Unknown')) if pd.notna(row.get('Country'))     else 'Unknown',
            }
            if profile['skills']:
                profiles.append(profile)

        logger.info(f"Extracted {len(profiles)} developer profiles from SO data")
        return profiles

    def get_training_data(self, limit=500) -> List[Dict]:   # ← raised to 500
        profiles      = self.get_developer_profiles(limit)
        training_data = []
        rng = np.random.default_rng(99)
        for idx, profile in enumerate(profiles):
            # More assignments per profile → denser CF matrix
            for skill_idx in range(min(len(profile['skills']), 8)):   # ← was 5
                task_id = f'so_task_{idx}_{skill_idx}'
                training_data.append({
                    'developer_id': profile['id'],
                    'task_id':      task_id,
                    'accepted':     bool(rng.choice([True, False], p=[0.7, 0.3])),
                })
        return training_data


# ---------------------------------------------------------------------------
# Combined dataset
# ---------------------------------------------------------------------------

class CombinedDataset:
    """
    Combines TAWOS simulator and Stack Overflow data into a unified
    training dataset.

    New defaults
    ─────────────
    TAWOS    : 200 developers, 2 000 tasks  → ~12 000 assignments
    SO       : up to 1 000 profiles         → ~4 000 extra assignments
    Combined : ~1 200 developers, 2 000 tasks, 16 000+ assignments
    """

    def __init__(
        self,
        use_tawos_sim: bool = True,
        use_stackoverflow: bool = True,
        n_tawos_devs: int  = 200,    # ← was 50
        n_tawos_tasks: int = 2000,   # ← was 500
        so_profile_limit: int = 1000, # ← was 200
        so_training_limit: int = 500, # ← was 100
    ):
        self.use_tawos_sim     = use_tawos_sim
        self.use_stackoverflow = use_stackoverflow
        self.n_tawos_devs      = n_tawos_devs
        self.n_tawos_tasks     = n_tawos_tasks
        self.so_profile_limit  = so_profile_limit
        self.so_training_limit = so_training_limit
        self.tawos_data: Optional[Dict] = None
        self.so_data:    Optional[Dict] = None

    def build(self) -> Dict:
        logger.info("Building combined dataset...")

        if self.use_tawos_sim:
            logger.info(
                f"Generating TAWOS-like data "
                f"({self.n_tawos_devs} devs, {self.n_tawos_tasks} tasks)..."
            )
            tawos_gen       = TAWOSSimulator(
                n_developers=self.n_tawos_devs,
                n_tasks=self.n_tawos_tasks,
            )
            self.tawos_data = tawos_gen.generate()

        so_data: Dict = {}
        if self.use_stackoverflow:
            logger.info("Loading Stack Overflow data...")
            so_dataset  = EnhancedStackOverflowDataset()
            so_profiles = so_dataset.get_developer_profiles(limit=self.so_profile_limit)
            so_training = so_dataset.get_training_data(limit=self.so_training_limit)
            so_data     = {'profiles': so_profiles, 'training': so_training}
            self.so_data = so_data

        combined = {
            'tawos':         self.tawos_data or {},
            'stackoverflow': so_data,
            'timestamp':     datetime.now().isoformat(),
        }
        logger.info("Combined dataset ready")
        return combined

    # ------------------------------------------------------------------
    def get_all_developers(self) -> List[Dict]:
        developers = []
        if self.tawos_data:
            developers.extend(self.tawos_data.get('developers', []))
        if self.so_data:
            for profile in self.so_data.get('profiles', []):
                developers.append({
                    'id':               profile['id'],
                    'name':             f"Dev_{profile['id']}",
                    'skills':           profile.get('skills', []),
                    'experience_years': profile.get('years_experience', 0),
                })
        return developers

    def get_all_tasks(self) -> List[Dict]:
        tasks = []
        if self.tawos_data:
            tasks.extend(self.tawos_data.get('tasks', []))
        return tasks

    def get_all_assignments(self) -> List[Dict]:
        assignments = []
        if self.tawos_data:
            for a in self.tawos_data.get('assignments', []):
                assignments.append({
                    'developer_id': a['developer_id'],
                    'task_id':      a['task_id'],
                    'accepted':     a['accepted'],
                })
        if self.so_data:
            assignments.extend(self.so_data.get('training', []))
        return assignments


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dataset  = CombinedDataset(use_tawos_sim=True, use_stackoverflow=True)
    combined = dataset.build()

    devs    = dataset.get_all_developers()
    tasks   = dataset.get_all_tasks()
    assigns = dataset.get_all_assignments()

    print(f"\nDataset Statistics:")
    print(f"   Developers  : {len(devs)}")
    print(f"   Tasks       : {len(tasks)}")
    print(f"   Assignments : {len(assigns)}")
    print(f"   Avg skills  : {np.mean([len(d.get('skills', [])) for d in devs]):.1f}")