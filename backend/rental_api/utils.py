from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.images import get_image_dimensions
from rest_framework import serializers


def validate_image_dimensions_and_size(value):
    """
    Field-level validation for image dimensions and file sizes.
    Handles standard Python lists of upload files.
    """
    if not value or any(v in [None, '', b''] for v in value):
        raise serializers.ValidationError("You must provide at least one image.")
    
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
    MIN_WIDTH, MIN_HEIGHT = 400, 400
    MAX_WIDTH, MAX_HEIGHT = 4000, 4000

    errors = {} 
    has_errors = False

    for idx, img in enumerate(value):  
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
        raise serializers.ValidationError(errors)

    return value


def handle_equipment_creation(validated_data, equipment_model, image_model):
    """
    Handles db execution and thumbnail mapping logic for creating equipment.
    """
    images_data = validated_data.pop('additional_images', [])
    thumbnail_image = validated_data.pop('thumbnail_image', None)
    thumbnail_index = validated_data.pop('thumbnail_index', None)

    with transaction.atomic():
        equipment = equipment_model.objects.create(**validated_data)

        created_images = []
        if images_data:
            image_objects = [image_model(equipment=equipment, image=image_data) for image_data in images_data]
            created_images = image_model.objects.bulk_create(image_objects)

        if thumbnail_image:
            thumb_obj = image_model.objects.create(equipment=equipment, image=thumbnail_image)
            equipment.thumbnail_image = thumb_obj.image
        elif thumbnail_index is not None and created_images:
            equipment.thumbnail_image = created_images[thumbnail_index].image
        elif created_images:
            equipment.thumbnail_image = created_images[0].image
        
        equipment.save()

    return equipment

def handle_equipment_creation(validated_data, equipment_model, image_model):
    """
    Handles db execution and thumbnail mapping logic for creating equipment.
    Expects thumbnail_image to be assigned directly on the base object.
    """
    images_data = validated_data.pop('additional_images', [])

    with transaction.atomic():
        equipment = equipment_model.objects.create(**validated_data)

        if images_data:
            image_objects = [
                image_model(equipment=equipment, image=image_data) 
                for image_data in images_data
            ]
            image_model.objects.bulk_create(image_objects)

    return equipment


# def handle_equipment_update(instance, validated_data, image_model):
#     """
#     Handles db updates, deletions, thumbnail swapping, and returns a list of obsolete physical files.
#     """
#     images_to_delete = validated_data.pop('images_to_delete', [])
#     images_data = validated_data.pop('additional_images', [])
#     thumbnail_image = validated_data.pop('thumbnail_image', None)
#     thumbnail_index = validated_data.pop('thumbnail_index', None)
#     thumbnail_id = validated_data.pop('thumbnail_id', None)
    
#     files_to_wipe = []

#     if images_to_delete:
#         images_queryset = instance.images.filter(id__in=images_to_delete)
#         files_to_wipe = [img.image.name for img in images_queryset if img.image]
#         images_queryset.delete()

#     created_images = []
#     if images_data:
#         image_objects = [image_model(equipment=instance, image=image_data) for image_data in images_data]
#         created_images = image_model.objects.bulk_create(image_objects)

#     if thumbnail_image:
#         thumb_obj = image_model.objects.create(equipment=instance, image=thumbnail_image)
#         instance.thumbnail_image = thumb_obj.image
#     elif thumbnail_id is not None:
#         try:
#             chosen_img = instance.images.get(id=thumbnail_id)
#             instance.thumbnail_image = chosen_img.image
#         except image_model.DoesNotExist:
#             pass
#     elif thumbnail_index is not None and created_images:
#         instance.thumbnail_image = created_images[thumbnail_index].image

#     current_thumb_path = instance.thumbnail_image.name if instance.thumbnail_image else None
#     if not current_thumb_path or (images_to_delete and any(f in current_thumb_path for f in files_to_wipe)):
#         remaining_images = instance.images.all()
#         instance.thumbnail_image = remaining_images.first().image if remaining_images.exists() else None
    
#     instance.save()
#     return instance, files_to_wipe


def purge_physical_files(files_to_wipe):
    """
    Cleans up unused images from storage safely.
    """
    for file_name in files_to_wipe:
        try:
            if file_name and default_storage.exists(file_name):
                default_storage.delete(file_name)
        except Exception:
            pass