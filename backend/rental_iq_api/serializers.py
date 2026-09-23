from django.db import transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from core_db.models import Category, Equipment, EquipmentImage, RentalRequest, Rental
from .utils import (
    validate_image_dimensions_and_size,
    get_coordinates_from_address
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

    city = serializers.CharField(write_only=True, required=False, allow_blank=True)
    area = serializers.CharField(write_only=True, required=False, allow_blank=True)
    block_sector = serializers.CharField(write_only=True, required=False, allow_blank=True)
    road_street = serializers.CharField(write_only=True, required=False, allow_blank=True)

    delete_image_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True, required=False, help_text="IDs of EquipmentImage instances to delete."
    )
    thumbnail_image = serializers.ImageField(
        required=False, 
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
            'slug', 'created_at', 'images', 'additional_images', 'thumbnail_image', 'delete_image_ids',
            'city', 'area', 'block_sector', 'road_street', 'address_name'
        ]
        read_only_fields = ['id', 'owner', 'average_rating', 'total_rentals', 'slug', 'created_at']

    def get_location(self, obj) -> dict | None:
        # Here, 'obj.location' reads the actual database field from PostGIS!
        if obj.location:
            return {
                "lat": round(obj.location.y, 6), # Reads .y from DB point
                "lng": round(obj.location.x, 6)  # Reads .x from DB point
            }
        return None


    def to_internal_value(self, data):
        """
        Intercepts raw data before field-level validation to clean up empty 
        strings/null values sent by Swagger or FormData for additional_images.
        """
       
        if hasattr(data, '_mutable'):
            data = data.copy()

        fields_to_clean = [
            'title', 'description', 
            'purchase_price', 'daily_rent', 'rent_advance', 
            'status', 'thumbnail_image', 'city_area', 'block_sector', 'road_street', 'address_name'
        ]

        for field in fields_to_clean:
            if field in data and data.get(field) in ['', 'null', 'undefined', 'string', None]:
                if hasattr(data, '_mutable'):
                    data.pop(field, None)
                else:
                    data.pop(field, None)

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
        return value   
        
    def validate_additional_images(self, value):
        if not value:
            return []
        
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

        city = attrs.get('city', getattr(self.instance, 'city', None))
        area = attrs.get('area', getattr(self.instance, 'area', None))
        block_sector = attrs.get('block_sector', getattr(self.instance, 'block_sector', None))
        road_street = attrs.get('road_street', getattr(self.instance, 'road_street', None))

        if any([city, area, block_sector, road_street]):
            if not city:
                errors['city'] = "City is required when specifying detailed location."
            if not area:
                errors['area'] = "Area is required when specifying detailed location."
            if not block_sector:
                errors['block_sector'] = "Block/Sector is required when specifying detailed location."
            if not road_street:
                errors['road_street'] = "Road/Street number is required when specifying detailed location."

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

        city = validated_data.pop('city', None)
        area = validated_data.pop('area', None)
        block = validated_data.pop('block_sector', None)
        road = validated_data.pop('road_street', None)

        if city and area and block and road:
            full_address = f"{road}, {block}, {area}, {city}, Bangladesh"
            validated_data['address_name'] = full_address
            validated_data['location'] = get_coordinates_from_address(full_address)

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

        city = validated_data.pop('city', None)
        area = validated_data.pop('area', None)
        block = validated_data.pop('block_sector', None)
        road = validated_data.pop('road_street', None)

        if city and area and block and road:
            full_address = f"{road}, {block}, {area}, {city}, Bangladesh"
            validated_data['address_name'] = full_address
            validated_data['location'] = get_coordinates_from_address(full_address)

        with transaction.atomic():
            if new_thumbnail and instance.thumbnail_image:
                instance.thumbnail_image.delete(save=False)

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
    thumbnail_image = serializers.ImageField(read_only=True)

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
            'address_name',
            'slug'
        ]
        read_only_fields = fields


    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if rep.get('address_name') is None:
            rep.pop('address_name', None)
        return rep

class OwnerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='username') 

    class Meta:
        model = User 
        fields = ['id', 'name']

class EquipmentRetrieveSerializer(serializers.ModelSerializer):
    """Get Equipment by id serializer."""
    category = CategorySerializer(read_only=True)
    images = EquipmentImageSerializer(many=True, read_only=True)
    thumbnail_image = serializers.ImageField(read_only=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'slug','created_at',
            'images', 'thumbnail_image', 'address_name', 'location'
        ]

        read_only_fields = fields


    def get_location(self, obj) -> dict | None:
        """Convert PostGIS Point to standard lat/lng dictionary for the frontend."""
        if obj.location:
            return {
                "lat": round(obj.location.y, 6),
                "lng": round(obj.location.x, 6)
            }
        return None

    def to_representation(self, instance):
        """Dynamically strip the None values on retrieve"""
        representation = super().to_representation(instance)
        
        if representation.get('category'):
            representation['category'].pop('slug', None)

        if representation.get('address_name') is None:
            representation.pop('address_name', None)
            
        return representation


class EquipmentNearbySerializer(serializers.ModelSerializer):
    distance_km = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()

    class Meta:
        model = Equipment
        fields = [
            'id',
            'title',
            'slug',
            'daily_rent',
            'status',
            'address_name',
            'location',
            'distance_km',
        ]

    def get_location(self, obj) -> dict | None:
        if obj.location:
            return {
                "lat": round(obj.location.y, 6),
                "lng": round(obj.location.x, 6)
            }
        return None

    def get_distance_km(self, obj) -> float | None:
        if hasattr(obj, 'distance_km') and obj.distance_km is not None:
            return round(obj.distance_km.km, 2)
        return None


class RentalRequestCreateSerializer(serializers.ModelSerializer):
    """
    Used when a user submits a new rental request.
    Validates equipment availability, dates, and self-rental checks.
    """
    class Meta:
        model = RentalRequest
        fields = [
            'id', 
            'renter',
            'equipment', 
            'start_date', 
            'end_date', 
            'daily_rent_snapshot', 
            'deposit_amount_snapshot', 
            'total_rent_amount', 
            'status', 
            'created_at',
            'fulfillment_type',          
            'delivery_address',          
            'delivery_contact_phone',    
            'notes',                     
        ]
        read_only_fields = [
            'id', 
            'renter',
            'daily_rent_snapshot', 
            'deposit_amount_snapshot', 
            'total_rent_amount', 
            'status', 
            'created_at'
        ]

    def validate_equipment(self, value):
        """Ensure the equipment is available for rental."""
        if value.status != 'available':
            raise serializers.ValidationError("This equipment is not currently available for rental.")
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        renter = request.user if request else None
        equipment = attrs.get('equipment')
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if equipment and renter and equipment.owner == renter:
            raise serializers.ValidationError({"equipment": "You cannot request to rent your own equipment."})

        today = timezone.now().date()
        if start_date and start_date < today:
            raise serializers.ValidationError({"start_date": "Start date cannot be in the past."})

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "End date cannot be earlier than start date."})

        instance = RentalRequest(
            equipment=equipment,
            renter=renter,
            start_date=start_date,
            end_date=end_date,
            status=RentalRequest.RequestStatus.PENDING
        )
        try:
            instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else e.messages)

        return attrs

    def create(self, validated_data):
        validated_data['renter'] = self.context['request'].user
        return super().create(validated_data)


class RentalRequestListSerializer(serializers.ModelSerializer):
    """
    Lightweight summary serializer for listing rental requests in tables/feeds.
    """
    equipment_title = serializers.ReadOnlyField(source='equipment.title')
    equipment_thumbnail = serializers.ImageField(source='equipment.thumbnail_image', read_only=True)
    renter_email = serializers.ReadOnlyField(source='renter.email')

    class Meta:
        model = RentalRequest
        fields = [
            'id',
            'equipment_title',
            'equipment_thumbnail',
            'renter_email',
            'start_date',
            'end_date',
            'total_rent_amount',
            'status',
            'created_at',
        ]
        read_only_fields = fields


class RentalRequestRetrieveSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for viewing single RentalRequest instances, 
    nested with Equipment summary info.
    """
    equipment = EquipmentListSerializer(read_only=True)
    renter_email = serializers.ReadOnlyField(source='renter.email')
    renter_id = serializers.ReadOnlyField(source='renter.id')

    class Meta:
        model = RentalRequest
        fields = [
            'id',
            'equipment',
            'renter_id',
            'renter_email',
            'start_date',
            'end_date',
            'daily_rent_snapshot',
            'deposit_amount_snapshot',
            'total_rent_amount',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class RentalRequestStatusUpdateSerializer(serializers.ModelSerializer):
    """
    Used by Equipment Owners to Approve or Reject a request.
    """
    class Meta:
        model = RentalRequest
        fields = ['status']

    def validate_status(self, value):
        allowed_choices = [
            RentalRequest.RequestStatus.APPROVED,
            RentalRequest.RequestStatus.REJECTED,
            RentalRequest.RequestStatus.CANCELLED
        ]
        if value not in allowed_choices:
            raise serializers.ValidationError("Invalid status transition.")
        return value


class RentalDetailSerializer(serializers.ModelSerializer):
    """
    Detailed View of an Active/Completed Rental agreement.
    """
    rental_request = RentalRequestRetrieveSerializer(read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Rental
        fields = [
            'id',
            'rental_request',
            'status',
            'payment_status',
            'transaction_id',
            'actual_return_date',
            'deposit_returned',
            'is_overdue',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_is_overdue(self, obj) -> bool:
        if obj.status == Rental.RentalStatus.ACTIVE and timezone.now().date() > obj.rental_request.end_date:
            return True
        return False


class RentalUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer used by staff/owners to manage return date, deposit returns, and rental status.
    """
    class Meta:
        model = Rental
        fields = [
            'status',
            'payment_status',
            'transaction_id',
            'actual_return_date',
            'deposit_returned'
        ]