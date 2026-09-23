from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import category_views, equipment_views, rental_views

router = DefaultRouter()
router.include_format_suffixes = False
router.register(r'categories', category_views.CategoryViewSet, basename='category')
router.register(r'equipment', equipment_views.EquipmentViewSet, basename='equipment')

router.register(r'rental-requests', rental_views.RentalRequestViewSet, basename='rental-request')
# router.register(r'rentals', rental_views.RentalViewSet, basename='rental')

urlpatterns = [
    path('', include(router.urls)),
]
