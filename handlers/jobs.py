# handlers/jobs.py
from telegram.ext import ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from utils import escape_markdown, escape_html, logger
from core.database import get_db
from core.db_models import Article, Source, Channel
from core.config import settings

# --- بخش جدید: تابع کمکی برای ترجمه غیرهمزمان در خود ربات ---
_llm_model_bot = None

async def translate_title_in_bot(title: str) -> str:
    """یک تابع async برای ترجمه عنوان که مستقیما در پروسه bot اجرا می‌شود."""
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
            return title # در صورت خطا، عنوان اصلی را برمی‌گرداند

    prompt = f"Translate the following English title to fluent Persian. Return only the translated text, without any explanations or quotation marks:\n\n{title}"
    try:
        # استفاده از متد async کتابخانه برای جلوگیری از مسدود شدن
        response = await _llm_model_bot.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Could not translate title '{title}' in bot process: {e}")
        return title # در صورت خطا، عنوان اصلی را برمی‌گرداند

# -------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update:", exc_info=context.error)

async def send_new_articles_to_admin(context: ContextTypes.DEFAULT_TYPE):
    """مقالات جدید را با عنوان ترجمه شده برای تایید اولیه ارسال می‌کند."""
    db: Session = next(get_db())
    article = None
    try:
        article = db.query(Article).filter(Article.status == 'new').order_by(Article.id).first()
        if not article: return

        # اصلاح کلیدی: ترجمه عنوان به صورت غیرهمزمان قبل از ارسال
        logger.info(f"Translating title for article {article.id} directly in bot job...")
        translated_title = await translate_title_in_bot(article.original_title)
            
        article.translated_title = translated_title
        article.status = 'pending_initial_approval'
        db.commit()
        
        caption = f"📣 *{escape_markdown(translated_title)}*\n\nمنبع: `{escape_markdown(article.source_name)}`"
        keyboard = [[
            InlineKeyboardButton("✅ تأیید و پردازش", callback_data=f"approve_{article.id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{article.id}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Sending article {article.id} for initial approval.")
        for admin_id in settings.admin_ids_list:
            try:
                if article.image_url:
                    await context.bot.send_photo(chat_id=admin_id, photo=article.image_url, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                logger.warning(f"Failed to send initial approval to admin {admin_id}: {e}")
    
    except Exception as e:
        if 'db' in locals() and db.is_active: db.rollback()
        if article: # اگر مقاله انتخاب شده بود اما در ادامه خطا داد، به وضعیت new برگردان
            article.status = 'new'
            db.commit()
        logger.error(f"Error in send_new_articles_to_admin job: {e}", exc_info=True)
    finally:
        if 'db' in locals() and db.is_active: db.close()

async def send_final_approval_to_admin(context: ContextTypes.DEFAULT_TYPE):
    """مقاله پردازش شده را پیدا کرده و پیام اولیه ادمین را ویرایش می‌کند."""
    db: Session = next(get_db())
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
            # ویرایش پیام قبلی با پیش‌نمایش نهایی
            await context.bot.edit_message_caption(
                chat_id=article.admin_chat_id,
                message_id=article.admin_message_id,
                caption=final_caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Edited message for final approval of article {article.id}")
        except Exception as e:
            # اگر ویرایش پیام اولیه (که عکس داشت) ممکن نبود، پیام جدید ارسال کن
            logger.warning(f"Could not edit original message for article {article.id}, sending a new one. Error: {e}")
            for admin_id in settings.admin_ids_list:
                await context.bot.send_message(chat_id=admin_id, text=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    except Exception as e:
        if 'db' in locals() and db.is_active: db.rollback()
        logger.error(f"Error in send_final_approval_to_admin job: {e}")
    finally:
        if 'db' in locals() and db.is_active: db.close()


async def cleanup_db_job(context: ContextTypes.DEFAULT_TYPE):
    """مقالات قدیمی را از دیتابیس بر اساس وضعیت و قدمتشان پاک می‌کند."""
    logger.info("Running scheduled job to clean up old articles...")
    db: Session = next(get_db())
    try:
        now = datetime.utcnow()
        
        # حذف مقالات رد شده یا ناموفق قدیمی‌تر از ۲ روز
        deleted_rejected = db.query(Article).filter(
            Article.status.in_(['rejected', 'discarded', 'failed']),
            Article.created_at < now - timedelta(days=2)
        ).delete(synchronize_session=False)

        # حذف مقالات جدید که بیش از ۱ روز در صف مانده‌اند
        deleted_new = db.query(Article).filter(
            Article.status.in_(['new', 'pending_initial_approval']),
            Article.created_at < now - timedelta(days=1)
        ).delete(synchronize_session=False)

        # حذف مقالات منتشر شده قدیمی‌تر از ۷ روز
        deleted_published = db.query(Article).filter(
            Article.status == 'published',
            Article.created_at < now - timedelta(days=7)
        ).delete(synchronize_session=False)

        db.commit()
        
        total_deleted = (deleted_rejected or 0) + (deleted_new or 0) + (deleted_published or 0)
        if total_deleted > 0:
            logger.info(f"Successfully deleted {total_deleted} old articles.")
        else:
            logger.info("No old articles to delete.")
            
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cleanup old articles: {e}", exc_info=True)
    finally:
        db.close()