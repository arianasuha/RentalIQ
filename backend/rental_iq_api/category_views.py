from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.http import Http404
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse
from core_db.models import Category
from backend.schema_serializers import ErrorResponseSerializer
from .serializers import CategorySerializer


class CategoryViewSet(viewsets.ModelViewSet):

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    http_method_names = ['get', 'post', 'delete']

    def get_permissions(self):
        """
        Dynamically applies permissions based on the incoming action.
        """

        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]
    

    @extend_schema(
        summary="List All Categories",
        description="Retrieves a list of all existing category records. Accessible by anyone.",
        tags=["Category Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=CategorySerializer(many=True),
                description="Successfully fetched categories list.",
            )
        }
    )
    def list(self, request, *args, **kwargs):
        """
        Fetches all categories at once.
        """
        return super().list(request, *args, **kwargs)
        
    
    @extend_schema(
        summary="Retrieve Category Details",
        description="Fetches a single category record safely by its ID string. Accessible by anyone.",
        tags=["Category Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=CategorySerializer,
                description="Category details retrieved successfully.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Category record not found.",
            )
        },
        examples=[
            OpenApiExample(
                name="Category Not Found",
                response_only=True,
                status_codes=["404"],
                value={"detail": "Not found."}
            )
        ]
    )
    def retrieve(self, request, pk=None, *args, **kwargs):
        """
        Fetches a single category record safely using get_object_or_404.
        """
        return super().retrieve(request, *args, **kwargs)
            
    
    @extend_schema(
        summary="Create New Category",
        description="Allows administrative users to compile a new unique category configuration.",
        tags=["Category Management"],
        request=CategorySerializer,
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Category registered successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Bad Request. Missing fields or duplicate unique values.",
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
                value={"detail": "Category successfully created."}
            ),
            OpenApiExample(
                name="Duplicate Name Validation Error",
                response_only=True,
                status_codes=["400"],
                value={"name": ["Category with this name already exists."]}
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
        Allows admins to create a new category configuration.
        """
        response = super().create(request, *args, **kwargs)

        return Response(
            {"detail": "Category successfully created."}, 
            status=status.HTTP_201_CREATED
        )
    

    @extend_schema(
        summary="Delete Category",
        description="Deletes target category structural tracking safely out of the persistent DB backend layer. Admin exclusive.",
        tags=["Category Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Target category unlinked and cleared successfully.",
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. Non-admin operations blocked.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Category database entry search target absent.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Deletion",
                response_only=True,
                status_codes=["200"],
                value={"detail": "Category successfully deleted."}
            ),
            OpenApiExample(
                name="Category Missing Error",
                response_only=True,
                status_codes=["404"],
                value={"detail": "Category Not found"}
            )
        ]
    )
    def destroy(self, request, pk=None, *args, **kwargs):
        """
        Allows admins to remove a category from the database.
        """
        try:
            super().destroy(request, *args, **kwargs)
            
            return Response(
                {"detail": "Category successfully deleted."}, 
                status=status.HTTP_200_OK
            )
            
        except Http404:
            return Response(
                {"detail": "Category Not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )