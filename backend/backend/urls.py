from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


urlpatterns = [
    path('admin/', admin.site.urls),
    path("auth-api/", include("auth_api.urls")),
    path("rental-api/", include("rental_api.urls")),
    
    path('swagger-api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger-api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
