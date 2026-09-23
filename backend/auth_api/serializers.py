from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

User = get_user_model()

class UserDetailSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = [
            'id', 'slug', 'first_name', 'last_name', 'email', 'username',
            'password', 'image_url', 'is_active', 'is_staff', 'is_superuser'
        ]
        read_only_fields = ['id', 'slug', 'is_superuser']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if self.instance:
            self.fields['password'].required = False
        else:
            self.fields['password'].required = True

        
    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
    
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
            
        if password:
            instance.set_password(password)
            
        instance.save()
        return instance
    
    def validate(self, attrs):
        """Validate all data"""
        password = attrs.get("password")

        if password:
            try:
                validate_password(password, user=self.instance)
            except DjangoValidationError as error:
                raise serializers.ValidationError({"password": list(error)})
            
        username = attrs.get("username")
        if username:
            if len(username) < 3:
                raise serializers.ValidationError(
                    {"username": "Username must be at least 3 characters long."}
                )

        attrs = super().validate(attrs)

        first_name = attrs.get("first_name")  
        last_name = attrs.get("last_name")

        if first_name:
            attrs["first_name"] = attrs["first_name"].title()

        if last_name:
            attrs["last_name"] = attrs["last_name"].title()
        return attrs

    
    
class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 
            'slug', 
            'first_name', 
            'last_name', 
            'username',
            'image_url'
        ]
        read_only_fields = fields


class UserRetrieveSerializer(serializers.ModelSerializer):
    """Get user by id serializer."""

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "slug",
            "first_name",
            "last_name",
            'username',
            "email",
        ]
        read_only_fields = fields

