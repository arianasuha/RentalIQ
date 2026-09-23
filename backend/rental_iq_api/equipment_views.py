from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.decorators import action
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.postgres.search import TrigramSimilarity
from django.contrib.gis.measure import D
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse, OpenApiParameter
from core_db.models import Equipment, Category
from backend.schema_serializers import ErrorResponseSerializer
from backend.utils import block_put_method
from .serializers import (
    EquipmentDetailSerializer, 
    EquipmentListSerializer, 
    EquipmentRetrieveSerializer,
    EquipmentDetailSerializer,
    EquipmentNearbySerializer
)
from .utils import get_coordinates_from_address
from .paginations import EquipmentPagination


class EquipmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and managing equipment inventory records.
    """
    queryset = Equipment.objects.all()
    serializer_class = EquipmentDetailSerializer
    pagination_class = EquipmentPagination
    http_method_names = ['get', 'post', 'patch', 'delete']


    def get_permissions(self):
        """
        Dynamically applies permissions based on the incoming action.
        """

        if self.action in ['list', 'retrieve', 'nearby', 'suggest_locations']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    

    def get_queryset(self):
        if self.action == "retrieve":
            return Equipment.objects.select_related('owner', 'category').all().prefetch_related('images').all()
        if self.action == "list":
            return Equipment.objects.prefetch_related('images').all()
        return Equipment.objects.all()
    

    def get_serializer_class(self):
        """Assign serializer based on action."""
        if self.action == "list":
            return EquipmentListSerializer
        if self.action == "retrieve":
            return EquipmentRetrieveSerializer
        return EquipmentDetailSerializer


    def _check_weekly_creation_limit(self, user):
        """
        Ensures a user hasn't exceeded the weekly threshold for creating equipment.
        """
        MAX_CREATIONS_PER_WEEK = 4
        one_week_ago = timezone.now() - timedelta(days=7)
        
        user_creation_count = Equipment.objects.filter(
            owner=user, 
            created_at__gte=one_week_ago
        ).count()
        
        if user_creation_count >= MAX_CREATIONS_PER_WEEK:
            raise PermissionDenied(
                f"You have reached your limit of {MAX_CREATIONS_PER_WEEK} equipment creations per week."
            )

    def _validate_uniqueness(self, user, validated_data):
        """
        Prevents the same owner from creating duplicate items with the same title.
        """
        equipment_title = validated_data.get('title')
        
        if Equipment.objects.filter(owner=user, title__iexact=equipment_title).exists():
            raise ValidationError(
                {"title": ["You have already listed an item with this title."]}
            )

        
    @extend_schema(
        summary="List All Equipment",
        description="Retrieves a list of all existing equipment items. Accessible by anyone.",
        tags=["Equipment Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=EquipmentListSerializer(many=True),
                description="Successfully fetched equipment inventory list.",
            )
        }
    )
    def list(self, request, *args, **kwargs):
        """
        Fetches all equipment entries at once.
        """
        return super().list(request, *args, **kwargs)


    @extend_schema(
        summary="Retrieve Equipment Details",
        description="Fetches a single equipment record safely by its ID. Accessible by anyone.",
        tags=["Equipment Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=EquipmentRetrieveSerializer,
                description="Equipment details retrieved successfully.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment record not found.",
            )
        },
        examples=[
            OpenApiExample(
                name="Equipment Not Found",
                response_only=True,
                status_codes=["404"],
                value={"detail": "Not found."}
            )
        ]
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Fetches a single equipment record safely using get_object_or_404.
        """
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Create New Equipment",
        description="Allows authenticated users to register a new equipment item with optional address parameters.",
        tags=["Equipment Management"],
        request={
            "application/json": EquipmentDetailSerializer,
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "integer",
                        "description": "Select a valid Category"
                    },
                    "title": {"type": "string", "maxLength": 255},
                    "description": {"type": "string"},
                    "purchase_price": {"type": "number", "format": "double"},
                    "daily_rent": {"type": "number", "format": "double"},
                    "rent_advance": {"type": "number", "format": "double"},
                    "status": {
                        "type": "string", 
                        "enum": ["available", "rented", "maintenance"],
                        "default": "available"
                    },
                    "city": {
                        "type": "string",
                        "description": "Optional: City (e.g., Dhaka). Required if area or block or road is provided."
                    },
                    "area": {
                        "type": "string",
                        "description": "Optional: Area (e.g., Banani). Required if city or block or road is provided."
                    },
                    "block_sector": {
                        "type": "string",
                        "description": "Optional: Block or Sector (e.g., Block C). Required if area or city or road is provided."
                    },
                    "road_street": {
                        "type": "string",
                        "description": "Optional: Road or Street (e.g., Road 11). Required if area or city or block is provided."
                    },
                    "thumbnail_image": {
                        "type": "string",
                        "format": "binary",
                        "description": "Explicit file upload to use directly as the thumbnail image."
                    },
                    "additional_images": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "format": "binary"
                        },
                        "description": "Upload up to 2 gallery images for this equipment."
                    },
                },
            },
        },
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=EquipmentDetailSerializer,
                description="Equipment registered successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. User unauthenticated or hit weekly creation thresholds.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Creation Response",
                response_only=True,
                status_codes=["201"],
                value={
                    "detail": "Equipment successfully created.", 
                    "data": {"id": 1, "title": "Heavy Duty Drill", "images": []}
                }
            ),
            OpenApiExample(
                name="Incomplete Location Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "area": ["Area is required when specifying detailed location."],
                    "block_sector": ["Block/Sector is required when specifying detailed location."],
                    "road_street": ["Road/Street number is required when specifying detailed location."]
                }
            ),
            OpenApiExample(
                name="Weekly Limit Reached Cap",
                response_only=True,
                status_codes=["403"],
                value={"detail": "You have reached your limit of 4 equipment creations per week."}
            )
        ]
    )
    def create(self, request, *args, **kwargs):
        """
        Creates a new equipment.
        """
        self._check_weekly_creation_limit(request.user)

        serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        
        self._validate_uniqueness(request.user, serializer.validated_data)
            
        serializer.save(owner=request.user)
        
        return Response(
            {"detail": "Equipment successfully created.", "data": serializer.data}, 
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Update Equipment (Full)",
        description="Replaces an entire equipment tracking entry. Admin exclusive.",
        tags=["Equipment Management"],
        request=EquipmentDetailSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment updated successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Bad Request. Provided values are invalid.",
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. Non-admin operations blocked.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment target missing.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Update Response",
                response_only=True,
                status_codes=["200"],
                value={"detail": "Equipment successfully updated."}
            )
        ]
    )
    def update(self, request, *args, **kwargs):
        """
        Allow authenticated owners to update their equipment.
        PATCH method allowed, PUT method not allowed.
        """
        not_allowed_method = block_put_method(request, *args, **kwargs)
        if not_allowed_method:
            return not_allowed_method
        
        instance = self.get_object()

        if instance.owner != request.user:
            raise PermissionDenied("You do not have permission to update this equipment.")

        response = super().update(request, *args, **kwargs)

        response.data = {
            "detail": "Equipment successfully updated.",
            "data": response.data
        }
        return response

    @extend_schema(
        summary="Update Equipment (Partial)",
        description="Updates field subsets, location specifics, or attached gallery images for an equipment item.",
        tags=["Equipment Management"],
        request={
            "application/json": EquipmentDetailSerializer,
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "category": {"type": "integer", "description": "ID of the category"},
                    "title": {"type": "string", "maxLength": 255},
                    "description": {"type": "string"},
                    "purchase_price": {"type": "number", "format": "double"},
                    "daily_rent": {"type": "number", "format": "double"},
                    "rent_advance": {"type": "number", "format": "double"},
                    "status": {
                        "type": "string", 
                        "enum": ["available", "rented", "maintenance"],
                        "default": "available"
                    },
                    "city": {
                        "type": "string",
                        "description": "Optional: City. Must be accompanied by area and block and road."
                    },
                    "area": {
                        "type": "string",
                        "description": "Optional: Area. Must be accompanied by city and block and road."
                    },
                    "block_sector": {
                        "type": "string",
                        "description": "Optional: Block or Sector. Must be accompanied by area and city and road."
                    },
                    "road_street": {
                        "type": "string",
                        "description": "Optional: Road or Street. Must be accompanied by area and city and block."
                    },
                    "thumbnail_image": {
                        "type": "string",
                        "format": "binary",
                        "description": "Explicit file upload to replace current thumbnail image."
                    },
                    "delete_image_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "IDs of EquipmentImage instances to delete."
                    },
                    "additional_images": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "format": "binary"
                        },
                        "description": "Upload up to 2 additional gallery images."
                    },
                },
            },
        },
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                description="Equipment patched successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Bad Request. Invalid data modifications, location combinations, or image issues.",
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. Action blocked if user is not the recorded owner.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment target missing.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Partial Update Response",
                response_only=True,
                status_codes=["200"],
                value={
                    "detail": "Equipment successfully updated.",
                    "data": {
                        "id": 1, 
                        "title": "Modified Title Name",
                        "address_name": "Road 11, Block C, Banani, Dhaka, Bangladesh",
                        "images": [
                            {"id": 15, "image": "/media/equipment/clean_pic.jpg"}
                        ]
                    }
                }
            )
        ]
    )
    def partial_update(self, request, *args, **kwargs):
        """Partial update equipment (PATCH method).
        """
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


    @extend_schema(
        summary="Delete Equipment",
        description="Deletes target equipment record from the inventory backend layer. Admin exclusive.",
        tags=["Equipment Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Target equipment cleared successfully.",
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. Non-admin operations blocked.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment database entry target absent.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Deletion",
                response_only=True,
                status_codes=["200"],
                value={"detail": "Equipment successfully deleted."}
            ),
            OpenApiExample(
                name="Equipment Missing Error",
                response_only=True,
                status_codes=["404"],
                value={"detail": "Equipment Not found"}
            )
        ]
    )
    def destroy(self, request, *args, **kwargs):
        """
        Allows admins to remove an equipment item from the database.
        """
        current_user = self.request.user
        equipment_instance = self.get_object()
        title = equipment_instance.title

        if (
            current_user != equipment_instance.owner
            and not current_user.is_superuser
        ):
            return Response(
                {"error": "You are not authorized to delete this equipment."},
                status=status.HTTP_403_FORBIDDEN,
            )
        images_to_delete = []

        if equipment_instance.thumbnail_image and equipment_instance.thumbnail_image.name:
            images_to_delete.append(equipment_instance.thumbnail_image.name)

        for gallery_img in equipment_instance.images.all():
            if gallery_img.image and gallery_img.image.name:
                images_to_delete.append(gallery_img.image.name)

        response = super().destroy(request, *args, **kwargs)

        if response.status_code == status.HTTP_204_NO_CONTENT:
            for file_path in images_to_delete:
                if default_storage.exists(file_path):
                    default_storage.delete(file_path)

            return Response(
                {"success": f"{title} deleted successfully."},
                status=status.HTTP_200_OK,
            )

        return response


    @extend_schema(
        summary="Suggest Equipment Locations",
        description="Returns distinct matching location strings based on trigram similarity for live search bar autocomplete.",
        tags=["Equipment Management"],
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                description="Partial text input to match against equipment address names (e.g., 'bash')",
                required=True,
            )
        ],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                description="List of matching address suggestions.",
            )
        }
    )
    @action(detail=False, methods=['get'], url_path='locations/suggest')
    def suggest_locations(self, request):
        """
        Returns up to 5 matching address names from existing Equipment listings
        using PostgreSQL Trigram Similarity.
        """
        query = request.query_params.get('q', '').strip()
        
        if not query or len(query) < 2:
            return Response([], status=status.HTTP_200_OK)

        suggestions = (
            Equipment.objects
            .filter(address_name__isnull=False)
            .annotate(similarity=TrigramSimilarity('address_name', query))
            .filter(similarity__gt=0.1)
            .order_by('-similarity')
            .values_list('address_name', flat=True)
            .distinct()[:5]
        )

        return Response(list(suggestions), status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='nearby')
    def nearby(self, request):
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        address = request.query_params.get('address')
        
        try:
            radius_km = float(request.query_params.get('radius_km', 10))
        except ValueError:
            return Response({"detail": "Invalid radius_km parameter."}, status=status.HTTP_400_BAD_REQUEST)

        if lat and lng:
            try:
                search_point = Point(float(lng), float(lat), srid=4326)
            except ValueError:
                return Response({"detail": "Invalid lat or lng values."}, status=status.HTTP_400_BAD_REQUEST)

            nearby_equipment = (
                Equipment.objects
                .filter(
                    status='available',
                    location__distance_lte=(search_point, D(km=radius_km))
                )
                .annotate(distance_km=Distance('location', search_point))
                .order_by('distance_km')
            )

        elif address:
            search_point = get_coordinates_from_address(address)

            if search_point:
                nearby_equipment = (
                    Equipment.objects
                    .filter(
                        status='available',
                        location__distance_lte=(search_point, D(km=radius_km))
                    )
                    .annotate(distance_km=Distance('location', search_point))
                    .order_by('distance_km')
                )
            else:
                nearby_equipment = (
                    Equipment.objects
                    .filter(status='available', address_name__isnull=False)
                    .annotate(similarity=TrigramSimilarity('address_name', address))
                    .filter(similarity__gt=0.1)
                    .order_by('-similarity')
                )

        else:
            return Response(
                {"detail": "Provide either ('lat' and 'lng') or an 'address' query parameter."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = EquipmentNearbySerializer(nearby_equipment, many=True)
        
        response_data = {
            "count": nearby_equipment.count(),
            "radius_km": radius_km,
            "results": serializer.data
        }

        if search_point:
            response_data["search_coordinates"] = {
                "lat": round(search_point.y, 6),
                "lng": round(search_point.x, 6)
            }

        return Response(response_data, status=status.HTTP_200_OK)
    
# will work on:
#pagination
#throttling
#owner's name should be present in retrieve rather than id 