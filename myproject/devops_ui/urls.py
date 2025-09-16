from django.urls import path
from .views import devops_trigger

urlpatterns = [
    path('', devops_trigger, name='trigger_pipeline'),
]
