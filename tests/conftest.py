from unittest.mock import MagicMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture(scope="function")
async def db_engine(tmp_path):
    """Отдельная база данных SQLite для каждого теста - позволяет избежать ошибки index-already-exists при выполнении create_all."""
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def mock_celery_task():
    """
    Применяет глобальное исправление к механизму распределения задач Celery, чтобы тесты никогда не обращались к Redis.
    Тесты, которым требуется проанализировать вызовы, могут напрямую использовать возвращаемый мок.
    """
    mock = MagicMock()
    mock.apply_async = MagicMock()

    with patch("app.workers.tasks.process_file", mock):
        yield mock


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()