# handlers/callback_handlers.py
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from sqlalchemy.orm import Session
from utils import escape_markdown, logger
from core.database import get_db
from core.db_models import Article, Channel
from tasks import process_article_task, publish_article_task

async def edit_message_safely(query, new_text: str, **kwargs):
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=new_text, **kwargs)
        else:
            await query.edit_message_text(text=new_text, **kwargs)
    except TelegramError as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Could not edit message: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data_parts = query.data.split('_'); action = data_parts[0]; article_id = int(data_parts[1])
    db: Session = next(get_db())
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            await query.edit_message_text(
                "این مقاله دیگر وجود ندارد.",
                parse_mode=None,
            )
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
        logger.error(f"Error in button_callback for article {article.id}: {e}", exc_info=True)
    finally:
        db.close()

async def handle_approve(query, article, db):
    if article.status != 'pending_initial_approval':
        await edit_message_safely(
            query,
            "این مورد قبلا پردازش شده است.",
            reply_markup=None,
            parse_mode=None,
        );
        return
    
    # ذخیره اطلاعات پیام برای ویرایش در مرحله بعد
    article.admin_chat_id = query.message.chat_id
    article.admin_message_id = query.message.message_id
    article.status = 'approved'; db.commit()
    
    process_article_task.delay(article.id)
    
    await edit_message_safely(
        query,
        "⏳ تایید اولیه شد. در حال پردازش مقاله...",
        reply_markup=None,
        parse_mode=None,
    )
    logger.info(f"Article {article.id} approved by {query.from_user.id}, processing task sent to queue.")

async def handle_reject(query, article, db):
    """مقاله را رد کرده و پیام آن را از چت مدیر حذف می‌کند."""
    if article.status != 'pending_initial_approval':
        await edit_message_safely(
            query,
            "این مورد قبلا پردازش شده است.",
            reply_markup=None,
            parse_mode=None,
        )
        return

    # ۱. وضعیت مقاله در دیتابیس به 'rejected' تغییر می‌کند
    article.status = 'rejected'
    db.commit()

    # ۲. پیام مربوط به مقاله از چت حذف می‌شود
    try:
        await query.message.delete()
        logger.info(f"Article {article.id} rejected and message deleted by {query.from_user.id}.")
    except TelegramError as e:
        # در صورتی که به هر دلیلی (مثلا پیام خیلی قدیمی باشد) حذف ممکن نباشد، خطا را لاگ می‌کنیم
        logger.warning(f"Could not delete message for rejected article {article.id}: {e}")

async def handle_publish(query, article, channel_id, context, db):
    if article.status != 'sent_for_publication':
        await edit_message_safely(
            query,
            "این مورد قبلا منتشر یا لغو شده است.",
            reply_markup=None,
            parse_mode=None,
        );
        return

    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        await edit_message_safely(
            query,
            "خطا: کانال مقصد یافت نشد.",
            parse_mode=None,
        )
        return
    
    try:
        publish_article_task.delay(article.id, channel.id)
        await edit_message_safely(
            query,
            "⏳ خبر برای انتشار در صف قرار گرفت.",
            reply_markup=None,
            parse_mode=None,
        )
        logger.info(
            f"Article {article.id} queued for publication to {channel.name} by {query.from_user.id}"
        )
    except TelegramError as e:
        await edit_message_safely(
            query,
            escape_markdown(f"⚠️ خطا در انتشار به کانال {channel.name}: {e}"),
        )
        logger.error(f"Failed to queue article {article.id} for channel {channel.name}: {e}")

async def handle_discard(query, article, db):
    if article.status != 'sent_for_publication':
        await edit_message_safely(
            query,
            "این مورد قبلا پردازش شده است.",
            reply_markup=None,
            parse_mode=None,
        );
        return
    
    article.status = 'discarded'; db.commit()
    await edit_message_safely(
        query,
        "🗑️ انتشار برای این کانال لغو شد.",
        reply_markup=None,
        parse_mode=None,
    )
    logger.info(f"Publication of article {article.id} discarded by {query.from_user.id}.")
    