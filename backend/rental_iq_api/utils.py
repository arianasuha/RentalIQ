import logging
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.images import get_image_dimensions
from rest_framework import serializers
from django.core.cache import cache
from django.contrib.gis.geos import Point
from geopy.geocoders import Nominatim
from redis.exceptions import ConnectionError as RedisConnectionError
from django_redis.exceptions import ConnectionInterrupted



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


# redis-cached geocoding helper

logger = logging.getLogger(__name__)

def get_coordinates_from_address(address_text: str) -> Point | None:
    """
    Checks Redis cache before querying OpenStreetMap Nominatim.
    Appends Bangladesh context and limits search bounds to Bangladesh.
    Returns GeoDjango Point(longitude, latitude) object.
    """
    if not address_text or not address_text.strip():
        return None

    clean_address = address_text.strip().lower()
    
    
    formatted_query = f"{clean_address}, Bangladesh" if "bangladesh" not in clean_address else clean_address
    cache_key = f"geo_cache:{formatted_query}"

    try:
        cached_coords = cache.get(cache_key)
        if cached_coords:
            return Point(cached_coords['lng'], cached_coords['lat'], srid=4326)
    except (RedisConnectionError, ConnectionInterrupted, Exception) as e:
        logger.warning(f"Redis unavailable, falling back to direct geocoding lookup: {e}")

    geolocator = Nominatim(user_agent="rentaliq_app")
    try:
        geo_data = geolocator.geocode(formatted_query, country_codes='bd', timeout=5)
        
        if not geo_data and formatted_query != clean_address:
            geo_data = geolocator.geocode(clean_address, country_codes='bd', timeout=5)

        if geo_data:
            coords = {'lat': geo_data.latitude, 'lng': geo_data.longitude}
            try:
                cache.set(cache_key, coords, timeout=604800)   # 7 days TTL
            except Exception:
                pass
            return Point(geo_data.longitude, geo_data.latitude, srid=4326)
    except Exception as e:
        logger.error(f"Geocoding error for '{address_text}': {e}")

    return None