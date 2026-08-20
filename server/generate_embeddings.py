from pymongo import MongoClient

from config import MONGO_URL, MONGO_DB_NAME
from services.embeddings import generate_embedding


client = MongoClient(MONGO_URL)
db = client[MONGO_DB_NAME]
projects = db["projects"]


def main():
    documents = projects.find({})

    for doc in documents:
        # Project ke useful text fields ko combine karo
        text_parts = []

        for key, value in doc.items():
            if key not in ["_id", "embedding"] and isinstance(value, str):
                text_parts.append(value)

        text = "\n".join(text_parts).strip()

        if not text:
            print(f"Skipping {doc['_id']} - no text")
            continue

        embedding = generate_embedding(text)

        projects.update_one(
            {"_id": doc["_id"]},
            {"$set": {"embedding": embedding}}
        )

        print(f"Embedded: {doc['_id']} ({len(embedding)} dimensions)")


if __name__ == "__main__":
    main()
