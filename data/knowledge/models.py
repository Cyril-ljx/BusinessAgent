import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Integer, Boolean, Date, DateTime, Text, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class Company(Base):
    """Company/tenant boundary for knowledge-base materials."""
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, comment="稳定公司ID")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="公司名称")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否默认公司")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    metadata_info: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Certificate(Base):
    """商务文件 - 细粒度证书及资质表"""
    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 公司/共享库隔离。shared 数据可被所有公司复用，company 数据只服务所属公司。
    company_id: Mapped[Optional[str]] = mapped_column(String(100), comment="所属公司ID；shared 数据可为空")
    scope: Mapped[str] = mapped_column(String(20), default="company", comment="company/shared")

    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="14大类(如营业执照/ISO等)")
    subcategory: Mapped[Optional[str]] = mapped_column(String(200), comment="子分类/细分类")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="证书具体名称")

    # 物理文件信息
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="图片/文件存储路径")
    file_type: Mapped[Optional[str]] = mapped_column(String(20), comment="png/jpg/pdf")
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)

    # 颁发与效期信息
    issue_date: Mapped[Optional[datetime]] = mapped_column(Date)
    expire_date: Mapped[Optional[datetime]] = mapped_column(Date)
    issuer: Mapped[Optional[str]] = mapped_column(String(200))
    cert_number: Mapped[Optional[str]] = mapped_column(String(100))

    # 版本与管理控制
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否当前生效版本")
    version_note: Mapped[Optional[str]] = mapped_column(String(100))

    # 检索与扩展
    keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    metadata_info: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TemplateSection(Base):
    """技术文件 - 粗粒度章节定位表"""
    __tablename__ = "template_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 公司/共享库隔离。技术/商务母版默认归属具体公司，只有显式 shared 才跨公司复用。
    company_id: Mapped[Optional[str]] = mapped_column(String(100), comment="所属公司ID；shared 数据可为空")
    scope: Mapped[str] = mapped_column(String(20), default="company", comment="company/shared")

    # 章节定位
    chapter_id: Mapped[Optional[str]] = mapped_column(String(50), comment="如 1.1, 1.2")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    full_path: Mapped[Optional[str]] = mapped_column(String(500), comment="例如: 项目整体规划/项目保障体系")
    level: Mapped[int] = mapped_column(Integer, nullable=False, comment="标题层级 1/2/3")
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    # 实体统计信息 (供展示用)
    has_text: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_image: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_table: Mapped[Optional[bool]] = mapped_column(Boolean)
    char_count: Mapped[Optional[int]] = mapped_column(Integer)
    image_count: Mapped[Optional[int]] = mapped_column(Integer)
    table_count: Mapped[Optional[int]] = mapped_column(Integer)

    # ★ 关键：在母版 docx 里的块级(Block)位置，用于无损复制
    start_block_idx: Mapped[Optional[int]] = mapped_column(Integer, comment="起始块索引")
    end_block_idx: Mapped[Optional[int]] = mapped_column(Integer, comment="结束块索引")

    # 分类与检索
    category: Mapped[Optional[str]] = mapped_column(String(50))
    keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    display_name: Mapped[Optional[str]] = mapped_column(String(200))

    # 管理控制
    metadata_info: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MasterDocument(Base):
    """母版文件版本管理表"""
    __tablename__ = "master_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 公司/共享库隔离。
    company_id: Mapped[Optional[str]] = mapped_column(String(100), comment="所属公司ID；shared 数据可为空")
    scope: Mapped[str] = mapped_column(String(20), default="company", comment="company/shared")

    doc_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="'business' 或 'technical'")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(50))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
