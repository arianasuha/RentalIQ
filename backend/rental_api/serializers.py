from rest_framework import serializers
from core_db.models import Category, Equipment

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']
        read_only_fields = ['id', 'slug']


class EquipmentDetailSerializer(serializers.ModelSerializer):

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'slug','created_at'
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

        return attrs

    

class EquipmentListSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')

    class Meta:
        model = Equipment
        fields = [
            'id', 
            'title', 
            'category_name', 
            'daily_rent', 
            'status', 
            'average_rating', 
            'slug'
        ]
        read_only_fields = fields


class EquipmentRetrieveSerializer(serializers.ModelSerializer):
    """Get Equipment by id serializer."""
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'slug','created_at'
        ]

        read_only_fields = fields


    def to_representation(self, instance):
        """Dynamically strip the slug from the category field on retrieve"""
        representation = super().to_representation(instance)
        
        if representation.get('category'):
            representation['category'].pop('slug', None)
            
        return representation
