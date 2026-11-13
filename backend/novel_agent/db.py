"""SQLite 存储层：单连接 + 线程锁，WAL 模式。"""
import json
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

from .paths import DATA_DIR, is_frozen

DB_PATH = DATA_DIR / "data.db"
_lock = threading.RLock()
_conn: "sqlite3.Connection | None" = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  genre TEXT DEFAULT '',
  premise TEXT DEFAULT '',
  style TEXT DEFAULT '',
  target_words INTEGER DEFAULT 200000,
  brief TEXT DEFAULT '{}',
  status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS world(
  project_id INTEGER PRIMARY KEY,
  sections TEXT DEFAULT '[]',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS characters(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  role TEXT DEFAULT '',
  profile TEXT DEFAULT '{}',
  created_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS volumes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  idx INTEGER DEFAULT 0,
  title TEXT DEFAULT '正文',
  summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chapters(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  volume_id INTEGER NOT NULL,
  idx INTEGER DEFAULT 0,
  title TEXT NOT NULL,
  brief TEXT DEFAULT '',
  status TEXT DEFAULT 'todo',
  summary TEXT DEFAULT '',
  word_count INTEGER DEFAULT 0,
  current_version_id INTEGER,
  book_done INTEGER DEFAULT 0,
  created_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chapter_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_id INTEGER NOT NULL,
  vtype TEXT DEFAULT 'draft',
  content TEXT DEFAULT '',
  word_count INTEGER DEFAULT 0,
  review_id INTEGER,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_id INTEGER NOT NULL,
  version_id INTEGER,
  round INTEGER DEFAULT 1,
  score INTEGER DEFAULT 0,
  report TEXT DEFAULT '{}',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS foreshadowing(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  description TEXT NOT NULL,
  planted_chapter_id INTEGER,
  status TEXT DEFAULT 'open',
  payoff_chapter_id INTEGER,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS timeline_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  chapter_id INTEGER,
  time_label TEXT DEFAULT '',
  description TEXT NOT NULL,
  idx INTEGER DEFAULT 0,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS skills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dir_name TEXT UNIQUE,
  name TEXT,
  description TEXT DEFAULT '',
  stages TEXT DEFAULT '[]',
  enabled INTEGER DEFAULT 1,
  source TEXT DEFAULT 'builtin',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS mcp_servers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE,
  transport TEXT DEFAULT 'stdio',
  command TEXT DEFAULT '',
  args TEXT DEFAULT '[]',
  url TEXT DEFAULT '',
  enabled INTEGER DEFAULT 0,
  auto_connect INTEGER DEFAULT 1,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS config(
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS book_jobs(
  project_id INTEGER PRIMARY KEY,
  status TEXT DEFAULT 'idle',
  mode TEXT DEFAULT 'full',
  rounds INTEGER DEFAULT 2,
  threshold INTEGER DEFAULT 85,
  stop_on_error INTEGER DEFAULT 0,
  total INTEGER DEFAULT 0,
  done INTEGER DEFAULT 0,
  seq INTEGER DEFAULT 0,
  current_chapter_id INTEGER,
  current_chapter_title TEXT DEFAULT '',
  error TEXT DEFAULT '',
  started_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS book_job_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  type TEXT DEFAULT '',
  payload TEXT DEFAULT '{}',
  created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id, volume_id, idx);
CREATE INDEX IF NOT EXISTS idx_versions_chapter ON chapter_versions(chapter_id);
CREATE INDEX IF NOT EXISTS idx_book_events ON book_job_events(project_id, seq);
CREATE TABLE IF NOT EXISTS text_chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  chapter_id INTEGER,
  ref_type TEXT DEFAULT 'chapter',
  ref_id INTEGER,
  title TEXT DEFAULT '',
  chunk_idx INTEGER DEFAULT 0,
  content TEXT NOT NULL,
  tfidf TEXT DEFAULT '{}',
  updated_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON text_chunks(project_id);
CREATE TABLE IF NOT EXISTS interview_templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  category TEXT DEFAULT '',
  blueprint TEXT DEFAULT '{}',
  seed_history TEXT DEFAULT '[]',
  is_builtin INTEGER DEFAULT 0,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS project_branches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  parent_project_id INTEGER,
  branch_name TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
"""

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "temperature": "0.8",
    "max_tokens": "4096",
    "agent_rounds": "2",
    "review_threshold": "85",
    "chapter_words": "2500",
    "auto_summary": "1",
    "close_action": "ask",  # ask | minimize | exit
    "context_window": "128000",  # 模型上下文窗口（token），用于占用估算
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def query(sql: str, args: tuple = ()) -> list:
    with _lock:
        rows = get_conn().execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, args: tuple = ()) -> "dict | None":
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = get_conn().execute(sql, args)
        get_conn().commit()
        return cur.lastrowid


def executemany(sql: str, args_list: list) -> None:
    if not args_list:
        return
    with _lock:
        get_conn().executemany(sql, args_list)
        get_conn().commit()


class _Tx:
    """事务内写入：不单独 commit，由 transaction() 统一提交。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, args: tuple = ()) -> int:
        return self._conn.execute(sql, args).lastrowid

    def executemany(self, sql: str, args_list: list) -> None:
        if args_list:
            self._conn.executemany(sql, args_list)


def transaction():
    """单连接事务：成功 commit，异常 rollback。"""
    from contextlib import contextmanager

    @contextmanager
    def _tx():
        with _lock:
            conn = get_conn()
            try:
                yield _Tx(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    return _tx()


def _import_legacy_config_if_needed() -> None:
    """AppData 库已存在但 Key 为空时，尝试从 exe 同级旧 data/data.db 导入配置。"""
    if not is_frozen():
        return
    cfg = get_config()
    if cfg.get("api_key"):
        return
    legacy_db = Path(sys.executable).parent / "data" / "data.db"
    if not legacy_db.is_file():
        return
    try:
        old = sqlite3.connect(str(legacy_db))
        old.row_factory = sqlite3.Row
        rows = old.execute("SELECT key, value FROM config").fetchall()
        old.close()
    except sqlite3.Error:
        return
    if not rows:
        return
    updates = {r["key"]: r["value"] for r in rows if r["key"] in DEFAULT_CONFIG and r["value"]}
    if updates:
        set_config_values(updates)


def init_db() -> None:
    with _lock:
        get_conn().executescript(SCHEMA)
        get_conn().commit()
    _migrate()
    if not query_one("SELECT key FROM config LIMIT 1"):
        set_config_values(DEFAULT_CONFIG)
    _import_legacy_config_if_needed()


def _migrate() -> None:
    """幂等迁移：为旧库补齐后加的列。"""
    cols = [r["name"] for r in query("PRAGMA table_info(chapters)")]
    if "book_done" not in cols:
        execute("ALTER TABLE chapters ADD COLUMN book_done INTEGER DEFAULT 0")
    pcols = [r["name"] for r in query("PRAGMA table_info(projects)")]
    if "brief" not in pcols:
        execute("ALTER TABLE projects ADD COLUMN brief TEXT DEFAULT '{}'")
    if "parent_project_id" not in pcols:
        execute("ALTER TABLE projects ADD COLUMN parent_project_id INTEGER")
    if "branch_name" not in pcols:
        execute("ALTER TABLE projects ADD COLUMN branch_name TEXT DEFAULT ''")
    _seed_interview_templates()


def _seed_interview_templates() -> None:
    from .templates_data import BUILTIN_TEMPLATES
    if query_one("SELECT id FROM interview_templates LIMIT 1"):
        return
    for t in BUILTIN_TEMPLATES:
        execute(
            "INSERT INTO interview_templates(name, category, blueprint, seed_history, is_builtin, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (t["name"], t["category"], json.dumps(t["blueprint"], ensure_ascii=False),
             json.dumps(t["seed_history"], ensure_ascii=False), now()),
        )


def get_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    for r in query("SELECT key, value FROM config"):
        cfg[r["key"]] = r["value"]
    return cfg


def set_config_values(d: dict) -> None:
    for k, v in d.items():
        if k not in DEFAULT_CONFIG:
            continue
        execute(
            "INSERT INTO config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )


def cfg_int(cfg: dict, key: str, default: int = 0) -> int:
    try:
        return int(float(cfg.get(key, default)))
    except (TypeError, ValueError):
        return default


def cfg_float(cfg: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def cfg_bool(cfg: dict, key: str, default: bool = False) -> bool:
    v = cfg.get(key, default)
    return str(v).lower() in ("1", "true", "yes", "on")


def jload(text, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
