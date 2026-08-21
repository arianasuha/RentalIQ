from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from django.views.generic import TemplateView


urlpatterns = [
    path('admin/', admin.site.urls),
    path("auth-api/", include("auth_api.urls")),
    path("rental-iq-api/", include("rental_iq_api.urls")),
    path('map/', TemplateView.as_view(template_name='map_demo.html'), name='map-demo'),
    
    path('swagger-api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger-api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
