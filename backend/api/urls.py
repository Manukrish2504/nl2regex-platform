from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("connection/", views.ConnectionView.as_view()),
    path("connection/files/", views.FileListView.as_view()),
]
