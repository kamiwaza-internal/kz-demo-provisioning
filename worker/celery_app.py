import os
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

# Load .env file before importing settings
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

from app.config import settings

celery_app = Celery(
    'provisioning_worker',
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=['worker.tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3300,  # 55 minutes soft limit
)
