# bot.py (فایل اصلی و راه‌انداز نهایی)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, filters
from telegram.ext import Defaults
from telegram.constants import ParseMode
from core.config import settings
from utils import logger
from handlers import admin_commands, callback_handlers, jobs

def main():
    """راه‌اندازی و اجرای ربات تلگرام."""
    logger.info("Starting bot application...")
    if not settings.TELEGRAM_BOT_TOKEN or not settings.ADMIN_USER_IDS:
        logger.critical("TELEGRAM_BOT_TOKEN or ADMIN_USER_IDS not found! Exiting.")
        return

    defaults = Defaults(parse_mode=ParseMode.MARKDOWN_V2)
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .defaults(defaults)
        .build()
    )
    admin_filter = filters.User(user_id=settings.admin_ids_list)

    # ثبت دستورات ادمین از ماژول جداگانه
    command_handlers = {
        "start": admin_commands.start, "help": admin_commands.start,
        "add_source": admin_commands.add_source, "remove_source": admin_commands.remove_source, "list_sources": admin_commands.list_sources,
        "add_channel": admin_commands.add_channel, "remove_channel": admin_commands.remove_channel, "list_channels": admin_commands.list_channels,
        "link": admin_commands.link_source_to_channel, "unlink": admin_commands.unlink_source_from_channel,
        "status": admin_commands.status, "force_fetch": admin_commands.force_fetch
    }
    for command, handler_func in command_handlers.items():
        application.add_handler(CommandHandler(command, handler_func, filters=admin_filter))

    # ثبت پاسخ به دکمه‌ها
    application.add_handler(CallbackQueryHandler(callback_handlers.button_callback))
    
    # ثبت کارهای زمان‌بندی شده
    job_queue = application.job_queue
    job_queue.run_repeating(jobs.send_new_articles_to_admin, interval=10, first=10)
    job_queue.run_repeating(jobs.send_final_approval_to_admin, interval=10, first=10)
    job_queue.run_repeating(jobs.cleanup_db_job, interval=3600, first=300)
    
    # ثبت error handler عمومی
    application.add_error_handler(jobs.error_handler)
    
    logger.info(f"Bot service running for admins: {settings.admin_ids_list}")
    application.run_polling()

if __name__ == '__main__':
    main()