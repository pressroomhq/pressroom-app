from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session


async def get_data_layer_for_org(org_id: int):
    """Non-dependency version — returns a DataLayer for a specific org. For internal use."""
    from services.data_layer import DataLayer
    session = async_session()
    return DataLayer(session, org_id=org_id)


async def get_data_layer(x_org_id: int | None = Header(default=None)):
    """FastAPI dependency — yields a DataLayer scoped to an org.

    Org comes from the X-Org-Id header. If missing, org_id=None (global/legacy).
    For authenticated access, use get_authenticated_data_layer from api.auth instead.
    """
    from services.data_layer import DataLayer
    async with async_session() as session:
        dl = DataLayer(session, org_id=x_org_id)
        yield dl
