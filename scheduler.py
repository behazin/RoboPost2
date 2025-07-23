# scheduler.py
import time
from tasks import run_all_fetchers_task
from handlers.jobs import dispatch_preprocess_tasks
from utils import logger
import schedule

FETCH_INTERVAL_MINUTES = 30
PREPROCESS_INTERVAL_MINUTES = 2

def dispatch_fetch_task():
    logger.info("Dispatching run_all_fetchers_task to the queue.")
    run_all_fetchers_task.delay()

def dispatch_preprocess_task():
    logger.info("Dispatching preprocessing tasks to the queue.")
    dispatch_preprocess_tasks()

if __name__ == "__main__":
    logger.info(
        f"Scheduler service started. Will dispatch fetch task every {FETCH_INTERVAL_MINUTES} minutes and preprocessing every {PREPROCESS_INTERVAL_MINUTES} minutes."
    )
    schedule.every(FETCH_INTERVAL_MINUTES).minutes.do(dispatch_fetch_task)
    schedule.every(PREPROCESS_INTERVAL_MINUTES).minutes.do(dispatch_preprocess_task)
    
    # اجرای اولین وظیفه با تاخیر کم برای اطمینان از آمادگی سیستم
    time.sleep(10)
    dispatch_fetch_task()
    dispatch_preprocess_task()
    
    while True:
        schedule.run_pending()
        time.sleep(1)