# utils.py
import logging
import sys

def setup_logger():
    """یک لاگر مرکزی برای پروژه راه‌اندازی می‌کند."""
    logger = logging.getLogger("NewsBot")
    if logger.hasHandlers():
        logger.handlers.clear()
    
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

logger = setup_logger()

def escape_markdown(text: str) -> str:
    """کاراکترهای خاص را برای ارسال در مد MarkdownV2 تلگرام escape می‌کند."""
    if not isinstance(text, str): return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # خود بک‌اسلش نیز باید escape شود
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def escape_html(text: str) -> str:
    """کاراکترهای خاص را برای ارسال در مد HTML تلگرام escape می‌کند."""
    if not isinstance(text, str): return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")