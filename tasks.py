# tasks.py
import feedparser
import requests
from newspaper import Article as NewspaperArticle
from celery.utils.log import get_task_logger
from celery import chord
import asyncio
from sqlalchemy.orm import Session
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from utils import escape_markdown, escape_markdown_url
from celery_app import celery_app
from core.database import SessionLocal
from core.db_models import Source, Article, Channel
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

# Helper utilities for running Telegram API calls with a fresh event loop
def _run_in_new_loop(coro):
    """Run an async coroutine in a dedicated event loop."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(coro)
        return result
    finally:
        if logger:
            logger.info("Running coroutine in loop %s", id(loop))
        loop.close()
        asyncio.set_event_loop(None)

async def _send_photo(token, admin_id, url, caption, markup):
    async with Bot(token=token) as bot:
        msg = await bot.send_photo(
            chat_id=admin_id,
            photo=url,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
        )
        return msg

async def _send_text(token, admin_id, text, markup):
    async with Bot(token=token) as bot:
        msg = await bot.send_message(
            chat_id=admin_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
        )
        return msg

async def _edit_caption(token, chat_id, message_id, caption, markup):
    async with Bot(token=token) as bot:
        msg = await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
        )
        return msg

async def _edit_text(token, chat_id, message_id, text, markup):
    async with Bot(token=token) as bot:
        msg = await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return msg




@celery_app.task
def run_all_fetchers_task():
    logger.info("Scheduler triggered: Fetching all active sources.")
    db: Session = SessionLocal()
    try:
        active_sources = db.query(Source).filter(Source.is_active == True).all()
        tasks = [fetch_source_task.s(src.id) for src in active_sources]
        if tasks:
            chord(tasks)(notify_fetch_complete_task.s())
        else:
            notify_fetch_complete_task.delay()
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=60, rate_limit="15/m")
def send_initial_approval_task(self, _results, article_id: int):
    """Send translated headline to admins for approval."""
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article or article.status != 'new':
        db.close()
        return
    try:
        score = article.news_value_score or 0
        translated_title = article.translated_title or article.original_title

        article.status = 'pending_initial_approval'
        db.commit()

        score_stars = "\u2b50" * (score // 2) if score else " (بدون نمره)"
        caption = (
            f"\U0001F4E3 *{escape_markdown(translated_title)}*\n\n"
            f"منبع: `{escape_markdown(article.source_name)}`\n"
            f"ارزش خبری: {escape_markdown(str(score))}/10 {escape_markdown(score_stars)}"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ تأیید و پردازش", callback_data=f"approve_{article.id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{article.id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        any_success = False
        for admin_id in settings.admin_ids_list:
            try:
                sent_message = None
                if article.image_url:
                    sent_message = _run_in_new_loop(
                        _send_photo(
                            settings.TELEGRAM_BOT_TOKEN,
                            admin_id,
                            article.image_url,
                            caption,
                            reply_markup,
                        )
                    )
                else:
                    sent_message = _run_in_new_loop(
                        _send_text(
                            settings.TELEGRAM_BOT_TOKEN,
                            admin_id,
                            caption,
                            reply_markup,
                        )
                    )
                if sent_message:
                    any_success = True
                    if article.admin_chat_id is None:
                        article.admin_chat_id = sent_message.chat_id
                        article.admin_message_id = sent_message.message_id
                        db.commit()
                logger.info(f"Initial approval sent to admin {admin_id}")
            except Exception as e:
                logger.warning(f"Failed to send initial approval to admin {admin_id}: {e}")
        if not any_success:
            article.status = 'new'
            db.commit()
            logger.error(
                f"Initial approval for article {article.id} could not be delivered to any admin."
            )
                
    except Exception as e:
        if db.is_active:
            db.rollback()
        logger.error(
            f"Error sending initial approval for article {article_id}: {e}",
            exc_info=True,
        )
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=60, rate_limit="15/m")
def send_final_approval_task(self, article_id: int):
    """Edit admin message with processed article for publication."""
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    try:
        if not article or article.status != 'pending_publication' or not article.admin_chat_id or not article.admin_message_id:
            if article and article.status == 'pending_publication':
                article.status = 'failed'
                db.commit()
            return

        source = db.query(Source).filter(Source.name == article.source_name).first()
        if not source or not source.channels:
            article.status = 'archived_unlinked'
            db.commit()
            return

        final_caption = (
            f"*{escape_markdown(article.translated_title)}*\n\n"
            f"{escape_markdown(article.summary)}\n\n"
            f"منبع: [{escape_markdown(article.source_name)}]({escape_markdown_url(article.original_url)})"
        )

        keyboard_rows = []
        for channel in source.channels:
            if channel.is_active:
                button = InlineKeyboardButton(
                    f"🚀 انتشار در {channel.name}", callback_data=f"publish_{article.id}_{channel.id}"
                )
                keyboard_rows.append([button])
        keyboard_rows.append([
            InlineKeyboardButton("🗑️ لغو کلی", callback_data=f"discard_{article.id}")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard_rows)

        if article.image_url:
            try:
                _run_in_new_loop(
                    _edit_caption(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        final_caption,
                        reply_markup,
                    )
                )
            except Exception:
                _run_in_new_loop(
                    _send_photo(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.image_url,
                        final_caption,
                        reply_markup,
                    )
                )
        else:
            try:
                _run_in_new_loop(
                    _edit_text(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        final_caption,
                        reply_markup,
                    )
                )
            except Exception:
                _run_in_new_loop(
                    _send_text(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        final_caption,
                        reply_markup,
                    )
                )
        logger.info("Final approval sent")
        article.status = 'sent_for_publication'
        db.commit()
    except Exception as e:
        if db.is_active:
            db.rollback()
        logger.error(f"Failed to send final approval for article {article_id}: {e}", exc_info=True)
        raise self.retry(exc=e)
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
        send_tasks = []
        for entry in feed.entries[:30]:
            if not db.query(Article).filter(Article.original_url == entry.link).first():
                top_image = None
                try:
                    temp_article = NewspaperArticle(entry.link, language='en')
                    temp_article.download(input_html=requests.get(entry.link, headers=headers, timeout=15).text)
                    temp_article.parse()
                    top_image = temp_article.top_image
                except Exception:
                    pass
                article = Article(
                    source_name=source.name,
                    original_url=entry.link,
                    original_title=entry.title,
                    image_url=top_image,
                    status='new',
                )
                db.add(article)
                db.commit()
                logger.info(f"NEW ARTICLE from {source.name}: {entry.title}")
                header = [translate_title_task.s(article.id), score_title_task.s(article.id)]
                result = chord(header)(send_initial_approval_task.s(article.id))
                send_tasks.append(result)
        if send_tasks:
            logger.info("Scheduling notify_initial_send_complete_task after %d send tasks", len(send_tasks))
            chord(send_tasks)(notify_initial_send_complete_task.s())
    except Exception as e:
        logger.error(f"Failed to fetch source {source_id}: {e}")
    finally:
        db.close()


@celery_app.task
def notify_initial_send_complete_task(_results=None):
    """Notify admins when all initial send tasks are finished."""
    logger.info("All initial sends completed; notifying admins")
    for admin_id in settings.admin_ids_list:
        try:
            _run_in_new_loop(
                _send_text(
                    settings.TELEGRAM_BOT_TOKEN,
                    admin_id,
                    "تمامی پست‌ها ارسال شد",
                    None,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")




@celery_app.task
def notify_fetch_complete_task(_results=None):
    for admin_id in settings.admin_ids_list:
        try:
            _run_in_new_loop(
                _send_text(
                    settings.TELEGRAM_BOT_TOKEN,
                    admin_id,
                    "جمع‌آوری منابع تمام شد",
                    None,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


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
        send_final_approval_task.delay(article.id)
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


@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=60, rate_limit="15/m")
def publish_article_task(self, article_id: int, channel_id: int):
    """Send the article to a channel and update admin message."""
    db: Session = SessionLocal()
    article = db.query(Article).filter(Article.id == article_id).first()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not article or not channel or article.status != 'sent_for_publication':
        db.close()
        return
    try:
        final_caption = (
            "\u200F"
            f"*{escape_markdown(article.translated_title)}*\n\n"
            f"{escape_markdown(article.summary)}\n\n"
            f"\u200E {escape_markdown(channel.telegram_channel_id)}"
        )

        if article.image_url:
            _run_in_new_loop(
                _send_photo(
                    settings.TELEGRAM_BOT_TOKEN,
                    channel.telegram_channel_id,
                    article.image_url,
                    final_caption,
                    None,
                )
            )
        else:
            _run_in_new_loop(
                _send_text(
                    settings.TELEGRAM_BOT_TOKEN,
                    channel.telegram_channel_id,
                    final_caption,
                    None,
                )
            )

        article.status = 'published'
        db.commit()

        success_msg = escape_markdown(f"🚀 با موفقیت در کانال {channel.name} منتشر شد.")
        try:
            if article.image_url:
                _run_in_new_loop(
                    _edit_caption(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        success_msg,
                        None,
                    )
                )
            else:
                _run_in_new_loop(
                    _edit_text(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        success_msg,
                        None,
                    )
                )
        except Exception:
            _run_in_new_loop(
                _send_text(
                    settings.TELEGRAM_BOT_TOKEN,
                    article.admin_chat_id,
                    success_msg,
                    None,
                )
            )

        logger.info(f"Article {article.id} published to {channel.name}")
    except Exception as e:
        if db.is_active:
            db.rollback()
        error_msg = escape_markdown(f"⚠️ خطا در انتشار به کانال {channel.name}: {e}")
        try:
            if article.image_url:
                _run_in_new_loop(
                    _edit_caption(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        error_msg,
                        None,
                    )
                )
            else:
                _run_in_new_loop(
                    _edit_text(
                        settings.TELEGRAM_BOT_TOKEN,
                        article.admin_chat_id,
                        article.admin_message_id,
                        error_msg,
                        None,
                    )
                )
        except Exception:
            _run_in_new_loop(
                _send_text(
                    settings.TELEGRAM_BOT_TOKEN,
                    article.admin_chat_id,
                    error_msg,
                    None,
                )
            )
        logger.error(f"Failed to publish article {article.id} to channel {channel.name}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()
        
        