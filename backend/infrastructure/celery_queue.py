from celery import current_app


class CeleryTaskQueue:
    """Enqueues tasks by name, so this adapter never imports the tasks package.

    Task arguments are IDs only. Flower and the result backend display arguments, so credentials
    must never travel this way; workers look them up in the vault themselves.
    """

    def enqueue_job(self, job_id: str) -> None:
        current_app.send_task("tasks.jobs.run_job", args=[job_id])

    def enqueue_preview(self, connection_id: str, file_key: str) -> None:
        current_app.send_task("tasks.files.build_preview", args=[connection_id, file_key])
