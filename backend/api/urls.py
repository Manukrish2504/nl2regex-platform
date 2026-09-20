from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("connection/", views.ConnectionView.as_view()),
    path("connection/files/", views.FileListView.as_view()),
    path("connection/files/preview/", views.FilePreviewView.as_view()),
    path("jobs/", views.JobListView.as_view()),
    path("jobs/<uuid:job_id>/", views.JobDetailView.as_view()),
    path("jobs/<uuid:job_id>/cancel/", views.JobCancelView.as_view()),
    path("jobs/<uuid:job_id>/rows/", views.JobRowsView.as_view()),
]
