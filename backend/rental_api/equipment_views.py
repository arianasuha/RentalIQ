from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.http import Http404
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse
from core_db.models import Equipment
from backend.schema_serializers import ErrorResponseSerializer
from backend.utils import block_put_method
from .serializers import EquipmentDetailSerializer, EquipmentListSerializer, EquipmentRetrieveSerializer
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

        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]
    

    def get_queryset(self):
        if self.action == "retrieve":
            return Equipment.objects.select_related('owner', 'category').all()
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
        
        # case-insensitive check on 'title' for this specific 'owner'
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
        description="Allows administrative users to register a new equipment item into the inventory.",
        tags=["Equipment Management"],
        request=EquipmentDetailSerializer,
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment registered successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Bad Request. Missing fields or invalid reference IDs (e.g., bad category ID).",
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. User lacks administrative permissions.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Creation Response",
                response_only=True,
                status_codes=["201"],
                value={"detail": "Equipment successfully created."}
            ),
            OpenApiExample(
                name="Validation Error",
                response_only=True,
                status_codes=["400"],
                value={"category": ["Invalid pk \"999\" - object does not exist."]}
            ),
            OpenApiExample(
                name="Permission Blocked Error",
                response_only=True,
                status_codes=["403"],
                value={"detail": "Authentication credentials were not provided."}
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
        description="Updates subset fields of a specific equipment item. Admin exclusive.",
        tags=["Equipment Management"],
        request=EquipmentDetailSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Equipment patched successfully.",
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
                name="Successful Partial Update Response",
                response_only=True,
                status_codes=["200"],
                value={"detail": "Equipment patch applied successfully."}
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
        
        response = super().destroy(request, *args, **kwargs)


        if response.status_code == status.HTTP_204_NO_CONTENT:
            return Response(
                {"success": f"{title} deleted successfully."},
                status=status.HTTP_200_OK,
            )

        return response
    


#pagination
#throttling
#owner's name should be present in retrieve rather than id 