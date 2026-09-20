from celery import shared_task

from config.container import preview_service


@shared_task(name="tasks.files.build_preview")
def build_preview(connection_id: str, file_key: str) -> None:
    preview_service().build(connection_id, file_key)
