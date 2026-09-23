from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from core_db.models import Equipment, RentalRequest, Rental
from backend.schema_serializers import ErrorResponseSerializer
from .serializers import (
    RentalRequestCreateSerializer,
    RentalRequestRetrieveSerializer,
    RentalRequestListSerializer,
    RentalRequestStatusUpdateSerializer,
)


class RentalRequestViewSet(viewsets.ModelViewSet):
    """
    ViewSet for creating, viewing, and updating rental requests.
    - Renters create and view their own requests.
    - Equipment Owners view requests for their items and manage request status (Approve/Reject).
    """
    queryset = RentalRequest.objects.all()
    serializer_class = RentalRequestRetrieveSerializer
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_permissions(self):
        """All rental request endpoints require authentication."""
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Filters requests based on the user's role:
        - Shows requests made BY the user (as renter).
        - Shows requests made FOR equipment owned by the user (as owner).
        """
        user = self.request.user
        queryset = RentalRequest.objects.select_related('equipment', 'renter', 'equipment__owner')

        if self.action in ['list', 'retrieve']:
            queryset = queryset.filter(
                Q(renter=user) | Q(equipment__owner=user)
            )

        return queryset

    def get_serializer_class(self):
        """Assigns optimal serializer based on the action performed."""
        if self.action == 'create':
            return RentalRequestCreateSerializer
        if self.action == 'list':
            return RentalRequestListSerializer
        if self.action == 'partial_update':
            return RentalRequestStatusUpdateSerializer
        return RentalRequestRetrieveSerializer

    def _check_active_request_limit(self, user):
        """
        Limits a renter to a maximum of 5 concurrent PENDING rental requests.
        """
        MAX_PENDING_REQUESTS = 5
        pending_count = RentalRequest.objects.filter(
            renter=user,
            status=RentalRequest.RequestStatus.PENDING
        ).count()

        if pending_count >= MAX_PENDING_REQUESTS:
            raise PermissionDenied(
                f"You have {pending_count} pending rental requests. "
                f"You cannot create more than {MAX_PENDING_REQUESTS} pending requests simultaneously."
            )

    @extend_schema(
        summary="List Rental Requests",
        description="Returns rental requests relevant to the authenticated user (either as renter or equipment owner).",
        tags=["Rental Request Management"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=RentalRequestListSerializer(many=True),
                description="List of relevant rental requests retrieved successfully.",
            )
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Retrieve Rental Request Details",
        description="Retrieves single rental request by ID. Only accessible by renter or equipment owner.",
        tags=["Rental Request Management"],
        responses={
            status.HTTP_200_OK: RentalRequestRetrieveSerializer,
            status.HTTP_404_NOT_FOUND: ErrorResponseSerializer,
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Create Rental Request",
        description="Submits a request to rent an equipment item for a designated date range.",
        tags=["Rental Request Management"],
        request=RentalRequestCreateSerializer,
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=RentalRequestRetrieveSerializer,
                description="Rental request submitted successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Forbidden. Max pending request threshold reached.",
            )
        },
        examples=[
            OpenApiExample(
                name="Successful Creation",
                response_only=True,
                status_codes=["201"],
                value={
                    "detail": "Rental request submitted successfully.",
                    "data": {
                        "id": 1,
                        "equipment": 3,
                        "renter": 12,
                        "start_date": "2026-09-01",
                        "end_date": "2026-09-05",
                        "daily_rent_snapshot": "50.00",
                        "deposit_amount_snapshot": "100.00",
                        "total_rent_amount": "250.00",
                        "total_days": 5,
                        "status": "PENDING"
                    }
                }
            )
        ]
    )
    def create(self, request, *args, **kwargs):
        self._check_active_request_limit(request.user)

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        detail_serializer = RentalRequestRetrieveSerializer(instance)
        return Response(
            {"detail": "Rental request submitted successfully.", "data": detail_serializer.data},
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Update Rental Request Status",
        description="Allows Equipment Owners to APPROVE or REJECT a pending request, or Renters to CANCEL a pending request.",
        tags=["Rental Request Management"],
        request=RentalRequestStatusUpdateSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=RentalRequestRetrieveSerializer,
                description="Rental request status updated successfully.",
            ),
            status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
        }
    )
    def partial_update(self, request, *args, **kwargs):
        new_status = request.data.get('status')

        if new_status == RentalRequest.RequestStatus.APPROVED:
            return self._approve_request(request, *args, **kwargs)

        if new_status == RentalRequest.RequestStatus.REJECTED:
            return self._reject_request(request, *args, **kwargs)
        
        if new_status == RentalRequest.RequestStatus.CANCELLED:
            return self._cancel_request(request, *args, **kwargs)

        return super().partial_update(request, *args, **kwargs)
    

    @extend_schema(
        summary="Delete / Cancel Rental Request",
        description="Allows renters to delete their pending or rejected requests, or soft-delete them from view.",
        tags=["Rental Request Management"],
        responses={
            status.HTTP_204_NO_CONTENT: OpenApiResponse(description="Rental request deleted successfully."),
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
        }
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        if instance.renter != request.user:
            raise PermissionDenied("You can only delete your own rental requests.")

        if instance.status == RentalRequest.RequestStatus.APPROVED:
            raise ValidationError({
                "detail": "Cannot delete an approved request. Please handle cancellation through the rental agreement."
            })

        # Option A: Hard Delete (Removes row completely)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Approve Rental Request",
        description="Allows Equipment Owners to approve a pending rental request.",
        tags=["Rental Request Management"],
        request=None,  # No request body needed for approval trigger
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response= RentalRequestRetrieveSerializer,
                description="Rental request approved successfully."
            ),
            status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: ErrorResponseSerializer,
        }
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        return self._approve_request(request, pk=pk)
    
    
    def _approve_request(self, request, *args, **kwargs):
        user = request.user

        with transaction.atomic():
            # 1. First lock the parent Equipment row to establish a strict lock order
            #    (Prevents DB deadlocks across concurrent operations)
            try:
                req_obj = RentalRequest.objects.values('equipment_id', 'status').get(pk=kwargs['pk'])
            except RentalRequest.DoesNotExist:
                raise NotFound("Rental request not found.")

            equipment = Equipment.objects.select_for_update().get(pk=req_obj['equipment_id'])

            if equipment.owner != user:
                raise PermissionDenied("Only the equipment owner can approve requests.")

            # 2. Lock the specific RentalRequest row
            instance = (
                RentalRequest.objects
                .select_for_update()
                .get(pk=kwargs['pk'])
            )

            if instance.status != RentalRequest.RequestStatus.PENDING:
                raise ValidationError({"status": ["Only PENDING requests can be approved."]})

            # 3. Re-verify overlap under lock
            has_overlap = RentalRequest.objects.filter(
                equipment=equipment,
                status=RentalRequest.RequestStatus.APPROVED,
                start_date__lte=instance.end_date,
                end_date__gte=instance.start_date
            ).exclude(pk=instance.pk).exists()

            if has_overlap:
                raise ValidationError({
                    "non_field_errors": ["This equipment is already approved for an overlapping date range."]
                })

            instance.status = RentalRequest.RequestStatus.APPROVED
            instance.save() 

            equipment.status = 'rented'
            equipment.save(update_fields=['status'])

            # 5. Auto-reject remaining pending overlaps
            RentalRequest.objects.filter(
                equipment=equipment,
                status=RentalRequest.RequestStatus.PENDING,
                start_date__lte=instance.end_date,
                end_date__gte=instance.start_date
            ).exclude(pk=instance.pk).update(status=RentalRequest.RequestStatus.REJECTED)

        serializer = self.get_serializer(instance)
        return Response({
            "detail": "Rental request approved successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


    def _reject_request(self, request, *args, **kwargs):
        user = request.user

        with transaction.atomic():
            try:
                req_obj = RentalRequest.objects.values('equipment_id', 'status').get(pk=kwargs['pk'])
            except RentalRequest.DoesNotExist:
                raise NotFound("Rental request not found.")

            equipment = Equipment.objects.select_for_update().get(pk=req_obj['equipment_id'])

            # Only equipment owners can reject requests
            if equipment.owner != user:
                raise PermissionDenied("Only the equipment owner can reject requests for this item.")

            instance = RentalRequest.objects.select_for_update().get(pk=kwargs['pk'])

            # Only PENDING requests can be rejected
            if instance.status != RentalRequest.RequestStatus.PENDING:
                raise ValidationError({"status": ["Only PENDING requests can be rejected."]})

            instance.status = RentalRequest.RequestStatus.REJECTED
            instance.save()

        serializer = self.get_serializer(instance)
        return Response({
            "detail": "Rental request rejected successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


    def _cancel_request(self, request, *args, **kwargs):
        user = request.user

        with transaction.atomic():
            # Lock row to prevent concurrent status modification
            try:
                instance = RentalRequest.objects.select_for_update().get(pk=kwargs['pk'])
            except RentalRequest.DoesNotExist:
                raise NotFound("Rental request not found.")

            if instance.renter != user:
                raise PermissionDenied("Only the renter can cancel this request.")

            if instance.status not in [RentalRequest.RequestStatus.PENDING, RentalRequest.RequestStatus.APPROVED]:
                raise ValidationError({"detail": f"Cannot cancel request in '{instance.status}' state."})

            now = timezone.now().date()
            days_until_start = (instance.start_date - now).days

            cancellation_fee = 0
            if instance.status == RentalRequest.RequestStatus.APPROVED:
                if days_until_start < 1:
                    cancellation_fee = instance.deposit_amount_snapshot
                elif days_until_start < 3:
                    cancellation_fee = instance.total_rent_amount * 0.3

            instance.status = RentalRequest.RequestStatus.CANCELLED
            instance.save()

            self._notify_rejected_renters(instance)

        serializer = self.get_serializer(instance)
        return Response({
            "detail": "Rental request cancelled successfully.",
            "cancellation_fee_applied": str(cancellation_fee),
            "data": serializer.data
        }, status=status.HTTP_200_OK)


    def _notify_rejected_renters(self, cancelled_request):
        """
        Finds requests auto-rejected for overlapping dates and sets up 
        future SMTP notification logic when dates reopen.
        """
        overlapping_rejected = RentalRequest.objects.filter(
            equipment=cancelled_request.equipment,
            status=RentalRequest.RequestStatus.REJECTED,
            start_date__lte=cancelled_request.end_date,
            end_date__gte=cancelled_request.start_date
        )

        for req in overlapping_rejected:
            # TODO: Add SMTP email logic or Celery task here later
            pass



# class RentalViewSet(viewsets.ModelViewSet):
#     """
#     ViewSet for managing active rental agreements and physical hand-offs.
#     - Viewable by both renters and equipment owners.
#     - Operational state updates (hand-off, return, deposit) are managed by owners.
#     """
#     queryset = Rental.objects.all()
#     serializer_class = RentalDetailSerializer
#     http_method_names = ['get', 'patch']  

#     def get_permissions(self):
#         return [permissions.IsAuthenticated()]

#     def get_queryset(self):
#         """
#         Restricts active rentals visibility to:
#         - Renters engaged in the rental.
#         - Owners of the underlying rented equipment.
#         """
#         user = self.request.user
#         return Rental.objects.select_related(
#             'rental_request',
#             'rental_request__equipment',
#             'rental_request__renter',
#             'rental_request__equipment__owner'
#         ).filter(
#             Q(rental_request__renter=user) | 
#             Q(rental_request__equipment__owner=user)
#         )

#     def get_serializer_class(self):
#         if self.action == 'partial_update':
#             return RentalUpdateSerializer
#         return RentalDetailSerializer

#     @extend_schema(
#         summary="List Active & Completed Rentals",
#         description="Retrieves a list of all active/completed rental agreements associated with the authenticated user.",
#         tags=["Rental Agreement Management"],
#         responses={
#             status.HTTP_200_OK: RentalDetailSerializer(many=True),
#         }
#     )
#     def list(self, request, *args, **kwargs):
#         return super().list(request, *args, **kwargs)

#     @extend_schema(
#         summary="Retrieve Rental Record Details",
#         description="Fetches detailed agreement status, transaction logs, and return state for a single rental record.",
#         tags=["Rental Agreement Management"],
#         responses={
#             status.HTTP_200_OK: RentalDetailSerializer,
#             status.HTTP_404_NOT_FOUND: ErrorResponseSerializer,
#         }
#     )
#     def retrieve(self, request, *args, **kwargs):
#         return super().retrieve(request, *args, **kwargs)

#     @extend_schema(
#         summary="Update Rental Operational State",
#         description="Allows equipment owners to log returns, update physical hand-off state, or process deposit refunds.",
#         tags=["Rental Agreement Management"],
#         request=RentalUpdateSerializer,
#         responses={
#             status.HTTP_200_OK: OpenApiResponse(
#                 response=RentalDetailSerializer,
#                 description="Rental tracking updated successfully."
#             ),
#             status.HTTP_403_FORBIDDEN: ErrorResponseSerializer,
#             status.HTTP_400_BAD_REQUEST: ErrorResponseSerializer,
#         }
#     )
#     def partial_update(self, request, *args, **kwargs):
#         with transaction.atomic():
#             # 1. Fetch rental record under pessimistic row-lock
#             try:
#                 instance = (
#                     Rental.objects
#                     .select_for_update()
#                     .select_related('rental_request__equipment')
#                     .get(pk=kwargs['pk'])
#                 )
#             except Rental.DoesNotExist:
#                 raise NotFound("Rental record not found.")

#             equipment = instance.rental_request.equipment

#             # 2. Authorization check: Only equipment owner or superuser can update physical state
#             if request.user != equipment.owner and not request.user.is_superuser:
#                 raise PermissionDenied("Only the equipment owner can update operational details of this rental.")

#             # 3. Validate and apply partial update
#             serializer = self.get_serializer(instance, data=request.data, partial=True)
#             serializer.is_valid(raise_exception=True)
            
#             # Automatically stamp actual_return_date when marked RETURNED
#             new_status = serializer.validated_data.get('status')
#             if new_status == Rental.RentalStatus.RETURNED and not instance.actual_return_date:
#                 serializer.validated_data['actual_return_date'] = timezone.now().date()

#             updated_instance = serializer.save()

#             # 4. Synchronize Equipment's physical status
#             if updated_instance.status in [Rental.RentalStatus.ACTIVE, Rental.RentalStatus.OVERDUE]:
#                 equipment.status = 'rented'  # Set to 'rented' (or 'active' based on your choices)
#                 equipment.save()

#             elif updated_instance.status == Rental.RentalStatus.RETURNED:
#                 equipment.status = 'available'
#                 equipment.save()

#         detail_serializer = RentalDetailSerializer(updated_instance)
#         return Response({
#             "detail": "Rental tracking and equipment status updated successfully.",
#             "data": detail_serializer.data
#         }, status=status.HTTP_200_OK)