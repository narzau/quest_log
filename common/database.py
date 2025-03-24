import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, Optional, Type, TypeVar, Dict, Any, List, Generic

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, update, delete, insert
from sqlalchemy.sql import Select
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# Create base class for SQLAlchemy models
Base = declarative_base()

# Type variable for models
ModelType = TypeVar("ModelType", bound=Base)  # type: ignore

class AsyncDatabase:
    """Async SQLAlchemy database connection manager"""
    
    def __init__(self, db_url: str, echo: bool = False):
        self.engine = create_async_engine(db_url, echo=echo)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a session for database operations"""
        session = self.session_factory()
        try:
            yield session
        except Exception as e:
            logger.error(f"Database error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def create_tables(self):
        """Create all tables in the database"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
    async def drop_tables(self):
        """Drop all tables in the database (use with caution!)"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


# Database dependency for FastAPI
async def get_db_session(db: AsyncDatabase) -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get a database session"""
    async with db.session() as session:
        yield session


class BaseRepository(Generic[ModelType]):
    """Generic repository for database operations"""
    
    def __init__(self, model: Type[ModelType], db: AsyncDatabase):
        self.model = model
        self.db = db
    
    async def get_by_id(self, id: Any) -> Optional[ModelType]:
        """Get a model by ID"""
        async with self.db.session() as session:
            result = await session.execute(
                select(self.model).where(self.model.id == id)
            )
            return result.scalars().first()
    
    async def get_by_field(self, field: str, value: Any) -> Optional[ModelType]:
        """Get a model by a field value"""
        async with self.db.session() as session:
            result = await session.execute(
                select(self.model).where(getattr(self.model, field) == value)
            )
            return result.scalars().first()
    
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Get all models with pagination"""
        async with self.db.session() as session:
            result = await session.execute(
                select(self.model).offset(skip).limit(limit)
            )
            return list(result.scalars().all())
    
    async def create(self, data: Dict[str, Any]) -> ModelType:
        """Create a new model"""
        async with self.db.session() as session:
            model = self.model(**data)
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model
    
    async def update(self, id: Any, data: Dict[str, Any]) -> Optional[ModelType]:
        """Update a model"""
        async with self.db.session() as session:
            # First update the model
            result = await session.execute(
                update(self.model)
                .where(self.model.id == id)
                .values(**data)
                .returning(self.model)
            )
            await session.commit()
            
            # Then fetch the updated model
            updated_model = result.scalars().first()
            return updated_model
    
    async def delete(self, id: Any) -> bool:
        """Delete a model"""
        async with self.db.session() as session:
            result = await session.execute(
                delete(self.model).where(self.model.id == id)
            )
            await session.commit()
            return result.rowcount > 0
    
    async def execute_query(self, query: Select) -> List[ModelType]:
        """Execute a custom query"""
        async with self.db.session() as session:
            result = await session.execute(query)
            return list(result.scalars().all())


def get_postgres_url(
    user: str,
    password: str,
    host: str,
    db_name: str,
    port: int = 5432,
) -> str:
    """Get PostgreSQL connection URL"""
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"