from django.db import transaction
from django.core.files.images import get_image_dimensions
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.images import get_image_dimensions
from rest_framework import serializers
from core_db.models import Category, Equipment, EquipmentImage
from .utils import (
    validate_image_dimensions_and_size
)

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']
        read_only_fields = ['id', 'slug']


class EquipmentImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentImage
        fields = ['id', 'image', 'uploaded_at']


class EquipmentDetailSerializer(serializers.ModelSerializer):
    images = EquipmentImageSerializer(many=True, read_only=True)

    additional_images = serializers.ListField(
        child=serializers.ImageField(max_length=100000, allow_empty_file=False, use_url=False),
        write_only=True, 
        allow_empty=True,
        allow_null=True,
        required=False, 
        help_text="Upload up to 2 images for this equipment."
    )
    delete_image_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True, required=False, help_text="IDs of EquipmentImage instances to delete."
    )
    thumbnail_image = serializers.ImageField(
        required=True, 
        use_url=True,
        error_messages={
            'required': "This field is required and must be a valid image file.",
            'invalid': "The submitted data was not a valid image file."
        }
    )

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 'description', 'purchase_price', 
            'daily_rent', 'rent_advance', 'status', 'average_rating', 'total_rentals', 
            'slug', 'created_at', 'images', 'additional_images', 'thumbnail_image', 'delete_image_ids'
        ]
        read_only_fields = ['owner', 'average_rating', 'total_rentals', 'slug']

    def to_internal_value(self, data):
        """
        Intercepts raw data before field-level validation to clean up empty 
        strings/null values sent by Swagger or FormData for additional_images.
        """
       
        if hasattr(data, '_mutable'):
            data = data.copy()

        if 'additional_images' in data:
            if hasattr(data, 'getlist'):
                raw_list = data.getlist('additional_images')
            else:
                raw_list = data.get('additional_images', [])
                if not isinstance(raw_list, list):
                    raw_list = [raw_list]

            
            cleaned_files = [
                f for f in raw_list 
                if f not in [None, '', 'null', 'undefined', b''] and not isinstance(f, str)
            ]

            if hasattr(data, '_mutable'):
                data.setlist('additional_images', cleaned_files)
            else:
                data['additional_images'] = cleaned_files

        return super().to_internal_value(data)

    def validate_thumbnail_image(self, value):
        if value:
            return validate_image_dimensions_and_size(value)
        return value   # what are we returning
        
    def validate_additional_images(self, value):
        if not value:
            return []
        
        return validate_image_dimensions_and_size(value)

    def validate(self, attrs):    # which validation method will work first
        purchase_price = attrs.get('purchase_price', getattr(self.instance, 'purchase_price', None))
        daily_rent = attrs.get('daily_rent', getattr(self.instance, 'daily_rent', None))
        rent_advance = attrs.get('rent_advance', getattr(self.instance, 'rent_advance', None))

        errors = {}
        if purchase_price is not None and purchase_price < 0:
            errors['purchase_price'] = "Purchase price cannot be negative."
        if daily_rent is not None and daily_rent < 0:
            errors['daily_rent'] = "Daily rent cannot be negative."
        if rent_advance is not None and rent_advance < 0:
            errors['rent_advance'] = "Rent advance cannot be negative."

        if not errors:
            if rent_advance is not None and purchase_price is not None and rent_advance > purchase_price:
                errors['rent_advance'] = "Rent advance cannot be greater than the purchase price."
            if daily_rent == 0 and rent_advance and rent_advance > 0:
                errors['rent_advance'] = "You cannot charge a rent advance if the daily rent is free (0)."

        if errors:
            raise serializers.ValidationError(errors)
        
        additional_images = attrs.get('additional_images', [])
        thumbnail_image = attrs.get('thumbnail_image', None)
        delete_image_ids = attrs.get('delete_image_ids', [])
        
        if not self.instance:
            if not thumbnail_image:
                raise serializers.ValidationError({'thumbnail_image': "You must upload a main thumbnail image."})
            
            if len(additional_images) > 2:
                raise serializers.ValidationError({
                    'additional_images': f"You can only upload a maximum of 2 additional gallery images. Attempted: {len(additional_images)}."
                })
                
            return attrs

        existing_images = self.instance.images.filter(id__in=delete_image_ids)
        if len(existing_images) != len(delete_image_ids):
            raise serializers.ValidationError({'delete_image_ids': "One or more image IDs are invalid or do not belong to this equipment."})

        current_count = self.instance.images.count()
        remaining_count = current_count - len(delete_image_ids)
        new_count = remaining_count + len(additional_images)

        if new_count > 2:
            raise serializers.ValidationError({
                'additional_images': f"Total additional images cannot exceed 2. (Current: {current_count}, Deleting: {len(delete_image_ids)}, Adding: {len(additional_images)})"
            })

        return attrs


    def create(self, validated_data):
        """
        Handles db execution and thumbnail mapping logic for creating equipment.
        """
        images_data = validated_data.pop('additional_images', [])

        with transaction.atomic():
            equipment =  Equipment.objects.create(**validated_data)

            if images_data:
                image_objects = [
                    EquipmentImage(equipment=equipment, image=image_data) 
                    for image_data in images_data
                ]
                EquipmentImage.objects.bulk_create(image_objects)
            
        return equipment
            


    def update(self, instance, validated_data):
        additional_images = validated_data.pop('additional_images', [])
        delete_image_ids = validated_data.pop('delete_image_ids', [])
        new_thumbnail = validated_data.get('thumbnail_image', None)

        with transaction.atomic():
            if new_thumbnail and instance.thumbnail_image:
                instance.thumbnail_image.delete(save=False) # Delete old file from storage

            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if delete_image_ids:
                images_to_delete = instance.images.filter(id__in=delete_image_ids)
                for img_obj in images_to_delete:
                    img_obj.image.delete(save=False)
                images_to_delete.delete()

            if additional_images:
                image_objects = [
                    EquipmentImage(equipment=instance, image=image_data)
                    for image_data in additional_images
                ]
                EquipmentImage.objects.bulk_create(image_objects)

        return instance

class EquipmentListSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')
    thumbnail_image = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            'id', 
            'title', 
            'category_name', 
            'daily_rent', 
            'status', 
            'average_rating', 
            'thumbnail_image',
            'slug'
        ]
        read_only_fields = fields

    def get_thumbnail_image(self, obj):
        latest_image = obj.images.order_by('-uploaded_at').first()
        
        if latest_image:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(latest_image.image.url)
            return latest_image.image.url
        return None

class OwnerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='username') 

    class Meta:
        model = User 
        fields = ['id', 'name']

class EquipmentRetrieveSerializer(serializers.ModelSerializer):
    """Get Equipment by id serializer."""
    category = CategorySerializer(read_only=True)
    images = EquipmentImageSerializer(many=True, read_only=True)

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'slug','created_at',
            'images'
        ]

        read_only_fields = fields


    def to_representation(self, instance):
        """Dynamically strip the slug from the category field on retrieve"""
        representation = super().to_representation(instance)
        
        if representation.get('category'):
            representation['category'].pop('slug', None)
            
        return representation
