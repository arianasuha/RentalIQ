from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from django.db.models import Q
from drf_spectacular.utils import (
    extend_schema,
    OpenApiExample,
    OpenApiResponse,
)
from backend.utils import block_put_method
from backend.schema_serializers import (
    RefreshResponseSerializer,
    RefreshRequestSerializer,
    LogoutRequestSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    ErrorResponseSerializer, 
    UserCreateRequestSerializer,
    UserUpdateRequestSerializer
)
from backend.renderers import ViewRenderer
from .serializers import (
    UserDetailSerializer, 
    UserListSerializer, 
    UserRetrieveSerializer
)
from .paginations import UserPagination


User = get_user_model()
DUMMY_PASSWORD_HASH = make_password("dummy_password")

def get_user_role(user):
    """Get user role."""

    if not user.is_active:
        return "UnAuthorized"
        
    if user.is_superuser:
        return "Superuser"
        
    if user.is_staff:
        return "Admin"
        
    return "Default"


def check_create_request_data(request):
    """Check if create request data is valid."""

    current_user = request.user
    if "is_superuser" in request.data:
        return Response(
            {
                "error": "You do not have permission to create a superuser. Contact Developer."
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if "is_staff" in request.data and not current_user.is_superuser:
        return Response(
            {"error": "You do not have permission to create an admin user."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if "slug" in request.data or "is_active" in request.data:
        return Response(
            {"error": "Forbidden fields cannot be updated."},
            status=status.HTTP_403_FORBIDDEN,
        )

    password = request.data.get("password")
    if not password:
        return Response(
            {"error": "Password is required."}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not request.data.get("c_password"):
        return Response(
            {"error": "Please confirm your password."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    c_password = request.data.pop("c_password")
    if password != c_password:
        return Response(
            {"error": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST
        )

    return current_user

def check_update_request_data(user_instance, request):
    """Check if update request data is valid."""

    current_user = request.user

    if current_user.id != user_instance.id and not current_user.is_superuser:
        return Response(
            {"error": "You do not have permission to update this user."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if "email" in request.data:
        return Response(
            {"error": "You cannot update the email field."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if (
        "slug" in request.data  
        or "is_active" in request.data
        or "is_staff" in request.data
        or "is_superuser" in request.data
    ):
        return Response(
            {"error": "Forbidden fields cannot be updated."},
            status=status.HTTP_403_FORBIDDEN,
        )

    password = request.data.get("password")
    if password:
        if not request.data.get("c_password"):
            return Response(
                {"error": "Please confirm your password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        c_password = request.data.pop("c_password")
        if password != c_password:
            return Response(
                {"error": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST
            )

    return current_user


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]


    @extend_schema(
        summary="Refresh Access and Refresh Tokens",
        description="Pass a valid refresh token to get a new access token, an updated refresh token, and user role metadata.",
        request=RefreshRequestSerializer,
        responses={
            200: RefreshResponseSerializer,
            400: OpenApiExample(
                "Bad Request",
                value={"detail": "Invalid Token."}
            ),
            401: OpenApiExample(
                "Unauthorized",
                value={"detail": "Token is invalid or expired."}
            ),
            403: OpenApiExample(
                "Forbidden",
                value={"detail": "This account is deactivated."}
            ),
        }
    )
    def post(self, request, *args, **kwargs):
        request_serializer = RefreshRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        raw_refresh_token = request_serializer.validated_data["refresh_token"]

        try:
            token = RefreshToken(raw_refresh_token)
            
            user_id = token.get("user_id") 

            if not user_id:
                return Response(
                    {"detail": "Invalid Token."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            target_user = User.objects.get(id=user_id)

            user_role = get_user_role(target_user)
            
            if not target_user.is_active:
                return Response(
                    {"detail": "This account is deactivated."}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            new_access_token = token.access_token
            
            token.rotate() 
            new_refresh_token = str(token)

            response_data = {
                "user_id": target_user.id,
                "user_role": user_role,
                "access_token": str(new_access_token),
                "access_token_expiry": timezone.now() + new_access_token.lifetime,
                "refresh_token": new_refresh_token
            }
            
            return Response(response_data, status=status.HTTP_200_OK)

        except (TokenError, InvalidToken) as e:
            return Response(
                {"detail": "Token is invalid or expired."}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        except User.DoesNotExist:
            return Response(
                {"detail": "User associated with this token does not exist."}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    summary="User Login and Token Acquisition",
    description=(
        "Authenticates the user with email and password. "
        "If valid, an access token and refresh token are returned."
    ),
    tags=["Authentication"],
    request=LoginRequestSerializer,
    responses={
        status.HTTP_200_OK: OpenApiResponse(
            response=LoginResponseSerializer,
            description="Successful authentication. Returns JWT tokens and user metadata.",
        ),
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=ErrorResponseSerializer,
            description=(
                "Bad Request. Occurs on invalid credentials, deactivated account, "
                "missing email/password, or other pre-auth failures."
            ),
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiResponse(
            response=ErrorResponseSerializer,
            description="Internal Server Error.",
        ),
    },
    examples=[
        OpenApiExample(
            name="Successful Login",
            response_only=True,
            status_codes=["200"],
            value={
                "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.A-VERY-LONG-JWT-TOKEN-PART-1",
                "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUz1NiJ9.A-VERY-LONG-JWT-TOKEN-PART-2",
                "user_id": 101,
                "user_role": "Agent",
                "access_token_expiry": "2023-06-15T12:34:56.789Z",
            },
        ),
        OpenApiExample(
            name="Superuser Login Request Example",
            value={
                "email": "superuser@example.com",
                "password": "Django@123",
            },
        ),
        OpenApiExample(
            name="Staff Login Request Example",
            value={
                "email": "staffuser@example.com",
                "password": "Django@123",
            },
        ),
        OpenApiExample(
            name="Agent Login Request Example",
            value={
                "email": "agentuser@example.com",
                "password": "Django@123",
            },
        ),
        OpenApiExample(
            name="Default User Login Request Example",
            value={
                "email": "defaultuser@example.com",
                "password": "Django@123",
            },
        ),
        OpenApiExample(
            name="Invalid Credentials Error",
            response_only=True,
            status_codes=["400"],
            value={"error": "Invalid credentials"},
        ),
        OpenApiExample(
            name="Deactivated Account Error",
            response_only=True,
            status_codes=["400"],
            value={"error": "Account is deactivated. Contact your admin"},
        ),
        OpenApiExample(
            name="Missing Email/Password Error",
            response_only=True,
            status_codes=["400"],
            value={"error": "Email and password are required"},
        ),
    ],
)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            return Response(
                {"detail": "Email and password are required."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            target_user = User.objects.get(email=email)
            user_exists = True
        except User.DoesNotExist:
            target_user = None
            user_exists = False

        if user_exists:
            is_password_correct = target_user.check_password(password)
            is_active = target_user.is_active
        else:
            check_password(password, DUMMY_PASSWORD_HASH) 
            is_password_correct = False
            is_active = True

        if not is_active:
            return Response(
                {"detail": "This account is deactivated. Please contact the administrator to reactivate your account."}, 
                status=status.HTTP_403_FORBIDDEN
            )

        cache_key = f"failed_attempts_{email}"

        if not is_password_correct:
            failed_attempts = cache.get(cache_key, 0) + 1
            cache.set(cache_key, failed_attempts, timeout=86400)

            if target_user:
                if failed_attempts >= 5:
                    target_user.is_active = False
                    target_user.save() 
                    cache.delete(cache_key)
                    
                    return Response(
                        {"detail": "This account has been deactivated due to too many failed login attempts. Please contact the administrator to reactivate your account."},
                        status=status.HTTP_403_FORBIDDEN
                    )

                if failed_attempts >= 3 and failed_attempts < 5:
                    remaining = 5 - failed_attempts
                    return Response(
                        {"detail": f"Warning: Invalid credentials. You have {remaining} attempts left before your account is deactivated."},
                        status=status.HTTP_403_FORBIDDEN
                    )

            return Response(
                {"detail": "Invalid credentials. Please try again."}, 
                status=status.HTTP_403_FORBIDDEN
            )

        cache.delete(cache_key)

        try:
            refresh = RefreshToken.for_user(target_user)
            user_role = get_user_role(target_user)

            response_data = {
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "user_id": target_user.pk,
                "user_role": user_role,
                "access_token_expiry": timezone.now() + refresh.access_token.lifetime 
            }
            
            response_serializer = LoginResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@extend_schema(
    summary="User Logout",
    description=("Logout by blacklisting the refresh token."),
    tags=["Authentication"],
    request=LogoutRequestSerializer,
    responses={
        status.HTTP_200_OK: OpenApiResponse(
            response=LoginResponseSerializer,
            description="Successful logout.",
        ),
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=ErrorResponseSerializer,
            description=("Bad Request. Missing tokens."),
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiResponse(
            response=ErrorResponseSerializer,
            description="Internal Server Error.",
        ),
    },
    examples=[
        OpenApiExample(
            name="Successful Logout",
            response_only=True,
            status_codes=["200"],
            value={"success": "Logged out successfully"},
        ),
        OpenApiExample(
            name="Missing Tokens Error",
            response_only=True,
            status_codes=["400"],
            value={"error": "Tokens are required"},
        ),
    ],
)
class LogoutView(APIView):
    """Logout by blacklisting the refresh token"""

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):  #check token validity
        try:
            refresh_token = request.data.get("refresh_token")

            if not refresh_token:
                return Response(
                    {"detail": "Refresh token is required."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response(
                {"success": "Logout successful."}, status=status.HTTP_200_OK
            )
        
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    pagination_class = UserPagination
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        """Dynamically return the serializer class based on the action."""
        if self.action == 'list':
            return UserListSerializer
        elif self.action == 'retrieve':
            return UserRetrieveSerializer
        return UserDetailSerializer

    def get_permissions(self):
        """Assign permissions based on action."""
        if self.action == "create":
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):  
        """Queryset for User View."""
        if self.action == "list":
            if self.request.user.is_staff:
                return get_user_model().objects.all()
            return get_user_model().objects.none()

        if self.action == "retrieve":
            if self.request.user.is_staff:
                return get_user_model().objects.all()
            
            return get_user_model().objects.filter(pk=self.request.user.pk)

        if self.request.user.is_superuser:
            return get_user_model().objects.all()
        return get_user_model().objects.filter(pk=self.request.user.pk)
    
    @extend_schema(
        summary="Create New User",
        description="Registers a new user account. Does not require authentication.",
        tags=["User Management"],
        request=UserCreateRequestSerializer,
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=UserDetailSerializer,
                description="User created successfully. Returns a success message.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description=(
                    "Bad Request. "
                    "Occurs on missing required fields, invalid data format, or duplicate email.",
                ),
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. User does not have staff or superuser privileges.",
            ),
            status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorResponseSerializer,
        },
        examples=[
            OpenApiExample(
                name="Successful User Creation",
                response_only=True,
                status_codes=["201"],
                value={"success": "User created successfully."},
            ),
            OpenApiExample(
                name="Creating Admin as a User Error",
                response_only=True,
                status_codes=["403"],
                value={"error": "You do not have permission to create an admin user."},
            ),
            OpenApiExample(
                name="Updating Forbidden fields.",
                response_only=True,
                status_codes=["403"],
                value={"error": "Forbidden fields cannot be updated."},
            ),
            OpenApiExample(
                name="Password Confirmation Error",
                response_only=True,
                status_codes=["400"],
                value={"error": "Please confirm your password."},
            ),
            OpenApiExample(
                name="Password Matching Error",
                response_only=True,
                status_codes=["400"],
                value={"error": "Passwords do not match."},
            ),
            OpenApiExample(
                name="Email Already Exists Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {
                        "email": [
                            "User with this email already exists.",
                        ]
                    }
                },
            ),
            OpenApiExample(
                name="Invalid Email Address Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {
                        "email": [
                            "Enter a valid email address.",
                        ]
                    }
                },
            ),
            OpenApiExample(
                name="Password Complexity Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {
                        "password": [
                            "Password must be at least 8 characters.",
                            "Password must contain at least one uppercase letter.",
                            "Password must contain at least one number.",
                            "Password must contain at least one special character.",
                        ]
                    }
                },
            ),
        ],
    )
    
    def create(self, request, *args, **kwargs):  
        """Create new user and send email verification link."""

        check_integrity = check_create_request_data(request)

        if isinstance(check_integrity, Response):
            return check_integrity
        
        response = super().create(request, *args, **kwargs)

        if response.status_code != status.HTTP_201_CREATED:
            return response

        return Response(
            {"success": "User profile created successfully."},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="List All Users",
        description=(
            "Returns a paginated list of all user accounts. "
            "Access is restricted to staff/superusers.",
        ),
        tags=["User Management"],
        request=None,
        responses={
            status.HTTP_200_OK: UserListSerializer,
            status.HTTP_401_UNAUTHORIZED: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. User does not have staff or superuser privileges.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Forbidden Access",
                response_only=True,
                status_codes=["403"],
                value={"error": "You do not have permission to perform this action."},
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Retrieve Single User Details",
        description="Returns the details of a specific user by ID.",
        tags=["User Management"],
        request=None,
        responses={
            status.HTTP_200_OK: UserRetrieveSerializer,
            status.HTTP_401_UNAUTHORIZED: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description=(
                    "Not Found. "
                    "The user ID does not exist "
                    "or the authenticated user does not have permission to view it.",
                ),
            ),
        },
        examples=[
            OpenApiExample(
                name="Not Found Error",
                response_only=True,
                status_codes=["404"],
                value={"error": "Not found."},
            ),
            OpenApiExample(
                name="Forbidden Access",
                response_only=True,
                status_codes=["403"],
                value={"error": "You do not have permission to perform this action."},
            ),
            OpenApiExample(
                name="Unauthorized Access",
                response_only=True,
                status_codes=["401"],
                value={"error": "You are not authenticated."},
            ),
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    
    def update(self, request, *args, **kwargs):
        """Allow only users to update their own profile. SuperUser can update any profile.
        Patch method allowed, Put method not allowed"""

        not_allowed_method = block_put_method(request, *args, **kwargs)

        if not_allowed_method:
            return not_allowed_method

        user = self.get_object()

        check_integrity = check_update_request_data(user, request)

        if isinstance(check_integrity, Response):
            return check_integrity

        response = super().update(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            user.refresh_from_db()
            retrieve_serializer = UserRetrieveSerializer(
                user,
                context=self.get_serializer_context(),
            )
            return Response(
                {
                    "success": "User profile updated successfully.",
                    "data": retrieve_serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        return response
    
    @extend_schema(
        summary="Update User Profile (Partial)",
        description="Partially updates an existing user profile (PATCH method).",
        tags=["User Management"],
        request=UserUpdateRequestSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=UserRetrieveSerializer,
                description="User profile updated successfully. Returns the updated user object.",
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Bad Request. Occurs on invalid field values or data integrity errors.",
            ),
            status.HTTP_401_UNAUTHORIZED: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Unauthorized. User is not authenticated.",
            ),
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: ErrorResponseSerializer,
            status.HTTP_405_METHOD_NOT_ALLOWED: ErrorResponseSerializer,
        },
        examples=[
            OpenApiExample(
                name="Success",
                response_only=True,
                status_codes=["200"],
                value={
                    "success": "User profile updated successfully.",
                    "data": {
                        "id": 1,
                        "slug": "updateduser",
                        "first_name": "Updated",
                        "last_name": "User",
                        "username": "updateduser",
                        "email": "1b8Xu@example.com",
                    },
                },
            ),
            OpenApiExample(
                name="Method Not Allowed",
                response_only=True,
                status_codes=["405"],
                value={"error": "PUT operation not allowed."},
            ),
            OpenApiExample(
                name="Unauthorized User Update Error",
                response_only=True,
                status_codes=["401"],
                value={"error": "You are not authenticated."},
            ),
            OpenApiExample(
                name="Not Found Error",
                response_only=True,
                status_codes=["404"],
                value={"error": "Not found."},
            ),
            OpenApiExample(
                name="Unauthorized User Update Error",
                response_only=True,
                status_codes=["403"],
                value={"error": "You do not have permission to update this user."},
            ),
            OpenApiExample(
                name="Updating Email field",
                response_only=True,
                status_codes=["403"],
                value={"error": "You cannot update the email field."},
            ),
            OpenApiExample(
                name="Updating Forbidden fields.",
                response_only=True,
                status_codes=["403"],
                value={"error": "Forbidden fields cannot be updated."},
            ),
            OpenApiExample(
                name="Username Already Exists Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {"username": ["User with this username already exists."]}
                },
            ),
            OpenApiExample(
                name="Username Too Short Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {
                        "username": ["Username must be at least 6 characters long."]
                    }
                },
            ),
            OpenApiExample(
                name="Password Confirmation Error",
                response_only=True,
                status_codes=["400"],
                value={"error": "Please confirm your password."},
            ),
            OpenApiExample(
                name="Password Matching Error",
                response_only=True,
                status_codes=["400"],
                value={"error": "Passwords do not match."},
            ),
            OpenApiExample(
                name="Password Complexity Error",
                response_only=True,
                status_codes=["400"],
                value={
                    "error": {
                        "password": [
                            "Password must be at least 8 characters.",
                            "Password must contain at least one uppercase letter.",
                            "Password must contain at least one number.",
                            "Password must contain at least one special character.",
                        ]
                    }
                },
            ),
        ],
    )
    
    def partial_update(self, request, *args, **kwargs):
        """Partially updates an existing user profile (PATCH method)."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


    @extend_schema(
        summary="Delete User Profile",
        description="Deletes a user profile by ID.",
        tags=["User Management"],
        request=None,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"success": {"type": "string"}},
                },
                description="User Profile Deleted Successfully.",
            ),
            status.HTTP_401_UNAUTHORIZED: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                response=ErrorResponseSerializer,
                description=("User ID Not Found or Does not exist. "),
            ),
        },
        examples=[
            OpenApiExample(
                name="Successful User Deletion",
                response_only=True,
                status_codes=["200"],
                value={"success": "User Profile Deleted Successfully."},
            ),
            OpenApiExample(
                name="Unauthorized User Delete Error",
                response_only=True,
                status_codes=["401"],
                value={"error": "You are not authenticated."},
            ),
            OpenApiExample(
                name="User ID Not Found Error",
                response_only=True,
                status_codes=["404"],
                value={"error": "User ID Not Found or Does not exist."},
            ),
            OpenApiExample(
                name="Forbidden User Delete Error",
                response_only=True,
                status_codes=["403"],
                value={"error": "You are not authorized to delete this user."},
            ),
            OpenApiExample(
                name="Superuser Delete Error",
                response_only=True,
                status_codes=["403"],
                value={"error": "You cannot delete superusers."},
            ),
        ],
    )
    def destroy(self, request, *args, **kwargs):
        """Allow user to delete their own profile and superuser to delete normal or staff users"""
        current_user = self.request.user
        user_to_delete = self.get_object()

        if not current_user.is_superuser and current_user.id != user_to_delete.id:
            return Response(
                {"error": "You are not authorized to delete this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user_to_delete.is_superuser:
            return Response(
                {"error": "You cannot delete superusers"},
                status=status.HTTP_403_FORBIDDEN,
            )


        email = user_to_delete.email
        response = super().destroy(request, *args, **kwargs)

        if response.status_code == status.HTTP_204_NO_CONTENT:
            return Response(
                {"success": f"User {email} deleted successfully."},
                status=status.HTTP_200_OK,
            )

        return response
