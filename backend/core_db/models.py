"""
Database models.
"""
from phonenumber_field.modelfields import PhoneNumberField
from django.db import models
from django.utils.text import slugify
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator


class UserManager(BaseUserManager):
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

    objects = UserManager()
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

    def __str__(self):
        """String representation of the user object."""
        return self.email


class Category(models.Model):  
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True) #signals

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    
class Equipment(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('rented', 'Rented'),
        ('maintenance', 'Maintenance'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='equipments')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='equipments')
    title = models.CharField(max_length=255)
    description = models.TextField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    daily_rent = models.DecimalField(max_digits=8, decimal_places=2)
    rent_advance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    total_rentals = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
    

class EquipmentImage(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='equipment_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)


# class RentalRequest(models.Model):
#     STATUS_CHOICES = [
#         ('PENDING', 'Pending'),
#         ('APPROVED', 'Approved'),
#         ('REJECTED', 'Rejected'),
#         ('CANCELLED', 'Cancelled'),
#     ]

#     equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='rental_requests')
#     renter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_requests')
#     start_date = models.DateField()
#     end_date = models.DateField()
#     status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
#     message = models.TextField(blank=True, help_text="Optional note from renter to owner")
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return f"Request by {self.renter.username} for {self.equipment.title} ({self.status})"


# class Rental(models.Model):
#     STATUS_CHOICES = [
#         ('UPCOMING', 'Upcoming'),
#         ('ACTIVE', 'Active'),
#         ('RETURNED', 'Returned'),
#         ('OVERDUE', 'Overdue'),
#     ]

#     rental_request = models.OneToOneField(RentalRequest, on_delete=models.PROTECT, related_name='rental')
#     equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='rentals')
#     renter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rentals_as_renter')
    
#     start_date = models.DateField()
#     end_date = models.DateField()
#     status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='UPCOMING')
    
#     total_price = models.DecimalField(max_digits=10, decimal_places=2)
#     deposit_held = models.DecimalField(max_digits=10, decimal_places=2)
    
#     actual_return_date = models.DateField(null=True, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return f"Rental of {self.equipment.title} by {self.renter.username} ({self.status})"



# class Review(models.Model):
#     # Ties back to the physical rental contract to prevent fake reviews
#     rental = models.OneToOneField(Rental, on_delete=models.CASCADE, related_name='review')
#     equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='reviews')
    
#     # Explicitly tracking who is writing and who is receiving the score
#     renter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='written_reviews')
#     owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_reviews')
    
#     rating = models.PositiveIntegerField(
#         validators=[MinValueValidator(1), MaxValueValidator(5)]
#     )
#     comment = models.TextField()
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return f"Review ({self.rating}★) for {self.equipment.title} by {self.renter.username}" 
