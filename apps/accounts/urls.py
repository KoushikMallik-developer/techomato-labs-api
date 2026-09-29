from django.urls import path

from . import views

urlpatterns = [
    path('auth/csrf/', views.CsrfView.as_view(), name='auth-csrf'),
    path('auth/signup/', views.SignupView.as_view(), name='auth-signup'),
    path('auth/login/', views.LoginView.as_view(), name='auth-login'),
    path('auth/logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', views.MeView.as_view(), name='auth-me'),
    path('auth/password/change/', views.ChangePasswordView.as_view(), name='auth-password-change'),
    path('auth/password/forgot/', views.ForgotPasswordView.as_view(), name='auth-password-forgot'),
    path('auth/password/reset/', views.ResetPasswordView.as_view(), name='auth-password-reset'),
    path('auth/verify-email/', views.VerifyEmailView.as_view(), name='auth-verify-email'),
    path('auth/verify-email/resend/', views.ResendVerificationView.as_view(), name='auth-verify-email-resend'),
    path('auth/oauth/providers/', views.OAuthProvidersView.as_view(), name='auth-oauth-providers'),
    path('auth/oauth/<str:provider>/', views.OAuthLoginView.as_view(), name='auth-oauth'),
]
