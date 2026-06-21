from celery import Celery
from app.core.config import settings


celery_app = Celery(
    "docflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_routes={"app.workers.tasks.*": {"queue": "docflow"}},
    worker_prefetch_multiplier=1,
)
