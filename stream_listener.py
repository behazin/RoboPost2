import os
import redis
from tasks import run_all_fetchers_task
from handlers.jobs import dispatch_preprocess_tasks
from utils import logger
from core.config import settings

STREAMS = ["fetch_requests", "preprocess_requests"]
GROUP_NAME = "listener_group"
CONSUMER_NAME = os.getenv("HOSTNAME", "listener")


def create_groups(r: redis.Redis):
    for stream in STREAMS:
        try:
            r.xgroup_create(stream, GROUP_NAME, id="0", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                continue
            raise


def main():
    logger.info("Starting Redis Stream listener...")
    r = redis.Redis.from_url(settings.REDIS_URL)
    create_groups(r)

    while True:
        try:
            msgs = r.xreadgroup(
                GROUP_NAME,
                CONSUMER_NAME,
                streams={stream: ">" for stream in STREAMS},
                count=1,
                block=5000,
            )
            for stream, entries in msgs:
                stream_name = stream.decode() if isinstance(stream, bytes) else stream
                for msg_id, data in entries:
                    try:
                        if stream_name == "fetch_requests":
                            run_all_fetchers_task.delay()
                        elif stream_name == "preprocess_requests":
                            dispatch_preprocess_tasks()
                        r.xack(stream_name, GROUP_NAME, msg_id)
                        logger.info(f"Processed {stream_name} message {msg_id}")
                    except Exception as exc:
                        logger.error(f"Failed processing {msg_id} from {stream_name}: {exc}", exc_info=True)
        except Exception as exc:
            logger.error(f"Stream listener error: {exc}", exc_info=True)


if __name__ == "__main__":
    main()