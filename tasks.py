# tasks.py (نسخه نهایی و کاملاً اصلاح شده)
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
    global _llm_model
    if _llm_model is None:
        from google.oauth2 import service_account
        import vertexai
        from vertexai.generative_models import GenerativeModel
        credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_APPLICATION_CREDENTIALS)
        vertexai.init(project=settings.GOOGLE_PROJECT_ID, location=settings.GOOGLE_LOCATION, credentials=credentials)
        _llm_model = GenerativeModel(settings.GEMINI_MODEL_NAME)
        logger.info(f"Vertex AI Model ({settings.GEMINI_MODEL_NAME}) initialized in worker.")
    return _llm_model

def get_prompt(filename: str) -> str:
    try:
        with open(filename, "r", encoding="utf-8") as f: return f.read().strip()
    except FileNotFoundError: return ""

@celery_app.task
def run_all_fetchers_task():
    logger.info("Scheduler triggered: Fetching all active sources.")
    db: Session = SessionLocal()
    try:
        active_sources = db.query(Source).filter(Source.is_active == True).all()
        logger.info(f"Found {len(active_sources)} active sources to process.")
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
        feed = feedparser.parse(source.rss_url)
        for entry in feed.entries[:40]:
            if not db.query(Article).filter(Article.original_url == entry.link).first():
                top_image = None
                try:
                    temp_article = NewspaperArticle(entry.link, language='en')
                    temp_article.download(input_html=requests.get(entry.link, timeout=10).text)
                    temp_article.parse()
                    top_image = temp_article.top_image
                except Exception:
                    logger.warning(f"Could not fetch top image for {entry.link}, continuing without it.")
                db.add(Article(source_name=source.name, original_url=entry.link, original_title=entry.title, image_url=top_image, status='new'))
                db.commit()
                logger.info(f"NEW ARTICLE from {source.name}: {entry.title}")
    except Exception as e:
        logger.error(f"Failed to fetch source {source_id}: {e}")
    finally:
        db.close()

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=3, countdown=10)
def translate_title_task(self, title: str) -> str:
    """وظیفه جدید و سبک برای ترجمه عنوان."""
    logger.info(f"Translating title: {title}")
    llm = get_llm_model()
    prompt = f"Translate the following English title to fluent Persian. Return only the translated text, without any explanations or quotation marks:\n\n{title}"
    try:
        response = llm.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Could not translate title '{title}': {e}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=180)
def process_article_task(self, article_id: int):
    """
    اصلاح شد: منطق پردازش پاسخ JSON از Gemini مقاوم‌تر شده است.
    """
    logger.info(f"Starting full processing for article_id: {article_id}")
    db: Session = SessionLocal()
    llm = get_llm_model()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article: return
        
        # ۱. دانلود محتوا (در صورت نیاز)
        if not article.original_content:
            try:
                news_article = NewspaperArticle(article.original_url, language='en')
                news_article.download()
                news_article.parse()
                if not news_article.text: raise ValueError("Newspaper could not extract content.")
                article.original_content = news_article.text
                if not article.image_url and news_article.top_image:
                     article.image_url = news_article.top_image
                db.commit()
            except Exception as e:
                raise ValueError(f"Newspaper download/parse failed: {e}")

        # ۲. ترجمه و خلاصه‌سازی با یک فراخوانی Gemini
        summary_prompt_template = get_prompt("prompt.txt")
        translate_prompt_template = get_prompt("translate_prompt.txt")
        
        # ترکیب پرامپت‌ها برای یک درخواست واحد
        prompt = (f"{translate_prompt_template}\n\n"
                  f"And after translating, create a summary based on these rules: {summary_prompt_template}\n\n"
                  f"--- ARTICLE ---\nTitle: {article.original_title}\n\nContent: {article.original_content}")
        
        response = llm.generate_content(prompt)
        
        # --- بخش کلیدی اصلاح شده ---
        # استخراج هوشمند JSON از پاسخ متنی مدل
        response_text = response.text.strip()
        json_start_index = response_text.find('{')
        json_end_index = response_text.rfind('}') + 1
        
        if json_start_index == -1 or json_end_index == 0:
            raise json.JSONDecodeError("No JSON object found in the response.", response_text, 0)
            
        json_string = response_text[json_start_index:json_end_index]
        result = json.loads(json_string)
        # --- پایان بخش اصلاح شده ---
        
        # ۳. ذخیره نتایج
        article.translated_title = result.get('translated_title', article.original_title)
        article.translated_content = result.get('translated_content')
        article.summary = result.get('summary')
        article.status = 'pending_publication'
        db.commit()
        
        logger.info(f"Article {article.id} processed successfully. Ready for final approval.")
    except Exception as e:
        logger.error(f"Critical error processing article {article_id}: {e}", exc_info=True)
        if article: article.status = 'failed'; db.commit()
        raise self.retry(exc=e)
    finally:
        db.close()