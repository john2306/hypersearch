from celery import Celery
from settings import BROKER_URL

celery_app = Celery("core", broker=BROKER_URL, backend=None)

celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    enable_utc=True
)

celery_app.autodiscover_tasks(['core'])

# latest RabbitMQ 3.13
# docker run -d --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.12-management
# docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest

# Ejecución de Celery
# pip install gevent # For Windowns 10
# celery -A core worker -l INFO -P gevent  # For Windowns 10
# celery -A core worker -l INFO -P gevent --concurrency=8 # For Windowns 10, concurrency = 2*number of cores (núcleos)
# celery -A core worker -l INFO # For Linux
# celery -A core worker -l INFO --concurrency=8 # For Linux 
# celery -A core beat -l INFO # For Linux when you want to run the beat