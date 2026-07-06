from rest_framework import serializers
from core_db.models import Category, Equipment

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']
        read_only_fields = ['id', 'slug']


class EquipmentSerializer(serializers.ModelSerializer):
    category_detail = CategorySerializer(source='category', read_only=True)

    class Meta:
        model = Equipment
        fields = [
            'id', 'owner', 'category', 'category_detail', 'title', 
            'description', 'purchase_price', 'daily_rent', 
            'rent_advance', 'status', 'average_rating', 'total_rentals', 'created_at'
        ]
        read_only_fields = ['owner', 'average_rating', 'total_rentals']