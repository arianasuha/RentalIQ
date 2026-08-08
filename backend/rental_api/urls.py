from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import category_views, equipment_views

router = DefaultRouter()
router.include_format_suffixes = False
router.register(r'categories', category_views.CategoryViewSet, basename='category')
router.register(r'equipment', equipment_views.EquipmentViewSet, basename='equipment')

urlpatterns = [
    path('', include(router.urls)),
]
