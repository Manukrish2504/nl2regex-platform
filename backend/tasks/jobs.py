"""The worker's entry point for jobs. Like an API view: it translates, and the service decides."""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from config.container import job_service
from domain.jobs import RetryLater

logger = logging.getLogger(__name__)


# The service decides whether a failure is worth retrying and gives up after its own attempt cap,
# so max_retries here is only a backstop and must stay above that cap.
@shared_task(
    bind=True,
    name="tasks.jobs.run_job",
    autoretry_for=(RetryLater,),
    # Start at 15 seconds, not Celery's 1: what these retries wait for is an outage — S3, the
    # Spark cluster, the model's API — and none of those ends inside a second. Jitter spreads
    # retries by picking a wait *below* the backoff, so with it on, all three attempts could still
    # land within a few seconds; the point here is to wait, so it is off.
    retry_backoff=15,
    retry_backoff_max=300,
    retry_jitter=False,
    max_retries=6,
)
def run_job(self, job_id: str) -> None:
    # True when the broker hands the message out again because its last delivery was never
    # acknowledged: that worker died mid-job.
    redelivered = bool((self.request.delivery_info or {}).get("redelivered"))
    service = job_service()
    try:
        service.run(job_id, redelivered=redelivered)
    except RetryLater:
        raise
    except SoftTimeLimitExceeded:
        service.fail_unexpected(
            job_id, "timed_out", "The job ran past its time limit and was stopped."
        )
    except Exception:
        logger.exception("Job %s failed unexpectedly", job_id)
        service.fail_unexpected(
            job_id, "internal_error", "Something went wrong on our side while processing the file."
        )
