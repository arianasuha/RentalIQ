from django.db import transaction
from django.core.files.images import get_image_dimensions
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.images import get_image_dimensions
from rest_framework import serializers
from core_db.models import Category, Equipment, EquipmentImage
from .utils import (
    validate_image_dimensions_and_size, 
    purge_physical_files, 
    handle_equipment_update, 
    handle_equipment_creation
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
        write_only=True, required=False, help_text="Upload up to 2 images for this equipment."
    )
    images_to_delete = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    thumbnail_image = serializers.ImageField(
        required=True, 
        use_url=True,
        error_messages={
            'required': "This field is required and must be a valid image file.",
            'invalid': "The submitted data was not a valid image file."
        }
    )
    thumbnail_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 'description', 'purchase_price', 
            'daily_rent', 'rent_advance', 'status', 'average_rating', 'total_rentals', 
            'slug', 'created_at', 'images', 'additional_images', 'images_to_delete', 
            'thumbnail_image', 'thumbnail_id'
        ]
        read_only_fields = ['owner', 'average_rating', 'total_rentals', 'slug']
    
    def validate_additional_images(self, value):
        if not value:
            return value
        print("-----------")
        print(value)
        return validate_image_dimensions_and_size(value)

    def validate(self, attrs):
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
        
        # Pull arrays safely for boundary checks
        additional_images = attrs.get('additional_images', [])
        thumbnail_image = attrs.get('thumbnail_image', None)
        
        # -------------------------------------------------------------
        # CREATION MATH RULES
        # -------------------------------------------------------------
        if not self.instance:
            if not thumbnail_image:
                raise serializers.ValidationError({'thumbnail_image': "You must upload a main thumbnail image."})
            
            # 2. Check maximum limits for additional uploads (Max 2 extra allowed)
            if len(additional_images) > 2:
                raise serializers.ValidationError({
                    'additional_images': f"You can only upload a maximum of 2 additional gallery images. Attempted: {len(additional_images)}."
                })
                
            return attrs
        
        return attrs
        
        # # Update Math Rules
        # existing_images = self.instance.images.all()
        # existing_ids = set(existing_images.values_list('id', flat=True))
        
        # invalid_ids = [img_id for img_id in images_to_delete if img_id not in existing_ids]
        # if invalid_ids:
        #     raise serializers.ValidationError({'images_to_delete': f"Image IDs {invalid_ids} do not belong to this equipment."})

        # final_count = existing_images.count() - len(set(images_to_delete)) + len(additional_images) + (1 if thumbnail_image else 0)
        # if final_count < 1:
        #     raise serializers.ValidationError({'additional_images': "At least one image must remain attached."})
        # if final_count > 3:
        #     raise serializers.ValidationError({'additional_images': f"Limit exceeded. Results in {final_count} images (Max: 3)."})

        # # Target ID & Index Checks
        # t_id, t_idx = attrs.get('thumbnail_id'), attrs.get('thumbnail_index')
        # if t_id is not None and (t_id in images_to_delete or t_id not in existing_ids):
        #     raise serializers.ValidationError({'thumbnail_id': "Invalid or deleted thumbnail selection."})
        # if t_idx is not None and (t_idx < 0 or t_idx >= len(additional_images)):
        #     raise serializers.ValidationError({'thumbnail_index': "Index out of range for newly uploaded images."})

        # return attrs

    def create(self, validated_data):
        return handle_equipment_creation(validated_data, Equipment, EquipmentImage)

    def update(self, instance, validated_data):
        with transaction.atomic():
            # Update root fields
            instance = super().update(instance, validated_data)
            # Run calculations inside the transaction
            instance, files_to_wipe = handle_equipment_update(instance, validated_data, EquipmentImage)
            
        # Run storage cleaning strictly outside the database lock context
        purge_physical_files(files_to_wipe)
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
