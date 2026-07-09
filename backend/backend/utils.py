from rest_framework import status
from rest_framework.response import Response


def block_put_method(request, *args, **kwargs):
    """Disallow PUT operation."""
    if request.method == "PUT":
        return Response(
            {"error": "PUT operation not allowed."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
    return None
