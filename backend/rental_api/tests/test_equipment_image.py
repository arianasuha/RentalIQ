import io
from PIL import Image
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status
from core_db.models import Equipment, EquipmentImage, Category

User = get_user_model()


class EquipmentImageCreateTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(email='testuser@example.com', password='Django@123')
        self.client.force_authenticate(user=self.user)
        
        self.category = Category.objects.create(name="Tools")
        self.url = reverse('equipment-list') 

    def _generate_image(self, width=800, height=800, format='JPEG', name='test_image.jpg'):
        file = io.BytesIO()
        image = Image.new('RGB', (width, height), color='red')
        image.save(file, format=format)
        file.seek(0)
        return SimpleUploadedFile(name, file.read(), content_type=f'image/{format.lower()}')

    def _generate_oversized_image(self, size_mb=2.5, name='large.jpg'):
        file = io.BytesIO()
        image = Image.new('RGB', (2500, 2500), color='blue')
        image.save(file, format='PNG')
        file.seek(0)
        
        raw_data = file.read()
        target_bytes = int(size_mb * 1024 * 1024)
        if len(raw_data) < target_bytes:
            raw_data += b'0' * (target_bytes - len(raw_data))
            
        return SimpleUploadedFile(name, raw_data, content_type='image/png')

    def _get_base_payload(self):
        """Returns standard required non-file fields."""
        return {
            'category': self.category.id,
            'title': 'Heavy Duty Drill',
            'description': 'A high power drill for construction work.',
            'daily_rent': '25.00',
            'purchase_price': '200.00',
            'rent_advance': '50.00',
            'status': 'available'
        }

    
    def test_generate_image(self, width=800, height=800, format='JPEG', name='test_image.jpg'):
        """Creates a valid image in memory with specified dimensions."""
        file = io.BytesIO()
        image = Image.new('RGB', (width, height), color='red')
        image.save(file, format=format)
        file.seek(0)
        return SimpleUploadedFile(name, file.read(), content_type=f'image/{format.lower()}')


    def test_create_equipment_thumbnail_exceeds_max_file_size_fails(self):
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_oversized_image(size_mb=2.5)

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('thumbnail_image', response.data)

    
    def test_create_equipment_with_only_thumbnail_success(self):
        """Should successfully create equipment with only a valid thumbnail image."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_image(500, 500, name='thumb.jpg')

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Equipment.objects.count(), 1)
        self.assertEqual(EquipmentImage.objects.count(), 0)  # No additional images
        
        equipment = Equipment.objects.first()
        self.assertTrue(equipment.thumbnail_image.name.startswith('equipment_thumbnails/'))

    def test_create_equipment_with_thumbnail_and_max_additional_images_success(self):
        """Should successfully create equipment with thumbnail and 2 additional gallery images."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_image(600, 600, name='thumb.jpg')
        payload['additional_images'] = [
            self._generate_image(800, 800, name='gallery1.jpg'),
            self._generate_image(1000, 1000, name='gallery2.jpg')
        ]

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Equipment.objects.count(), 1)
        self.assertEqual(EquipmentImage.objects.count(), 2)  # 2 extra gallery images

        equipment = Equipment.objects.first()
        gallery_images = equipment.images.all()
        for img in gallery_images:
            self.assertTrue(img.image.name.startswith('equipment_images/'))


    def test_create_equipment_missing_thumbnail_fails(self):
        """Should return 400 if thumbnail_image is completely missing from payload."""
        payload = self._get_base_payload()

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('thumbnail_image', response.data)

    def test_create_equipment_exceeds_max_additional_images_limit_fails(self):
        """Should return 400 when attempting to upload more than 2 additional images."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_image(500, 500)
        payload['additional_images'] = [
            self._generate_image(500, 500, name='img1.jpg'),
            self._generate_image(500, 500, name='img2.jpg'),
            self._generate_image(500, 500, name='img3.jpg')  # 3rd extra image (Limit is 2)
        ]

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('additional_images', response.data)

    def test_create_equipment_thumbnail_below_minimum_dimensions_fails(self):
        """Should return 400 if thumbnail width/height is below 400x400px."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_image(300, 300, name='small_thumb.jpg')

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('thumbnail_image', response.data)

    def test_create_equipment_additional_image_exceeds_max_dimensions_fails(self):
        """Should return 400 if an additional image exceeds 4000x4000px."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_image(500, 500)
        payload['additional_images'] = [
            self._generate_image(4500, 4500, name='huge_gallery.jpg')
        ]

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('additional_images', response.data)

    def test_create_equipment_thumbnail_exceeds_max_file_size_fails(self):
        """Should return 400 if thumbnail size is greater than 2MB."""
        payload = self._get_base_payload()
        payload['thumbnail_image'] = self._generate_oversized_image(size_mb=2.5, name='heavy_thumb.png')

        response = self.client.post(self.url, data=payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('thumbnail_image', response.data)

    # def test_create_equipment_upload_non_image_file_fails(self):
    #     """Should return 400 when submitting non-image files (e.g. TXT or PDF)."""
    #     payload = self._get_base_payload()
    #     fake_text_file = SimpleUploadedFile(
    #         name='script.txt', 
    #         content=b'This is a text file, not an image.', 
    #         content_type='text/plain'
    #     )
    #     payload['thumbnail_image'] = fake_text_file

    #     response = self.client.post(self.url, data=payload, format='multipart')

    #     self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    #     self.assertIn('thumbnail_image', response.data)