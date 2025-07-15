# handlers/jobs.py
import asyncio
from telegram.ext import ContextTypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from utils import escape_markdown, escape_html, logger
from core.database import get_db
from core.db_models import Article, Source, Channel
from core.config import settings
from tasks import process_article_task

_llm_model_bot = None

async def _initialize_llm_in_bot():
    """یک نمونه از مدل Gemini را در پروسه bot مقداردهی اولیه می‌کند."""
    global _llm_model_bot
    if _llm_model_bot is None:
        from google.oauth2 import service_account
        import vertexai
        from vertexai.generative_models import GenerativeModel
        try:
            credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_APPLICATION_CREDENTIALS)
            vertexai.init(project=settings.GOOGLE_PROJECT_ID, location=settings.GOOGLE_LOCATION, credentials=credentials)
            _llm_model_bot = GenerativeModel(settings.GEMINI_MODEL_NAME)
            logger.info(f"Vertex AI Model initialized successfully in BOT process.")
        except Exception as e:
            logger.error(f"Could not initialize LLM in bot process: {e}")
            _llm_model_bot = "failed" # برای جلوگیری از تلاش مجدد
    return _llm_model_bot

async def _get_translation(title: str) -> str:
    """عنوان را به صورت غیرهمزمان ترجمه می‌کند."""
    model = await _initialize_llm_in_bot()
    if model == "failed" or not model: return title
    
    prompt = f"Translate the following English title to fluent Persian. Return only the translated text, without any explanations or quotation marks:\n\n{title}"
    try:
        response = await model.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Could not translate title '{title}' in bot process: {e}")
        return title

async def _get_score(title: str) -> int:
    """به عنوان به صورت غیرهمزمان نمره ارزش خبری می‌دهد."""
    model = await _initialize_llm_in_bot()
    if model == "failed" or not model: return 0

    try:
        with open("score_prompt.txt", "r", encoding="utf-8") as f:
            prompt_template = f.read().strip()
    except FileNotFoundError:
        prompt_template = "Score the following headline from 1 to 10. Return only the number:"

    prompt = f"{prompt_template}\n{title}"
    try:
        response = await model.generate_content_async(prompt)
        return int(response.text.strip())
    except (ValueError, TypeError, Exception) as e:
        logger.error(f"Could not get score for title '{title}': {e}")
        return 0 # در صورت خطا، نمره پیش‌فرض صفر برمی‌گرداند

# -------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update:", exc_info=context.error)

async def send_new_articles_to_admin(context: ContextTypes.DEFAULT_TYPE):
    """مقالات جدید را با عنوان ترجمه شده و نمره ارزش خبری برای تایید اولیه ارسال می‌کند."""
    db: Session = next(get_db())
    article = None
    try:
        # اصلاح: مقالات بدون نمره را در اولویت قرار می‌دهد
        article = db.query(Article).filter(Article.status == 'new', Article.news_value_score == None).order_by(Article.id).first()
        if not article: return

        logger.info(f"Processing article {article.id} for scoring and translation...")
        
        # اجرای همزمان ترجمه و نمره‌دهی برای حداکثر سرعت
        translation_task = _get_translation(article.original_title)
        scoring_task = _get_score(article.original_title)
        translated_title, score = await asyncio.gather(translation_task, scoring_task)
            
        article.translated_title = translated_title
        article.news_value_score = score
        article.status = 'pending_initial_approval'
        db.commit()
        
        score_stars = "⭐️" * (score // 2) if score else " (بدون نمره)"
        caption = (f"📣 *{escape_markdown(translated_title)}*\n\n"
                   f"منبع: `{escape_markdown(article.source_name)}`\n"
                   f"ارزش خبری: {escape_markdown(str(score))}/10 {score_stars}")

        keyboard = [[
            InlineKeyboardButton("✅ تأیید و پردازش", callback_data=f"approve_{article.id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{article.id}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Sending article {article.id} for initial approval.")
        for admin_id in settings.admin_ids_list:
            try:
                sent_message = None
                if article.image_url:
                    sent_message = await context.bot.send_photo(chat_id=admin_id, photo=article.image_url, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    sent_message = await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                
                if sent_message and article.admin_chat_id is None:
                    article.admin_chat_id = sent_message.chat_id
                    article.admin_message_id = sent_message.message_id
                    db.commit()
            except Exception as e:
                logger.warning(f"Failed to send initial approval to admin {admin_id}: {e}")
    
    except Exception as e:
        if 'db' in locals() and db.is_active: db.rollback()
        logger.error(f"Error in send_new_articles_to_admin job: {e}", exc_info=True)
    finally:
        if 'db' in locals() and db.is_active: db.close()

async def send_final_approval_to_admin(context: ContextTypes.DEFAULT_TYPE):
    """مقاله پردازش شده را پیدا کرده و پیام اولیه ادمین را ویرایش می‌کند."""
    db: Session = next(get_db())
    article = None
    try:
        article = db.query(Article).filter(Article.status == 'pending_publication').order_by(Article.id).first()
        if not article or not article.admin_chat_id or not article.admin_message_id:
            if article: article.status = 'failed'; db.commit()
            return

        source = db.query(Source).filter(Source.name == article.source_name).first()
        if not source or not source.channels:
            article.status = 'archived_unlinked'; db.commit()
            return

        article.status = 'sent_for_publication'
        db.commit()
        
        final_caption = (f"<b>{escape_html(article.translated_title)}</b>\n\n"
                         f"{escape_html(article.summary)}\n\n"
                         f"منبع: <a href='{article.original_url}'>{escape_html(article.source_name)}</a>")
        
        keyboard_rows = []
        for channel in source.channels:
            if channel.is_active:
                button = InlineKeyboardButton(f"🚀 انتشار در {channel.name}", callback_data=f"publish_{article.id}_{channel.id}")
                keyboard_rows.append([button])
        keyboard_rows.append([InlineKeyboardButton("🗑️ لغو کلی", callback_data=f"discard_{article.id}")])
        reply_markup = InlineKeyboardMarkup(keyboard_rows)

        try:
            # --- بخش کلیدی و اصلاح شده ---
            # اگر پیام اولیه عکس داشته باشد، کپشن آن را ویرایش می‌کنیم
            if article.image_url:
                await context.bot.edit_message_caption(
                    chat_id=article.admin_chat_id, message_id=article.admin_message_id,
                    caption=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.HTML
                )
            # در غیر این صورت، متن پیام را ویرایش می‌کنیم
            else:
                await context.bot.edit_message_text(
                    chat_id=article.admin_chat_id, message_id=article.admin_message_id,
                    text=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            logger.info(f"Edited message for final approval of article {article.id}")
        except Exception as e:
            logger.error(f"Failed to edit final approval message for article {article.id}: {e}", exc_info=True)
    except Exception as e:
        if db.is_active: db.rollback()
        logger.error(f"Error in send_final_approval_to_admin job: {e}")
    finally:
        if db.is_active: db.close()

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