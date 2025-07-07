# handlers/admin_commands.py
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from core.database import get_db
from core.db_models import Source, Channel, Article
from utils import logger, escape_markdown
from tasks import run_all_fetchers_task

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستورات راهنما را برای ادمین ارسال می‌کند."""
    help_text_raw = (
        "سلام ادمین! به ربات مدیریت محتوا خوش آمدید.\n\n"
        "*مدیریت منابع:*\n"
        "/add_source <name> <rss_url>\n"
        "/remove_source <source_id>\n"
        "/list_sources\n\n"
        "*مدیریت کانال‌ها:*\n"
        "/add_channel <name> <@id> <lang> <admin_id>\n"
        "/remove_channel <channel_id>\n"
        "/list_channels\n\n"
        "*اتصال منابع به کانال‌ها:*\n"
        "/link <source_id> <channel_id>\n"
        "/unlink <source_id> <channel_id>\n\n"
        "*عملیاتی:*\n"
        "/status | /force_fetch"
    )
    await update.message.reply_text(escape_markdown(help_text_raw), parse_mode=ParseMode.MARKDOWN_V2)

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if len(context.args) < 2:
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/add_source <name> <rss_url>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return
        
        name = ' '.join(context.args[:-1])
        rss_url = context.args[-1]
        
        if not rss_url.startswith(('http://', 'https://')):
            await update.message.reply_text("آدرس RSS نامعتبر است. باید با http:// یا https:// شروع شود."); return

        new_source = Source(name=name, rss_url=rss_url)
        db.add(new_source); db.commit(); db.refresh(new_source)
        reply_text = f"✅ منبع خبری '{name}' با شناسه `{new_source.id}` اضافه شد."
        await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
    except IntegrityError:
        db.rollback(); await update.message.reply_text("⚠️ خطا: منبعی با این نام قبلاً ثبت شده است.")
    except Exception as e:
        db.rollback(); logger.error(f"Failed to add source: {e}"); await update.message.reply_text("خطایی در افزودن منبع رخ داد.")
    finally:
        db.close()

async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if not context.args or not context.args[0].isdigit():
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/remove_source <source_id>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return
        
        source_id = int(context.args[0])
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            await update.message.reply_text("منبعی با این شناسه یافت نشد."); return
        
        source_name = source.name
        db.delete(source); db.commit()
        reply_text = f"🗑️ منبع خبری '{source_name}' با موفقیت حذف شد."
        await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        db.rollback(); logger.error(f"Failed to remove source: {e}"); await update.message.reply_text("خطایی در حذف منبع رخ داد.")
    finally:
        db.close()

async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        sources = db.query(Source).order_by(Source.id).all()
        if not sources:
            await update.message.reply_text("هیچ منبع خبری تعریف نشده است."); return
        message = "📚 *لیست منابع خبری:*\n\n"
        for s in sources:
            status = "✅" if s.is_active else "❌"
            message += f"ID: `{s.id}` | {escape_markdown(s.name)} - *{status}*\n"
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        db.close()

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if len(context.args) != 4:
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/add_channel <name> <@channel_id> <lang> <admin_group_id>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return
        
        name, channel_id_str, lang, admin_id_str = context.args
        new_channel = Channel(name=name, telegram_channel_id=channel_id_str, target_language_code=lang, admin_group_id=int(admin_id_str))
        db.add(new_channel); db.commit(); db.refresh(new_channel)
        reply_text = f"✅ کانال '{name}' با شناسه `{new_channel.id}` پیکربندی شد."
        await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت اشتباه یا شناسه ادمین نامعتبر است.")
    except Exception as e:
        db.rollback(); await update.message.reply_text(f"خطا در افزودن کانال: {e}")
    finally:
        db.close()

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if not context.args or not context.args[0].isdigit():
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/remove_channel <channel_id>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return
        
        channel_id = int(context.args[0])
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            await update.message.reply_text("کانالی با این شناسه یافت نشد."); return
        
        channel_name = channel.name
        db.delete(channel); db.commit()
        reply_text = f"🗑️ کانال '{channel_name}' با موفقیت حذف شد."
        await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        db.rollback(); await update.message.reply_text("خطایی در حذف کانال رخ داد.")
    finally:
        db.close()

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        channels = db.query(Channel).order_by(Channel.id).all()
        if not channels:
            await update.message.reply_text("هیچ کانالی تعریف نشده است."); return
        message = "📺 *لیست کانال‌های مقصد:*\n\n"
        for ch in channels:
            status = "✅" if ch.is_active else "❌"
            message += f"ID: `{ch.id}` | {escape_markdown(ch.name)} ({escape_markdown(ch.telegram_channel_id)}) - زبان: `{ch.target_language_code}` - *{status}*\n"
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        db.close()

async def link_source_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/link <source_id> <channel_id>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return
        
        source_id, channel_id = map(int, context.args)
        source = db.query(Source).filter(Source.id == source_id).first()
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not source or not channel:
            await update.message.reply_text("شناسه منبع یا کانال نامعتبر است."); return
        
        if source not in channel.sources:
            channel.sources.append(source); db.commit()
            reply_text = f"✅ منبع '{source.name}' با موفقیت به کانال '{channel.name}' متصل شد."
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text("⚠️ این اتصال از قبل وجود دارد.")
    except Exception as e:
        db.rollback(); await update.message.reply_text(f"خطا در اتصال: {e}")
    finally:
        db.close()

async def unlink_source_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
            reply_text = "فرمت اشتباه. استفاده صحیح:\n`/unlink <source_id> <channel_id>`"
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2); return

        source_id, channel_id = map(int, context.args)
        source = db.query(Source).filter(Source.id == source_id).first()
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not source or not channel:
            await update.message.reply_text("شناسه منبع یا کانال نامعتبر است."); return
        
        if source in channel.sources:
            channel.sources.remove(source); db.commit()
            reply_text = f"✅ اتصال منبع '{source.name}' از کانال '{channel.name}' حذف شد."
            await update.message.reply_text(escape_markdown(reply_text), parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text("این اتصال وجود ندارد.")
    except Exception as e:
        db.rollback(); logger.error(f"Failed to unlink source: {e}"); await update.message.reply_text(f"خطا در حذف اتصال: {e}")
    finally:
        db.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db: Session = next(get_db())
    try:
        statuses = ['new', 'pending_initial_approval', 'approved', 'pending_publication', 'published', 'failed', 'rejected', 'discarded']
        status_counts = {s: db.query(Article).filter(Article.status == s).count() for s in statuses}
        message = "📊 *وضعیت فعلی سیستم:*\n\n"
        message += f"🔹 جدید: *{status_counts['new']}*\n"
        message += f"🔹 در انتظار تایید اولیه: *{status_counts['pending_initial_approval']}*\n"
        message += f"🔹 در صف پردازش: *{status_counts['approved']}*\n"
        message += f"🔹 آماده انتشار: *{status_counts['pending_publication']}*\n"
        message += f"🔹 منتشر شده: *{status_counts['published']}*\n"
        message += f"🔹 رد شده: *{status_counts['rejected'] + status_counts['discarded']}*\n"
        message += f"🔹 پردازش ناموفق: *{status_counts['failed']}*\n"
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        db.close()

async def force_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Manual fetch triggered by admin {update.effective_user.id}")
    run_all_fetchers_task.delay()
    await update.message.reply_text("✅ دستور جمع‌آوری فوری اخبار به صف اضافه شد.")