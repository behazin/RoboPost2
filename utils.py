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
    if not isinstance(text, str):
        return ""
    escape_chars = r'\\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

def escape_html(text: str) -> str:
    """کاراکترهای خاص را برای ارسال در مد HTML تلگرام escape می‌کند."""
    if not isinstance(text, str): return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def escape_markdown_url(url: str) -> str:
    """کاراکترهای خاص را در URL برای MarkdownV2 escape می‌کند."""
    if not isinstance(url, str):
        return ""
    return url.replace("(", "\\(").replace(")", "\\)")
    