# RentalIQ - Equipment Rental Platform
A robust, RESTful backend API for an equipment rental ecosystem built with Python, Django, and Django REST Framework (DRF). Designed with enterprise-grade security practices, concurrency management, and clean code architecture.

## Key Highlights of Security Implementations
Although engineered as a commercial rental service, RentIQ integrates defense-in-depth security principles across authentication, data integrity, and network traffic:

### Side-Channel Timing Attack Mitigation: 
Implements constant-time dummy password hashing for non-existent user accounts during login to prevent account enumeration via timing variances.

### Brute-Force Protection & Account Lockouts: 
Tracks failed login attempts in Redis per email address, enforcing an automated account lock (is_active = False) after 5 consecutive failures.

### Strict JWT Lifecycle Management: 
Short-lived access tokens paired with mandatory refresh token rotation (ROTATE_REFRESH_TOKENS = True) and immediate token blacklisting (rest_framework_simplejwt.token_blacklist) upon refresh or logout.

### Strict CORS Policy & Credential Scoping: 
Configured with explicit origin whitelisting (CORS_ALLOWED_ORIGINS) and controlled credential handling (CORS_ALLOW_CREDENTIALS), preventing unauthorized cross-origin requests while restricting wildcard access (CORS_ALLOW_ALL_ORIGINS = False).

### Custom Password Complexity Validation: 
Enforces custom password strength policies (PasswordComplexityValidator) combined with standard Django attribute similarity and numeric checks.

### Soft Deletion for Data Security: 
Implements soft deletion for users, equipment listings, and rental records to prevent irreversible data loss, support forensic audit trails, and maintain relational integrity without exposing deleted entities to standard API queries.

### Immutable Method Enforcement & Access Control: 
Explicitly disables global HTTP PUT requests to prevent full entity overwrites, enforcing object-level ownership checks (instance.owner == request.user) for updates and deletions.

### Role-Based Access Control (RBAC)

Strict permission classes controlling administrative actions—restricting Category CRUD operations exclusively to superusers/admins.

## Key Features

### Geospatial & Proximity Search:

PostGIS PointField (SRID 4326) geometry indexing for spatial queries.

Radius-based filtering using Distance annotations (lat, lng, radius_km).

Address-based proximity search paired with Trigram similarity (pg_trgm) for location autocomplete suggestions.

### Interactive Leaflet.js Frontend Map:

Browser Geolocation API integration with fallback to regional center search.

Real-time debounced location search with auto-complete dropdowns.

Dynamic marker rendering displaying daily rates, exact addresses, and distance to search location.

### Rental Request & Concurrency Engine:

Pessimistic database locking during approvals to eliminate double-booking race conditions.

Automatic rejection of overlapping pending requests upon approval of a booking.

Rate limiting restricting users to a maximum of 5 concurrent pending requests.

### Inventory & Media Handling:

Equipment listing management capped at 4 items per week per user to prevent inventory spamming.

Automated storage cleanup removing thumbnail and gallery media files from storage upon listing deletion.

## Tech Stack
Framework: Django, Django REST Framework (DRF)

Database & Spatial Engine: PostgreSQL, PostGIS (django.contrib.gis)

Caching & Session Storage: Redis (django-redis)

Authentication & Docs: rest_framework_simplejwt, drf-spectacular (OpenAPI 3.0)

Frontend Interface (For map only): Leaflet.js (OpenStreetMap tiles), Vanilla JavaScript (ES6+), HTML5/CSS3
