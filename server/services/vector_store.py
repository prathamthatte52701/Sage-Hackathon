from pymongo import MongoClient

from config import MONGO_URL, MONGO_DB_NAME
from services.embeddings import generate_embedding


client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]
projects_collection = db["projects"]


def add_embedding_to_project(project_id, text: str):
    embedding = generate_embedding(text)

    projects_collection.update_one(
        {"_id": project_id},
        {
            "$set": {
                "embedding": embedding
            }
        }
    )

    return embedding
