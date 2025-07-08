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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update:", exc_info=context.error)

async def send_new_articles_to_admin(context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        article = db.query(Article).filter(Article.status == 'new').order_by(Article.id).first()
        if not article: return

        article.status = 'pending_initial_approval'; db.commit()
        logger.info(f"Sending article {article.id} for initial approval.")
        
        caption = f"📣 *{escape_markdown(article.original_title)}*\n\nمنبع: `{escape_markdown(article.source_name)}`"
        keyboard = [[
            InlineKeyboardButton("✅ تأیید و پردازش", callback_data=f"approve_{article.id}"),
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
        if 'db' in locals() and db.is_active: db.rollback()
        logger.error(f"Error in send_new_articles_to_admin job: {e}")
    finally:
        if 'db' in locals() and db.is_active: db.close()

async def send_final_approval_to_admin(context: ContextTypes.DEFAULT_TYPE):
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

        article.status = 'sent_for_publication'; db.commit()
        
        final_caption = (f"<b>{escape_html(article.translated_title)}</b>\n\n"
                         f"{escape_html(article.summary)}\n\n"
                         f"منبع: <a href='{article.original_url}'>{escape_html(article.source_name)}</a>")
        
        keyboard_rows = []
        for channel in source.channels:
            if channel.is_active:
                button = InlineKeyboardButton(f"🚀 انتشار در {channel.name}", callback_data=f"publish_{article.id}_{channel.id}")
                keyboard_rows.append([button])
        keyboard_rows.append([InlineKeyboardButton("🗑️ لغو", callback_data=f"discard_{article.id}")])
        reply_markup = InlineKeyboardMarkup(keyboard_rows)

        try:
            await context.bot.edit_message_caption(
                chat_id=article.admin_chat_id,
                message_id=article.admin_message_id,
                caption=final_caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Edited message for final approval of article {article.id}")
        except Exception as e:
            logger.error(f"Failed to edit final approval message for article {article.id}: {e}")
    except Exception as e:
        if 'db' in locals() and db.is_active: db.rollback()
        logger.error(f"Error in send_final_approval_to_admin job: {e}")
    finally:
        if 'db' in locals() and db.is_active: db.close()

async def cleanup_db_job(context: ContextTypes.DEFAULT_TYPE):
    # ... (کد این تابع بدون تغییر است) ...
    pass