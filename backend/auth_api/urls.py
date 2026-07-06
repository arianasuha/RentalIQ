from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views 

router = DefaultRouter()
router.include_format_suffixes = False
router.register(r'users', views.UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh-token/", views.RefreshTokenView.as_view(), name="refresh-token"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
]

