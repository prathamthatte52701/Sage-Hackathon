import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_DB_NAME, MONGO_URL

_client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where()) if MONGO_URL else None
db = _client[MONGO_DB_NAME] if _client else None
