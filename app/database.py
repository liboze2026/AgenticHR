"""SQLAlchemy 数据库连接管理"""
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# 确保数据目录存在
db_path = settings.database_url.replace("sqlite:///", "")
if db_path and db_path != ":memory:":
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入用的数据库 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """仅测试用. 生产/开发走 Alembic (migrations/).

    Alembic 引入后 (M3-kickoff K0), 生产环境的 schema 演化完全由 migration 管理.
    此函数保留是因为大量单测依赖 `create_all()` 的幂等建表行为.
    """
    Base.metadata.create_all(bind=engine)
    _migrate(engine)


def _migrate(engine):
    """向已有表添加新列（SQLite 不支持 ALTER COLUMN，只支持 ADD COLUMN）"""
    import re
    from sqlalchemy import text, inspect
    insp = inspect(engine)

    migrations = [
        ("resumes", "ai_parsed", "VARCHAR(10) DEFAULT 'no'"),
        ("resumes", "bachelor_school", "VARCHAR(200) DEFAULT ''"),
        ("resumes", "master_school", "VARCHAR(200) DEFAULT ''"),
        ("resumes", "phd_school", "VARCHAR(200) DEFAULT ''"),
        ("resumes", "qr_code_path", "VARCHAR(500) DEFAULT ''"),
        ("interviews", "feishu_event_id", "VARCHAR(200) DEFAULT ''"),
        ("interviews", "meeting_account", "VARCHAR(50) DEFAULT ''"),
        ("interviews", "meeting_id", "VARCHAR(50) DEFAULT ''"),
        ("interviews", "meeting_topic", "VARCHAR(200) DEFAULT ''"),
        ("interviewers", "phone", "VARCHAR(20) DEFAULT ''"),
        # 用户数据隔离
        ("resumes", "user_id", "INTEGER DEFAULT 0"),
        ("jobs", "user_id", "INTEGER DEFAULT 0"),
        ("interviews", "user_id", "INTEGER DEFAULT 0"),
        ("notification_logs", "user_id", "INTEGER DEFAULT 0"),
    ]

    with engine.connect() as conn:
        for table, column, col_type in migrations:
            if table in insp.get_table_names():
                existing = [c["name"] for c in insp.get_columns(table)]
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    conn.commit()

        # 数据迁移：把 interviewers.email 里误填的中国手机号搬到 phone 列
        # 只迁移 phone 为空、email 是 11 位 1xx 开头的行
        if "interviewers" in insp.get_table_names():
            rows = conn.execute(text(
                "SELECT id, email FROM interviewers WHERE (phone IS NULL OR phone='') AND email != ''"
            )).fetchall()
            pattern = re.compile(r"^1[3-9]\d{9}$")
            for row in rows:
                if pattern.match(row[1] or ""):
                    conn.execute(
                        text("UPDATE interviewers SET phone=:p, email='' WHERE id=:id"),
                        {"p": row[1], "id": row[0]},
                    )
            conn.commit()

        # Add user_id to interviewers if missing
        if "interviewers" in insp.get_table_names():
            interviewer_cols = [c["name"] for c in insp.get_columns("interviewers")]
            if "user_id" not in interviewer_cols:
                conn.execute(text("ALTER TABLE interviewers ADD COLUMN user_id INTEGER DEFAULT 0"))
                conn.commit()

        # 数据迁移：user_id=0 的旧数据自动归属到第一个用户
        # BUG-036: 用标记表防止重复执行 —— 每次重启都跑会静默污染新的 user_id=0 孤儿数据
        if "users" in insp.get_table_names():
            already_ran = conn.execute(
                text("SELECT 1 FROM _migration_flags WHERE flag='user_id_backfill' LIMIT 1")
            ).fetchone() if "_migration_flags" in insp.get_table_names() else None
            if not already_ran:
                first_user = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()
                if first_user:
                    uid = first_user[0]
                    for t in ("resumes", "jobs", "interviews", "notification_logs"):
                        if t in insp.get_table_names():
                            conn.execute(text(f"UPDATE {t} SET user_id=:uid WHERE user_id=0"), {"uid": uid})
                    # 确保标记表存在并记录已执行
                    conn.execute(text(
                        "CREATE TABLE IF NOT EXISTS _migration_flags "
                        "(flag TEXT PRIMARY KEY, ran_at TEXT)"
                    ))
                    conn.execute(text(
                        "INSERT OR IGNORE INTO _migration_flags (flag, ran_at) "
                        "VALUES ('user_id_backfill', datetime('now'))"
                    ))
                    conn.commit()
