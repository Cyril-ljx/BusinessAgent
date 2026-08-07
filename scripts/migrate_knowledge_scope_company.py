"""Add company/scope isolation columns to knowledge-base tables.

Run with:
    set PYTHONPATH=src
    python scripts/migrate_knowledge_scope_company.py
"""

from __future__ import annotations

from sqlalchemy import text

from tender_agent.core.db import engine


TABLES = ("certificates", "template_sections", "master_documents")
DEFAULT_COMPANY_ID = "demo-company"
DEFAULT_COMPANY_NAME = "\u5e7f\u4e1c\u9510\u535a\u4eba\u529b\u8d44\u6e90\u670d\u52a1\u6709\u9650\u516c\u53f8"


def migrate() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id VARCHAR(100) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    is_default BOOLEAN NOT NULL DEFAULT false,
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO companies (id, name, is_default, is_active)
                VALUES (:id, :name, true, true)
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    is_default = true,
                    is_active = true,
                    updated_at = now()
                """
            ),
            {"id": DEFAULT_COMPANY_ID, "name": DEFAULT_COMPANY_NAME},
        )
        for table in TABLES:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS company_id VARCHAR(100)
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET company_id = :company_id
                    WHERE scope = 'company'
                      AND (company_id IS NULL OR company_id = '')
                    """
                ),
                {"company_id": DEFAULT_COMPANY_ID},
            )
            conn.execute(
                text(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'company'
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET scope = 'company'
                    WHERE scope IS NULL OR scope = ''
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    COMMENT ON COLUMN {table}.company_id IS '所属公司ID；shared 数据可为空'
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    COMMENT ON COLUMN {table}.scope IS 'company/shared'
                    """
                )
            )


if __name__ == "__main__":
    migrate()
    print("knowledge scope/company columns migrated")
