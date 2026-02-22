"""Standalone scheduler runner for cleanup job.
Run this with a process manager so cleanup runs once daily outside the web workers.
"""
import time
from datetime import datetime
import logging
from main import init_db, cleanup_job


def main():
    init_db()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Scheduler runner started')
    # simple loop: run cleanup immediately, then every 24h
    while True:
        try:
            logging.info('Running cleanup_job')
            cleanup_job()
        except Exception as e:
            logging.exception('cleanup_job failed: %s', e)
        # sleep 24 hours
        time.sleep(24 * 3600)


if __name__ == '__main__':
    main()
