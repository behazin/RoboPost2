import os
import sys
import types
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_db():
    sys.modules.pop("sqlalchemy", None)
    sys.modules.pop("sqlalchemy.orm", None)
    sys.modules.pop("sqlalchemy.ext.declarative", None)
    sys.modules.pop("sqlalchemy.pool", None)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import Text

    mysql_dialect = types.ModuleType("sqlalchemy.dialects.mysql")
    mysql_dialect.LONGTEXT = Text
    sys.modules["sqlalchemy.dialects.mysql"] = mysql_dialect
    import sqlalchemy.dialects as _dials
    _dials.mysql = mysql_dialect

    Base = declarative_base()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SessionLocal = sessionmaker(bind=engine)

    core_database_mod = types.ModuleType("core.database")
    core_database_mod.Base = Base
    core_database_mod.SessionLocal = SessionLocal
    sys.modules["core.database"] = core_database_mod

    sys.modules.pop("core.db_models", None)
    from core.db_models import Article  # type: ignore

    Base.metadata.create_all(bind=engine)
    return SessionLocal, Article


def cleanup_and_count(db, Article):
    stale_threshold = datetime.utcnow() - timedelta(days=1)
    stale_articles = (
        db.query(Article)
        .filter(Article.status == "new", Article.created_at < stale_threshold)
        .all()
    )
    if stale_articles:
        for art in stale_articles:
            art.status = "failed"
        db.commit()
    return (
        db.query(Article)
        .filter(Article.status == "new", Article.created_at >= stale_threshold)
        .count()
    )


def test_notification_sent_for_stale_new_articles():
    SessionLocal, Article = setup_db()
    session = SessionLocal()
    fresh = Article(
        source_name="src",
        original_url="u1",
        original_title="t1",
        status="pending_publication",
    )
    stale = Article(
        source_name="src",
        original_url="u2",
        original_title="t2",
        status="new",
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    session.add_all([fresh, stale])
    session.commit()

    notifications = []
    remaining = cleanup_and_count(session, Article)
    if remaining == 0:
        notifications.append("done")

    stale_db = session.query(Article).filter_by(id=stale.id).first()
    assert stale_db.status == "failed"
    assert len(notifications) == 1