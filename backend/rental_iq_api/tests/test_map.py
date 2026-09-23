from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from core_db.models import Equipment, Category, CustomUser

class GeospatialEquipmentAPITestCase(APITestCase):

    def setUp(self):
        # Create test owner & category
        self.user = CustomUser.objects.create_user(
            email="testuser@example.com", 
            password="Password123!", 
            full_name="Tester"
        )
        self.category = Category.objects.create(name="Electronics", slug="electronics")

        # 1. Equipment in Mohakhali (Lat: 23.7771, Lng: 90.4030)
        self.equipment_near = Equipment.objects.create(
            owner=self.user,
            category=self.category,
            title="Mohakhali Camera",
            daily_rent=100.0,
            status="available",
            location=Point(90.4030, 23.7771, srid=4326), # Note: Point(longitude, latitude)
            address_name="Mohakhali, Dhaka"
        )

        # 2. Equipment in Chittagong (~200 km away)
        self.equipment_far = Equipment.objects.create(
            owner=self.user,
            category=self.category,
            title="Chittagong Drone",
            daily_rent=200.0,
            status="available",
            location=Point(91.8318, 22.3569, srid=4326),
            address_name="Chittagong, Bangladesh"
        )

    def test_nearby_equipment_returns_only_in_radius(self):
        """Test search within 10 km returns Mohakhali item, excluding Chittagong item."""
        url = reverse('equipment-nearby')  # Adjust based on your router basename
        params = {
            'address': 'Mohakhali, Dhaka',
            'radius_km': 10
        }
        response = self.client.get(url, params)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', [])
        
        # Verify filtering
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], "Mohakhali Camera")

    def test_annotated_distance_ordering(self):
        """Test results are ordered by distance (closest first)."""
        url = reverse('equipment-nearby')
        params = {'address': 'Mohakhali, Dhaka', 'radius_km': 300}  # Large radius
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', [])

        self.assertGreaterEqual(len(results), 2)
        # Ensure first item distance is smaller than second item distance
        self.assertLess(results[0]['distance_km'], results[1]['distance_km'])