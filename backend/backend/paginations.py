import math
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CustomPagination(PageNumberPagination):
    """
    Base class for custom pagination.
    Contains common settings and the standard response structure.
    """

    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_response(self, data):
        """Prepares the paginated response with total_pages."""
        total_count = self.page.paginator.count
        total_pages = math.ceil(total_count / self.get_page_size(self.request))

        return Response(
            {
                "count": total_count,
                "total_pages": total_pages,  # Total number of pages
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )