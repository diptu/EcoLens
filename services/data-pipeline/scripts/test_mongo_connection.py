import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from ecolens.config import get_settings

# Configure logging for professional observability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mongo_test")


def test_mongodb_connection():
    # Load configuration
    config = get_settings()

    # Initialize client with recommended server selection timeout
    # This prevents the script from hanging indefinitely if the DB is unreachable
    client = MongoClient(config.mongo_uri, serverSelectionTimeoutMS=5000)

    try:
        # 1. Verify Connectivity
        client.admin.command("ping")
        logger.info("Successfully connected to MongoDB server.")

        # 2. Verify Database and Collection Access
        db = client["my_database_name"]
        collection = db["my_collection_name"]

        # 3. Perform a lightweight write-then-read operation
        # This confirms write permissions and collection availability
        test_doc = {"test_key": "connection_test", "timestamp": "2026-07-20"}
        result = collection.insert_one(test_doc)

        # Retrieve the document to confirm read integrity
        retrieved_doc = collection.find_one({"_id": result.inserted_id})

        if retrieved_doc:
            logger.info("Successfully performed CRUD operation (Write & Read).")
            # Cleanup
            collection.delete_one({"_id": result.inserted_id})
            logger.info("Test record cleaned up.")

    except ConnectionFailure:
        logger.error(
            "Could not connect to MongoDB. Check your connection string or network."
        )
    except OperationFailure as e:
        logger.error(f"Authentication or permission error: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    test_mongodb_connection()
