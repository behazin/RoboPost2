# scheduler.py
import time
from tasks import run_all_fetchers_task
from utils import logger
import schedule

FETCH_INTERVAL_MINUTES = 30

def dispatch_fetch_task():
    logger.info("Dispatching run_all_fetchers_task to the queue.")
    run_all_fetchers_task.delay()

if __name__ == "__main__":
    logger.info(f"Scheduler service started. Will dispatch fetch task every {FETCH_INTERVAL_MINUTES} minutes.")
    schedule.every(FETCH_INTERVAL_MINUTES).minutes.do(dispatch_fetch_task)
    
    # اجرای اولین وظیفه با تاخیر کم برای اطمینان از آمادگی سیستم
    time.sleep(10) 
    dispatch_fetch_task()
    
    while True:
        schedule.run_pending()
        time.sleep(1)