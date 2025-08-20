from celery import Celery
from kombu import Queue, Exchange
from settings import BROKER_URL

# Create Celery app with optimized configuration
celery_app = Celery("core", broker=BROKER_URL, backend=None)

# Optimized Celery configuration for high performance
celery_app.conf.update(
    # Serialization
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],

    # Timezone
    enable_utc=True,
    timezone='UTC',

    # Task routing and execution
    task_routes={
        'core.tasks.process_knowledge': {'queue': 'knowledge_processing'},
    },

    # Worker optimization
    worker_prefetch_multiplier=1,  # One task per worker at a time
    task_acks_late=True,  # Acknowledge task after completion
    worker_disable_rate_limits=True,

    # Performance tuning
    task_compression='gzip',
    result_compression='gzip',

    # Task time limits (in seconds)
    task_time_limit=1800,  # 30 minutes hard limit
    task_soft_time_limit=1500,  # 25 minutes soft limit

    # Connection settings
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,

    # Memory optimization
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
    worker_max_memory_per_child=200000,  # 200MB memory limit per worker

    # Concurrency
    worker_pool='threads',  # Use threads for I/O bound tasks

    # Queue configuration
    task_default_queue='default',
    task_default_exchange='default',
    task_default_exchange_type='direct',
    task_default_routing_key='default',

    # Define queues
    task_queues=(
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('knowledge_processing', Exchange('knowledge'), routing_key='knowledge'),
    ),

    # Error handling
    task_reject_on_worker_lost=True,
    task_ignore_result=True,  # Don't store results to improve performance
)

# Auto-discover tasks
celery_app.autodiscover_tasks(['core'])

# Configure logging
celery_app.conf.worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
celery_app.conf.worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'

# Health check task
@celery_app.task
def health_check():
    """Simple health check task"""
    return "OK"


# Production deployment commands:
# ================================
#
# For Linux (recommended):
# celery -A core worker -l INFO --concurrency=4 -Q knowledge_processing,default
#
# For development:
# celery -A core worker -l INFO --concurrency=2
#
# For monitoring:
# celery -A core flower
#
# For beat scheduler (if needed):
# celery -A core beat -l INFO
#
# Docker deployment:
# docker run -d --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.13-management
# docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest