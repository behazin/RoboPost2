import redis
from tasks import run_all_fetchers_task
from handlers.jobs import dispatch_preprocess_tasks
from utils import logger
from core.config import settings

CHANNELS = ["fetch_requests", "preprocess_requests"]

def main():
    logger.info("Starting Redis Pub/Sub listener...")
    r = redis.Redis.from_url(settings.REDIS_URL)
    pubsub = r.pubsub()
    pubsub.subscribe(*CHANNELS)
    for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()
        logger.info(f"Received message on {channel}")
        if channel == "fetch_requests":
            run_all_fetchers_task.delay()
        elif channel == "preprocess_requests":
            dispatch_preprocess_tasks()

if __name__ == "__main__":
    main()