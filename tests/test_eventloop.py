
import os
import sys
import types
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

dummy = types.ModuleType("dummy")
sys.modules.setdefault("feedparser", dummy)
dummy.RequestException = Exception
sys.modules.setdefault("requests", dummy)

newspaper = types.ModuleType("newspaper")
class DummyArticle: ...
newspaper.Article = DummyArticle
sys.modules.setdefault("newspaper", newspaper)

celery = types.ModuleType("celery")
celery.chord = lambda *a, **k: None
sys.modules.setdefault("celery", celery)

celery_utils = types.ModuleType("celery.utils.log")
celery_utils.get_task_logger = lambda name: None
sys.modules.setdefault("celery.utils.log", celery_utils)

sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")
sqlalchemy_orm.Session = object
sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_orm)


telegram_mod = types.ModuleType("telegram")
class DummyBot:
    def __init__(self, *a, **k):
        pass
    async def send_message(self, *a, **k): pass
    async def send_photo(self, *a, **k): pass
    class session:
        async def close(self): pass
telegram_mod.Bot = DummyBot
telegram_mod.InlineKeyboardButton = object
telegram_mod.InlineKeyboardMarkup = object
sys.modules.setdefault("telegram", telegram_mod)

telegram_constants = types.ModuleType("telegram.constants")
telegram_constants.ParseMode = types.SimpleNamespace(MARKDOWN_V2="MarkdownV2")
sys.modules.setdefault("telegram.constants", telegram_constants)

utils_mod = types.ModuleType("utils")
utils_mod.escape_markdown = lambda x: x
utils_mod.escape_markdown_url = lambda x: x
sys.modules.setdefault("utils", utils_mod)

celery_app_mod = types.ModuleType("celery_app")
class DummyCelery:
    def task(self, *a, **k):
        def wrapper(f):
            return f
        return wrapper
celery_app_mod.celery_app = DummyCelery()
sys.modules.setdefault("celery_app", celery_app_mod)

core_database_mod = types.ModuleType("core.database")
core_database_mod.SessionLocal = lambda: None
sys.modules.setdefault("core.database", core_database_mod)

core_db_models_mod = types.ModuleType("core.db_models")
core_db_models_mod.Source = object
core_db_models_mod.Article = object
core_db_models_mod.Channel = object
sys.modules.setdefault("core.db_models", core_db_models_mod)

core_config_mod = types.ModuleType("core.config")
core_config_mod.settings = types.SimpleNamespace(TELEGRAM_BOT_TOKEN="", admin_ids_list=[])
sys.modules.setdefault("core.config", core_config_mod)

from tasks import _run_in_new_loop, _send_text, _send_photo, _edit_text, _edit_caption

async def dummy():
    return "ok"

def test_run_in_new_loop_multiple_times():
    for _ in range(3):
        assert _run_in_new_loop(dummy()) == "ok"

@patch('tasks.Bot')
def test_send_text_helper_runs(mock_bot_cls):
    mock_context = AsyncMock()
    mock_context.send_message = AsyncMock(return_value='sent')
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = AsyncMock(return_value=mock_context)
    mock_bot.__aexit__ = AsyncMock(return_value=None)
    result = _run_in_new_loop(_send_text('token', 1, 'hi', None))
    assert result == 'sent'
    mock_context.send_message.assert_awaited_once()
    mock_bot.__aenter__.assert_awaited_once()
    mock_bot.__aexit__.assert_awaited_once()

@patch('tasks.Bot')
def test_send_photo_helper_runs(mock_bot_cls):
    mock_context = AsyncMock()
    mock_context.send_photo = AsyncMock(return_value='photo')
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = AsyncMock(return_value=mock_context)
    mock_bot.__aexit__ = AsyncMock(return_value=None)
    result = _run_in_new_loop(_send_photo('token', 2, 'url', 'cap', None))
    assert result == 'photo'
    mock_context.send_photo.assert_awaited_once()
    mock_bot.__aenter__.assert_awaited_once()
    mock_bot.__aexit__.assert_awaited_once()

@patch('tasks.Bot')
def test_edit_text_helper_runs(mock_bot_cls):
    mock_context = AsyncMock()
    mock_context.edit_message_text = AsyncMock(return_value='edited')
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = AsyncMock(return_value=mock_context)
    mock_bot.__aexit__ = AsyncMock(return_value=None)
    result = _run_in_new_loop(_edit_text('t', 1, 10, 'txt', None))
    assert result == 'edited'
    mock_context.edit_message_text.assert_awaited_once()
    mock_bot.__aenter__.assert_awaited_once()
    mock_bot.__aexit__.assert_awaited_once()

@patch('tasks.Bot')
def test_edit_caption_helper_runs(mock_bot_cls):
    mock_context = AsyncMock()
    mock_context.edit_message_caption = AsyncMock(return_value='edited')
    mock_bot = mock_bot_cls.return_value
    mock_bot.__aenter__ = AsyncMock(return_value=mock_context)
    mock_bot.__aexit__ = AsyncMock(return_value=None)
    result = _run_in_new_loop(_edit_caption('t', 1, 10, 'cap', None))
    assert result == 'edited'
    mock_context.edit_message_caption.assert_awaited_once()
    mock_bot.__aenter__.assert_awaited_once()
    mock_bot.__aexit__.assert_awaited_once()
