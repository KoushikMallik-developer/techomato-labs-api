from django.urls import path

from . import views

urlpatterns = [
    path('admin/login/', views.AdminLoginView.as_view(), name='admin-login'),
    path('admin/logout/', views.AdminLogoutView.as_view(), name='admin-logout'),
    path('admin/session/', views.AdminSessionView.as_view(), name='admin-session'),
    path('admin/circuits/pending/', views.PendingCircuitsView.as_view(), name='admin-pending'),
    path('admin/circuits/<uuid:pk>/approve/', views.ApproveCircuitView.as_view(), name='admin-approve'),
    path('admin/circuits/<uuid:pk>/reject/', views.RejectCircuitView.as_view(), name='admin-reject'),
]
