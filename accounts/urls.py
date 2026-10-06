from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('approval-pending/', views.approval_pending, name='approval_pending'),
    path('password_change/', auth_views.PasswordChangeView.as_view(template_name='password_change.html', success_url=reverse_lazy('profile')), name='password_change'),
]
