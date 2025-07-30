# handlers/jobs.py
from telegram.ext import ContextTypes
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from utils import logger
from core.database import get_db
from core.db_models import Article
from tasks import translate_title_task, score_title_task

def dispatch_preprocess_tasks():
    """Dispatch translation and scoring tasks for new articles."""
    db: Session = next(get_db())
    try:
        articles = db.query(Article).filter(Article.status == 'new').all()
        for article in articles:
            if article.translated_title is None:
                translate_title_task.delay(article.id)
            if article.news_value_score is None:
                score_title_task.delay(article.id)
    except Exception as e:
        logger.error(f"Failed to dispatch preprocess tasks: {e}")
    finally:
        db.close()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update:", exc_info=context.error)

async def cleanup_db_job(context: ContextTypes.DEFAULT_TYPE):
    """مقالات قدیمی را از دیتابیس پاک می‌کند."""
    db: Session = next(get_db())
    try:
        now = datetime.utcnow()
        deleted_rejected = db.query(Article).filter(Article.status.in_(['rejected', 'discarded', 'failed']), Article.created_at < now - timedelta(days=2)).delete(synchronize_session=False)
        deleted_new = db.query(Article).filter(Article.status.in_(['new','pending_initial_approval']), Article.created_at < now - timedelta(days=1)).delete(synchronize_session=False)
        deleted_published = db.query(Article).filter(Article.status == 'published', Article.created_at < now - timedelta(days=7)).delete(synchronize_session=False)
        db.commit()
        total_deleted = (deleted_rejected or 0) + (deleted_new or 0) + (deleted_published or 0)
        if total_deleted > 0:
            logger.info(f"Successfully deleted {total_deleted} old articles.")
    except Exception as e:
        db.rollback(); logger.error(f"Failed to cleanup old articles: {e}")
    finally:
        db.close()
        