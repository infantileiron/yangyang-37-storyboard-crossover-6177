import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ['DATABASE_URL'] = f'sqlite:///{BACKEND}/tests/test.db'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:1/0'
os.environ['SEED_DEMO'] = 'false'

import pytest

from src.models.base import Base, engine


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
