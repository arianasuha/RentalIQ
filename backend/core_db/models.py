"""
Database models.
"""
import uuid
from phonenumber_field.modelfields import PhoneNumberField
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.auth.password_validation import validate_password
from django.contrib.gis.db import models as gis_models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator


class UserQuerySet(models.QuerySet):
    """Custom QuerySet to allow chaining filter methods."""
    def active(self):
        return self.filter(is_deleted=False)
    
class UserManager(BaseUserManager):
    def get_queryset(self):
        return UserQuerySet(self.model, using=self._db)
    
    def create_user(self, email, password=None, **extra_fields):
        """Create, save and return a new user."""
        if not email:
            raise ValueError('Users must have an email address.')

        try:
            validate_email(email)
        except ValidationError:
            raise ValueError('The provided email is not a valid format.')

        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return superuser."""
        if password is None:
            raise TypeError('Superusers must have a password.')

        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        user = self.create_user(email, password, **extra_fields)
        return user

class ActiveUserManager(UserManager):
    """Default Manager: Automatically filters out soft-deleted users."""
    def get_queryset(self):
        return super().get_queryset().active()
    
class User(AbstractBaseUser, PermissionsMixin):
    """Custom User class in the system."""
    class Meta:
        ordering = ["email"]
        
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(max_length=255, unique=True)
    username = models.CharField(
        max_length=150,
        unique=True,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9_-]+$",
                message="Username can only contain letters, numbers, underscores, and hyphens.",
                code="invalid_username",
            )
        ],
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    phone_number = PhoneNumberField(unique=True, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    trust_score = models.IntegerField(default=0)
    image_url = models.ImageField(upload_to='user_images/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    objects = ActiveUserManager()       
    all_objects = UserManager() 

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def set_password(self, raw_password):
        """Validates raw password before hashing"""
        if not raw_password:
            raise ValidationError("Password is required.")
        
        validate_password(raw_password, user=self)
        
        super().set_password(raw_password)

    def save(self, *args, **kwargs):
        if not self.pk and not self.slug:
            base_slug = slugify(self.email.split('@')[0])
            
            if not base_slug:
                base_slug = 'user'

            new_slug = base_slug
            counter = 1
            while self.__class__.objects.filter(slug=new_slug).exists():  #time complexity O(n^2), need to mitigate
                new_slug = f'{base_slug}-{counter}'
                counter += 1

            self.slug = new_slug
            
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        """Soft-deletes the user account and frees up unique constraints."""
        stamp = int(timezone.now().timestamp())
        prefix = f"deleted_{stamp}_"

        # Scramble Email
        max_email_len = 255 - len(prefix)
        self.email = f"{prefix}{self.email[:max_email_len]}"
        
        # Scramble Username if present
        if self.username:
            max_orig_len = 150 - len(prefix)  
            self.username = f"{prefix}{self.username[:max_orig_len]}"
            
        # Clear unique phone number constraint
        if self.phone_number:
            self.phone_number = None

        self.is_active = False
        self.is_deleted = True
        self.deleted_at = timezone.now()
        super().save(using=using)

    def __str__(self):
        """String representation of the user object."""
        return self.email


class Category(models.Model):  
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True) #signals

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class EquipmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_deleted=False)

class EquipmentManager(models.Manager):
    """Base manager returning all equipment records."""
    def get_queryset(self):
        return EquipmentQuerySet(self.model, using=self._db)

class ActiveEquipmentManager(EquipmentManager):
    """Filters out soft-deleted equipment by default."""
    def get_queryset(self):
        return super().get_queryset().active()


class Equipment(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('rented', 'Rented'),
        ('maintenance', 'Maintenance'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='equipments'
    )
    category = models.ForeignKey('Category', on_delete=models.CASCADE, related_name='equipments')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    daily_rent = models.DecimalField(
    max_digits=8, 
    decimal_places=2,
    validators=[MinValueValidator(Decimal('0.01'))] 
    )
    thumbnail_image = models.ImageField(upload_to='equipment_thumbnails/')
    rent_advance = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    total_rentals = models.PositiveIntegerField(default=0)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Soft Delete Fields
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # GeoDjango Point field (Stores longitude and latitude as geometric coordinates)
    location = gis_models.PointField(srid=4326, null=True, blank=True, db_index=True)
    address_name = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="Human-readable address e.g. Banani, Dhaka"
    )

    # Model Managers
    objects = ActiveEquipmentManager()  # Equipment.objects.all() returns active items
    all_objects = EquipmentManager()      # Equipment.all_objects.all() includes deleted items

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                Lower('title'),
                'owner', 
                name='unique_owner_equipment_title'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.pk and not self.slug:
            base_slug = slugify(self.title) or 'item'
            self.slug = f"{base_slug[:80]}-{str(uuid.uuid4())[:8]}"

        if not self.is_deleted:
            self.full_clean()
            
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def delete(self, using=None, keep_parents=False): 
        """Prevents deletion if active rentals exist; soft-deletes otherwise."""
        # Check through the related Rental model for ongoing fulfillment
        has_active = self.rental_requests.filter(
            Q(rental__status__in=['UPCOMING', 'ACTIVE', 'OVERDUE']) | Q(status='PENDING')
        ).exists()

        if has_active:
            raise ValidationError(
                "Cannot delete equipment with active rentals or pending requests."
            )

        stamp = int(timezone.now().timestamp())
        prefix = f"[DELETED_{stamp}] "
        max_len = 255 - len(prefix)
        self.title = f"{prefix}{self.title[:max_len]}"
        
        self.is_deleted = True
        self.deleted_at = timezone.now()
        super().save(using=using)


        # should i add the full clean logic? as terminal by passed thumbnail image constraint


class EquipmentImage(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='equipment_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)


class RentalRequest(models.Model):
    class RequestStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'   
        CANCELLED = 'CANCELLED', 'Cancelled'  

    class FulfillmentType(models.TextChoices):
        PICKUP = 'PICKUP', 'In-Person Pickup'
        DELIVERY = 'DELIVERY', 'Delivery'

    equipment = models.ForeignKey(
        'Equipment',
        on_delete=models.CASCADE,
        related_name='rental_requests'
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rental_requests'
    )

    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)

    fulfillment_type = models.CharField(
        max_length=20,
        choices=FulfillmentType.choices,
        default=FulfillmentType.PICKUP,
    )
    delivery_address = models.TextField(blank=True, null=True)
    delivery_contact_phone = PhoneNumberField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    daily_rent_snapshot = models.DecimalField(   
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    deposit_amount_snapshot = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    total_rent_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['equipment', 'start_date', 'end_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')), 
                name='request_end_date_after_start_date'
            )
        ]

    def __str__(self):
        return f"Request #{self.id} - {self.equipment.title} by {self.renter.email}"

    @property       
    def total_days(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0

    def clean(self):    
        super().clean()
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValidationError("End date cannot be earlier than start date.")

            if self.status == self.RequestStatus.APPROVED:
                overlapping = RentalRequest.objects.filter(
                    equipment=self.equipment,
                    status=self.RequestStatus.APPROVED,
                    start_date__lte=self.end_date,
                    end_date__gte=self.start_date
                )
                if self.pk:
                    overlapping = overlapping.exclude(pk=self.pk)
                if overlapping.exists():
                    raise ValidationError("This equipment is already reserved for the specified dates.")

    def save(self, *args, **kwargs):
        if not self.pk:
            if not self.daily_rent_snapshot:
                self.daily_rent_snapshot = self.equipment.daily_rent
            
            if self.deposit_amount_snapshot is None:
                raw_advance = getattr(self.equipment, 'rent_advance', None)
                self.deposit_amount_snapshot = raw_advance if raw_advance is not None else Decimal('0.00')

        if self.daily_rent_snapshot and self.total_days > 0:
            self.total_rent_amount = self.daily_rent_snapshot * Decimal(self.total_days)

        self.full_clean()
        super().save(*args, **kwargs)


class Rental(models.Model):
    class RentalStatus(models.TextChoices):
        UPCOMING = 'UPCOMING', 'Upcoming'
        ACTIVE = 'ACTIVE', 'Active'
        RETURNED = 'RETURNED', 'Returned'
        OVERDUE = 'OVERDUE', 'Overdue'

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    # Single Source of Truth
    rental_request = models.OneToOneField(
        RentalRequest,
        on_delete=models.PROTECT,
        related_name='rental'
    )

    # Operational Tracking (Fields specific ONLY to active fulfillment)
    actual_return_date = models.DateField(null=True, blank=True)
    deposit_returned = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=RentalStatus.choices,
        default=RentalStatus.UPCOMING,
        db_index=True
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True
    )

    transaction_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'payment_status']),
        ]

    def __str__(self):
        return f"Rental #{self.id} - {self.rental_request.equipment.title} ({self.status})"

    
# class Notification(models.Model):
#     class NotificationType(models.TextChoices):
#         # Rental Request Lifecycle
#         REQUEST_RECEIVED = 'REQUEST_RECEIVED', 'New Rental Request Received'
#         REQUEST_APPROVED = 'REQUEST_APPROVED', 'Rental Request Approved'
#         REQUEST_REJECTED = 'REQUEST_REJECTED', 'Rental Request Rejected'
#         REQUEST_CANCELLED = 'REQUEST_CANCELLED', 'Rental Request Cancelled'

#         # Rental Operations & Payment
#         PAYMENT_SUCCESS = 'PAYMENT_SUCCESS', 'Payment Received'
#         RENTAL_ACTIVE = 'RENTAL_ACTIVE', 'Rental Period Started'
#         RENTAL_OVERDUE = 'RENTAL_OVERDUE', 'Rental Overdue Warning'
#         RENTAL_COMPLETED = 'RENTAL_COMPLETED', 'Rental Marked as Returned'

#         # Account & General
#         SYSTEM_ALERT = 'SYSTEM_ALERT', 'System Alert'

#     recipient = models.ForeignKey(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.CASCADE,
#         related_name='notifications',
#         db_index=True
#     )
#     actor = models.ForeignKey(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.SET_NULL,
#         null=True,
#         blank=True,
#         related_name='sent_notifications',
#         help_text="The user who triggered the notification (e.g., renter, owner, or system if null)."
#     )
    
#     notification_type = models.CharField(
#         max_length=50,
#         choices=NotificationType.choices,
#         default=NotificationType.SYSTEM_ALERT,
#         db_index=True
#     )
#     title = models.CharField(max_length=255)
#     message = models.TextField()

#     # Optional generic link or object references to support direct routing in frontend/API
#     rental_request = models.ForeignKey(
#         'RentalRequest',
#         on_delete=models.SET_NULL,
#         null=True,
#         blank=True,
#         related_name='notifications'
#     )
#     rental = models.ForeignKey(
#         'Rental',
#         on_delete=models.SET_NULL,
#         null=True,
#         blank=True,
#         related_name='notifications'
#     )
#     equipment = models.ForeignKey(
#         'Equipment',
#         on_delete=models.SET_NULL,
#         null=True,
#         blank=True,
#         related_name='notifications'
#     )
    
#     # Tracking State
#     is_read = models.BooleanField(default=False, db_index=True)
#     created_at = models.DateTimeField(auto_now_add=True, db_index=True)

#     class Meta:
#         ordering = ['-created_at']
#         indexes = [
#             models.Index(fields=['recipient', 'is_read', 'created_at']),
#         ]

#     def __str__(self):
#         return f"Notification for {self.recipient.email} - {self.notification_type} ({'Read' if self.is_read else 'Unread'})"

#     def mark_as_read(self):
#         """Helper method to mark single notification as read."""
#         if not self.is_read:
#             self.is_read = True
#             self.save(update_fields=['is_read'])
