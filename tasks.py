# tasks.py
import feedparser
import requests
from newspaper import Article as NewspaperArticle
from celery.utils.log import get_task_logger
from sqlalchemy.orm import Session

from celery_app import celery_app
from core.database import SessionLocal
from core.db_models import Source, Article
from core.config import settings

logger = get_task_logger(__name__)
_llm_model = None

def get_llm_model():
    """یک نمونه از مدل Gemini را در worker مقداردهی اولیه کرده و بازمی‌گرداند."""
    global _llm_model
    if _llm_model is None:
        from google.oauth2 import service_account
        import vertexai
        from vertexai.generative_models import GenerativeModel
        try:
            credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_APPLICATION_CREDENTIALS)
            vertexai.init(project=settings.GOOGLE_PROJECT_ID, location=settings.GOOGLE_LOCATION, credentials=credentials)
            _llm_model = GenerativeModel(settings.GEMINI_MODEL_NAME)
            logger.info(f"Vertex AI Model ({settings.GEMINI_MODEL_NAME}) initialized in worker.")
        except Exception as e:
            logger.critical(f"FATAL: Could not initialize Vertex AI Model in worker: {e}", exc_info=True)
    return _llm_model

def get_prompt(filename: str) -> str:
    """محتوای یک فایل پرامپت را می‌خواند."""
    try:
        with open(filename, "r", encoding="utf-8") as f: return f.read().strip()
    except FileNotFoundError: return ""

def _call_llm(prompt_text: str):
    """یک تابع داخلی امن برای فراخوانی Gemini که وظیفه Celery نیست."""
    llm = get_llm_model()
    if not llm: raise ConnectionError("LLM model is not available.")
    try:
        response = llm.generate_content(prompt_text)
        return response.text.strip()
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise

@celery_app.task
def run_all_fetchers_task():
    logger.info("Scheduler triggered: Fetching all active sources.")
    db: Session = SessionLocal()
    try:
        active_sources = db.query(Source).filter(Source.is_active == True).all()
        for source in active_sources: fetch_source_task.delay(source.id)
    finally:
        db.close()

@celery_app.task(autoretry_for=(requests.RequestException,), max_retries=3, countdown=60)
def fetch_source_task(source_id: int):
    db: Session = SessionLocal()
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source: db.close(); return
    try:
        logger.info(f"Fetching: {source.name}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        feed = feedparser.parse(source.rss_url)
        for entry in feed.entries[:30]:
            if not db.query(Article).filter(Article.original_url == entry.link).first():
                top_image = None
                try:
                    temp_article = NewspaperArticle(entry.link, language='en')
                    temp_article.download(input_html=requests.get(entry.link, headers=headers, timeout=15).text)
                    temp_article.parse()
                    top_image = temp_article.top_image
                except Exception: pass
                db.add(Article(source_name=source.name, original_url=entry.link, original_title=entry.title, image_url=top_image, status='new'))
                db.commit()
                logger.info(f"NEW ARTICLE from {source.name}: {entry.title}")
    except Exception as e:
        logger.error(f"Failed to fetch source {source_id}: {e}")
    finally:
        db.close()

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=180)
def process_article_task(self, article_id: int):
    """وظیفه اصلی پردازش مقاله پس از تایید اولیه."""
    logger.info(f"Starting full processing for article_id: {article_id}")
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article: return
        
        # 1. دانلود محتوا
        if not article.original_content:
            try:
                news_article = NewspaperArticle(article.original_url, language='en')
                news_article.download(); news_article.parse()
                if not news_article.text: raise ValueError("Newspaper download failed.")
                article.original_content = news_article.text
                if not article.image_url: article.image_url = news_article.top_image
                db.commit()
            except Exception as e:
                raise ValueError(f"Newspaper parse failed: {e}")
        
        # 2. ترجمه عنوان
        title_prompt = f"Translate the following English title to fluent Persian. Return only the translated text:\n\n{article.original_title}"
        article.translated_title = _call_llm(title_prompt)

        # 3. ترجمه محتوای کامل
        content_prompt = f"Translate the following English article content to fluent and natural Persian. Return only the translated text:\n\n{article.original_content}"
        translated_content = _call_llm(content_prompt)
        article.translated_content = translated_content

        # 4. خلاصه‌سازی محتوای ترجمه شده
        summary_prompt = f"{get_prompt('prompt.txt')}\n---\n{translated_content}"
        article.summary = _call_llm(summary_prompt)

        # 5. تغییر وضعیت نهایی
        article.status = 'pending_publication'
        db.commit()
        
        logger.info(f"Article {article.id} processed successfully. Ready for final approval.")
    except Exception as e:
        logger.error(f"Critical error processing article {article_id}: {e}", exc_info=True)
        if article: article.status = 'failed'; db.commit()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=60)
def translate_title_task(self, article_id: int):
    """Translate only the article title and store it."""
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article or article.translated_title:
            return

        prompt = f"{get_prompt('translate_prompt.txt')}\n{article.original_title}"
        article.translated_title = _call_llm(prompt)
        db.commit()
        logger.info(f"Translated title for article {article_id}")
    except Exception as e:
        logger.error(f"Failed to translate title for article {article_id}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=60)
def score_title_task(self, article_id: int):
    """Score the article headline and store it."""
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article or article.news_value_score is not None:
            return

        prompt = f"{get_prompt('score_prompt.txt')}\n{article.original_title}"
        result = _call_llm(prompt)
        try:
            article.news_value_score = int(result)
        except (ValueError, TypeError):
            article.news_value_score = 0
        db.commit()
        logger.info(f"Scored title for article {article_id}")
    except Exception as e:
        logger.error(f"Failed to score title for article {article_id}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()    