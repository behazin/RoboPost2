# handlers/callback_handlers.py (نسخه نهایی و کاملاً اصلاح شده)
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError
from sqlalchemy.orm import Session

from utils import escape_html, escape_markdown, logger
from core.database import get_db
from core.db_models import Article, Channel
from tasks import process_article_task

async def edit_message_safely(query, new_text: str, **kwargs):
    """یک تابع کمکی برای ویرایش هوشمند پیام (متن یا کپشن)."""
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=new_text, **kwargs)
        else:
            await query.edit_message_text(text=new_text, **kwargs)
    except TelegramError as e:
        # اگر پیام خیلی قدیمی باشد یا تغییری نکرده باشد، تلگرام خطا می‌دهد.
        # ما این خطا را نادیده می‌گیریم تا از لاگ‌های اضافی جلوگیری کنیم.
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Could not edit message: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمام کلیک‌های روی دکمه‌های اینلاین را مدیریت می‌کند."""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split('_')
    action = data_parts[0]
    article_id = int(data_parts[1])

    db: Session = next(get_db())
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            await query.edit_message_text("این مقاله دیگر وجود ندارد.")
            return

        if action == 'approve':
            await handle_approve(query, article, db)
        elif action == 'reject':
            await handle_reject(query, article, db)
        elif action == 'publish':
            channel_id_to_publish = int(data_parts[2])
            await handle_publish(query, article, channel_id_to_publish, context, db)
        elif action == 'discard':
            await handle_discard(query, article, db)
    except Exception as e:
        logger.error(f"Error in button_callback for article {article_id}: {e}", exc_info=True)
    finally:
        db.close()

async def handle_approve(query, article, db):
    """منطق دکمه تایید اولیه (اصلاح نهایی)."""
    if article.status != 'pending_initial_approval':
        await edit_message_safely(query, "این مورد قبلا پردازش شده است.", reply_markup=None)
        return
    
    process_article_task.delay(article.id)
    article.status = 'approved'
    db.commit()
    
    # اصلاح کلیدی: فقط یک پیام ساده و بدون ریسک خطا نمایش می‌دهیم.
    new_text = "✅ تایید اولیه شد. پردازش مقاله در پس‌زمینه آغاز شد."
    await edit_message_safely(query, new_text, reply_markup=None)
    logger.info(f"Article {article.id} approved by {query.from_user.id}, task sent to queue.")

async def handle_reject(query, article, db):
    """منطق دکمه رد اولیه (اصلاح نهایی)."""
    if article.status != 'pending_initial_approval':
        await edit_message_safely(query, "این مورد قبلا پردازش شده است.", reply_markup=None)
        return
    
    article.status = 'rejected'
    db.commit()
    
    # اصلاح کلیدی: فقط یک پیام ساده و بدون ریسک خطا نمایش می‌دهیم.
    new_text = "❌ خبر رد شد."
    await edit_message_safely(query, new_text, reply_markup=None)
    logger.info(f"Article {article.id} rejected by {query.from_user.id}.")

async def handle_publish(query, article, channel_id, context, db):
    """منطق دکمه انتشار نهایی."""
    if article.status != 'sent_for_publication':
        await edit_message_safely(query, "این مورد قبلا منتشر یا لغو شده است.", reply_markup=None)
        return

    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        await edit_message_safely(query, "خطا: کانال مقصد یافت نشد.")
        return
    
    try:
        final_caption = (f"<b>{escape_html(article.translated_title)}</b>\n\n"
                         f"{escape_html(article.summary)}\n\n"
                         f"منبع: <a href='{article.original_url}'>{escape_html(article.source_name)}</a>")
        
        if article.image_url:
            await context.bot.send_photo(chat_id=channel.telegram_channel_id, photo=article.image_url, caption=final_caption, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(chat_id=channel.telegram_channel_id, text=final_caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

        article.status = 'published'
        db.commit()
        await edit_message_safely(query, f"🚀 با موفقیت در کانال {escape_html(channel.name)} منتشر شد.", reply_markup=None, parse_mode=ParseMode.HTML)
        logger.info(f"Article {article.id} published to {channel.name} by {query.from_user.id}")
    except TelegramError as e:
        await edit_message_safely(query, f"⚠️ خطا در انتشار به کانال {escape_html(channel.name)}: {e}", parse_mode=ParseMode.HTML)
        logger.error(f"Failed to publish article {article.id} to channel {channel.name}: {e}")

async def handle_discard(query, article, db):
    """منطق دکمه لغو انتشار."""
    if article.status != 'sent_for_publication':
        await edit_message_safely(query, "این مورد قبلا پردازش شده است.", reply_markup=None)
        return
    
    article.status = 'discarded'
    db.commit()
    await edit_message_safely(query, "🗑️ انتشار برای این کانال لغو شد.", reply_markup=None)
    logger.info(f"Publication of article {article.id} discarded by {query.from_user.id}.")