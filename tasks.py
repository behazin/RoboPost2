# tasks.py (نسخه نهایی با پردازش مرحله‌ای، بدون JSON و کاملاً اصلاح شده)
import feedparser
import requests
import json
from newspaper import Article as NewspaperArticle, ArticleException
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
            logger.info(f"Vertex AI Model ({settings.GEMINI_MODEL_NAME}) initialized successfully in worker.")
        except Exception as e:
            logger.critical(f"FATAL: Could not initialize Vertex AI Model in worker: {e}", exc_info=True)
            _llm_model = None
    return _llm_model

def get_prompt(filename: str) -> str:
    """محتوای یک فایل پرامپت را می‌خواند."""
    try:
        with open(filename, "r", encoding="utf-8") as f: return f.read().strip()
    except FileNotFoundError: return ""

@celery_app.task
def run_all_fetchers_task():
    logger.info("Scheduler triggered: Fetching all active sources.")
    db: Session = SessionLocal()
    try:
        active_sources = db.query(Source).filter(Source.is_active == True).all()
        for source in active_sources:
            fetch_source_task.delay(source.id)
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
        for entry in feed.entries[:5]: # بررسی ۵ ورودی آخر فید
            if not db.query(Article).filter(Article.original_url == entry.link).first():
                top_image = None
                try:
                    temp_article = NewspaperArticle(entry.link, language='en')
                    temp_article.download(input_html=requests.get(entry.link, headers=headers, timeout=15).text)
                    temp_article.parse()
                    top_image = temp_article.top_image
                except Exception:
                    logger.warning(f"Could not fetch top image for {entry.link}, continuing without it.")

                new_article = Article(
                    source_name=source.name, original_url=entry.link,
                    original_title=entry.title, image_url=top_image, status='new'
                )
                db.add(new_article)
                db.commit()
                logger.info(f"NEW ARTICLE from {source.name}: {entry.title}")
    except Exception as e:
        logger.error(f"Failed to fetch source {source_id} ({source.name}): {e}", exc_info=True)
    finally:
        db.close()

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=3, countdown=10)
def translate_text_task(self, text: str, prompt_text: str) -> str:
    """یک وظیفه عمومی برای ترجمه یا خلاصه‌سازی متن با پرامپت مشخص."""
    if not text: return ""
    logger.info(f"LLM task started (first 50 chars): {text[:50]}...")
    llm = get_llm_model()
    if not llm: raise ConnectionError("LLM model is not available.")
    
    final_prompt = f"{prompt_text}\n---\n{text}"
    try:
        response = llm.generate_content(final_prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"LLM task failed: {e}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=180)
def process_article_task(self, article_id: int):
    """وظیفه هماهنگ‌کننده پردازش مقاله (با منطق جدید و ساده‌تر)."""
    logger.info(f"Coordinating full processing for article_id: {article_id}")
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article: return
        
        # 1. دانلود محتوای کامل
        if not article.original_content:
            try:
                news_article = NewspaperArticle(article.original_url, language='en')
                news_article.download(); news_article.parse()
                if not news_article.text: raise ValueError("Newspaper download failed.")
                article.original_content = news_article.text
                if not article.image_url: article.image_url = news_article.top_image # اطمینان از وجود عکس
                db.commit()
            except Exception as e:
                raise ValueError(f"Newspaper parse failed: {e}")
        
        # 2. ترجمه عنوان
        title_prompt = "Translate the following English title to fluent Persian. Return only the translated text:"
        translated_title = translate_text_task.delay(article.original_title, title_prompt).get(timeout=30)
        article.translated_title = translated_title

        # 3. ترجمه محتوای کامل
        content_prompt = "Translate the following English article content to fluent and natural Persian. Return only the translated text:"
        translated_content = translate_text_task.delay(article.original_content, content_prompt).get(timeout=120)
        article.translated_content = translated_content

        # 4. خلاصه‌سازی محتوای ترجمه شده
        summary_prompt_template = get_prompt("prompt.txt")
        summary = translate_text_task.delay(translated_content, summary_prompt_template).get(timeout=120)
        article.summary = summary
        
        # 5. تغییر وضعیت نهایی برای ارسال به ادمین
        article.status = 'pending_publication'
        db.commit()
        
        logger.info(f"Article {article.id} processed successfully. Ready for final approval.")
    except Exception as e:
        logger.error(f"Critical error in coordinator task for article {article.id}: {e}", exc_info=True)
        if article: article.status = 'failed'; db.commit()
        raise self.retry(exc=e)
    finally:
        db.close()