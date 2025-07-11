# core/db_models.py
from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        ForeignKey, Table, BigInteger, Index)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

# جدول واسط برای رابطه چندبه‌چند بین منابع و کانال‌ها
source_channel_map = Table('source_channel_map', Base.metadata,
    Column('source_id', Integer, ForeignKey('sources.id', ondelete="CASCADE"), primary_key=True),
    Column('channel_id', Integer, ForeignKey('channels.id', ondelete="CASCADE"), primary_key=True)
)

class Source(Base):
    __tablename__ = 'sources'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    rss_url = Column(String(2048), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    channels = relationship("Channel", secondary=source_channel_map, back_populates="sources")

class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    telegram_channel_id = Column(String(255), unique=True, nullable=False)
    target_language_code = Column(String(10), default='fa')
    admin_group_id = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    sources = relationship("Source", secondary=source_channel_map, back_populates="channels")

class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String(255), nullable=False)
    original_url = Column(String(2048), nullable=False)
    original_title = Column(Text, nullable=False)
    original_content = Column(LONGTEXT, nullable=True)
    image_url = Column(String(2048), nullable=True)
    status = Column(String(50), default='new', index=True)
    translated_title = Column(Text, nullable=True)
    translated_content = Column(LONGTEXT, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    admin_chat_id = Column(BigInteger, nullable=True)
    admin_message_id = Column(Integer, nullable=True)
    news_value_score = Column(Integer, index=True, nullable=True, default=None)
    __table_args__ = (
        Index('ix_articles_original_url', 'original_url', unique=True, mysql_length=255),
    )