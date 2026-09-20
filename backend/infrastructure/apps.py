from django.apps import AppConfig


class InfrastructureConfig(AppConfig):
    """Installed only so Django manages the tables in models.py. The domain never sees the ORM."""

    name = "infrastructure"
