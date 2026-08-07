import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

from data.knowledge.models import Base


def main() -> None:
    load_dotenv(encoding="utf-8-sig")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required; copy .env.example to .env and configure PostgreSQL first")

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    print("Database tables created successfully.")


if __name__ == "__main__":
    main()
