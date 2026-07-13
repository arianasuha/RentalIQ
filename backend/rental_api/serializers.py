from rest_framework import serializers
from core_db.models import Category, Equipment, EquipmentImage
from django.contrib.auth.models import User

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
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(max_length=100000, allow_empty_file=False, use_url=False),
        write_only=True,
        required=False,
        help_text="Upload up to 3 images for this equipment."
    )

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'slug','created_at', 'images',
            'uploaded_images'
        ]
        read_only_fields = ['owner', 'average_rating', 'total_rentals', 'slug']


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
            if rent_advance is not None and purchase_price is not None:
                if rent_advance > purchase_price:
                    errors['rent_advance'] = "Rent advance cannot be greater than the purchase price."
            
            if daily_rent == 0 and rent_advance and rent_advance > 0:
                errors['rent_advance'] = "You cannot charge a rent advance if the daily rent is free (0)."

        if errors:
            raise serializers.ValidationError(errors)
        

        uploaded_images = attrs.get('uploaded_images', [])
        new_images_count = len(uploaded_images)
        
        # Scenario A: Creation (self.instance is None)
        if not self.instance:
            if new_images_count == 0:
                raise serializers.ValidationError({
                    'uploaded_images': "You must upload at least one image when creating equipment."
                })
        
        # Scenario B: Updating (self.instance exists)
        existing_images_count = 0
        if self.instance:
            existing_images_count = self.instance.images.count()
        
        total_expected_images = existing_images_count + new_images_count
        if total_expected_images > 3:
            raise serializers.ValidationError({
                'uploaded_images': f"You can upload a maximum of 3 images. Current: {existing_images_count}, Added: {new_images_count}."
            })

        return attrs
    

    def create(self, validated_data):
        images_data = validated_data.pop('uploaded_images', [])
        
        equipment = Equipment.objects.create(**validated_data)
        for image_data in images_data:
            EquipmentImage.objects.create(equipment=equipment, image=image_data)
        return equipment

    def update(self, instance, validated_data):
        images_data = validated_data.pop('uploaded_images', [])
        instance = super().update(instance, validated_data)
        
        for image_data in images_data:
            EquipmentImage.objects.create(equipment=instance, image=image_data)
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
