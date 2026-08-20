from pymongo import MongoClient
from bson import ObjectId

from config import MONGO_URL, MONGO_DB_NAME
from services.embeddings import generate_embedding


if not MONGO_URL:
    raise RuntimeError("MONGO_URL is not configured")

client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]
projects_collection = db["projects"]


def _project_filter(project_id):
    if isinstance(project_id, ObjectId):
        return {"_id": project_id}
    try:
        return {"_id": ObjectId(str(project_id))}
    except Exception:
        return {"_id": project_id}


def add_embedding_to_project(project_id, text: str):
    embedding = generate_embedding(text)

    result = projects_collection.update_one(
        _project_filter(project_id),
        {
            "$set": {
                "embedding": embedding
            }
        }
    )
    if result.matched_count == 0:
        raise ValueError(f"Project not found: {project_id}")

    return embedding
