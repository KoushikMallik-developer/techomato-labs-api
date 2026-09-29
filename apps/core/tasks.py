import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def enqueue_on_commit(task, *args, **kwargs):
    """
    Queue a Celery task once the surrounding transaction commits. A broker
    outage must never fail the request that triggered the task, so enqueue
    errors are logged and swallowed.
    """

    def _enqueue():
        try:
            task.delay(*args, **kwargs)
        except Exception:  # noqa: BLE001 - broker errors are wide-ranging
            logger.exception('Could not enqueue task %s', getattr(task, 'name', task))

    transaction.on_commit(_enqueue)
