import redis

try:
    # Connect to Redis running on localhost via Docker port mapping
    client = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,  # Automatically decodes byte responses to strings
    )

    # Test the connection
    if client.ping():
        print("Successfully connected to Redis!")

    # Set a key-value pair
    client.set("greeting", "Hello from Python & Docker!")

    # Retrieve the value
    value = client.get("greeting")
    print(f"Retrieved Value: {value}")

except redis.ConnectionError as e:
    print(f"Could not connect to Redis: {e}")
