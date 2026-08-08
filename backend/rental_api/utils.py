from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.images import get_image_dimensions
from rest_framework import serializers


def validate_image_dimensions_and_size(value):
    """
    Field-level validation for image dimensions and file sizes.
    Accepts either a single uploaded image or a list/iterable of uploaded images.
    """
    if not value:
        raise serializers.ValidationError("You must provide at least one image.")
    
    images = value if isinstance(value, (list, tuple)) else [value]

    if any(v in [None, '', b''] for v in images):
        raise serializers.ValidationError("Invalid file upload submitted.")
    
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
    MIN_WIDTH, MIN_HEIGHT = 400, 400
    MAX_WIDTH, MAX_HEIGHT = 4000, 4000

    errors = {} 
    has_errors = False

    for idx, img in enumerate(images):  
        if not img or isinstance(img, str):
            errors[idx] = ["The submitted data was not a valid file."]
            has_errors = True
            continue

        item_errors = []

        if img.size > MAX_FILE_SIZE:
            item_errors.append(f"File size too large. Max is 2MB. (Found {img.size / (1024*1024):.2f}MB)")

        width, height = get_image_dimensions(img)
        if not width or not height:
            item_errors.append("Could not read image dimensions. File may be corrupted.")
        else:
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                item_errors.append(f"Dimensions too small ({width}x{height}px). Minimum is {MIN_WIDTH}x{MIN_HEIGHT}px.")
            if width > MAX_WIDTH or height > MAX_HEIGHT:
                item_errors.append(f"Dimensions too large ({width}x{height}px). Maximum is {MAX_WIDTH}x{MAX_HEIGHT}px.")

        if item_errors:
            errors[idx] = item_errors
            has_errors = True

    if has_errors:
        if not isinstance(value, (list, tuple)):
            raise serializers.ValidationError(errors[0])
        raise serializers.ValidationError(errors)

    return value
