# handlers/jobs.py
from telegram.ext import ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from utils import escape_markdown, logger
from core.database import get_db
from core.db_models import Article, Source, Channel
from core.config import settings
from tasks import translate_title_task # <--- import صحیح

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update:", exc_info=context.error)

async def send_new_articles_to_admin(context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    article = None
    try:
        article = db.query(Article).filter(Article.status == 'new').order_by(Article.id).first()
        if not article: return

        logger.info(f"Translating title for article {article.id}...")
        try:
            task_result = translate_title_task.delay(article.original_title)
            translated_title = task_result.get(timeout=20)
            article.translated_title = translated_title
        except Exception as e:
            logger.error(f"Title translation failed for article {article.id}. Skipping. Error: {e}")
            article.status = 'failed'; db.commit()
            return

        article.status = 'pending_initial_approval'; db.commit()
        
        caption = f"📣 *{escape_markdown(article.translated_title)}*\n\nمنبع: `{escape_markdown(article.source_name)}`"
        keyboard = [[
            InlineKeyboardButton("✅ تأیید", callback_data=f"approve_{article.id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{article.id}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for admin_id in settings.admin_ids_list:
            try:
                if article.image_url:
                    await context.bot.send_photo(chat_id=admin_id, photo=article.image_url, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                logger.warning(f"Failed to send initial approval to admin {admin_id}: {e}")
    except Exception as e:
        db.rollback(); logger.error(f"Error in send_new_articles_to_admin job: {e}")
    finally:
        if 'db' in locals() and db.is_active: db.close()

async def send_final_approval_to_admin(context: ContextTypes.DEFAULT_TYPE):
    """هر ۳۰ ثانیه یک مقاله پردازش شده را برای تایید نهایی به ادمین مربوطه ارسال می‌کند."""
    db: Session = next(get_db())
    try:
        article = db.query(Article).filter(Article.status == 'pending_publication').order_by(Article.id).first()
        if not article: return

        source = db.query(Source).filter(Source.name == article.source_name).first()
        if not source or not source.channels:
            article.status = 'archived_unlinked'; db.commit()
            logger.warning(f"Article {article.id} has no linked channels. Archiving."); return

        article.status = 'sent_for_publication'; db.commit()
        
        for channel in source.channels:
            if not channel.is_active: continue
            
            final_caption = (f"<b>{escape_html(article.translated_title)}</b>\n\n"
                             f"{escape_html(article.summary)}\n\n"
                             f"منبع: <a href='{article.original_url}'>{escape_html(article.source_name)}</a>\n"
                             f"<b>مقصد: {escape_html(channel.name)}</b>")
            
            keyboard = [[
                InlineKeyboardButton(f"🚀 انتشار", callback_data=f"publish_{article.id}_{channel.id}"),
                InlineKeyboardButton("🗑️ لغو", callback_data=f"discard_{article.id}"),
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                if article.image_url:
                    await context.bot.send_photo(chat_id=channel.admin_group_id, photo=article.image_url, caption=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                else:
                    await context.bot.send_message(chat_id=channel.admin_group_id, text=final_caption, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                logger.info(f"Sent article {article.id} for final approval to admin group {channel.admin_group_id} for channel {channel.name}")
            except Exception as e:
                logger.error(f"Failed to send final approval for article {article.id} to admin group {channel.admin_group_id}: {e}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in send_final_approval_to_admin job: {e}")
        if 'article' in locals() and article: article.status = 'pending_publication'; db.commit()
    finally:
        db.close()

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