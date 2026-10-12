# RentalIQ - Equipment Rental Platform
A robust, RESTful backend API for an equipment rental ecosystem built with Python, Django, and Django REST Framework (DRF). Designed with enterprise-grade security practices, concurrency management, and clean code architecture.

## Key Highlights of Security Implementations
Although engineered as a commercial rental service, RentIQ integrates defense-in-depth security principles across authentication, data integrity, and network traffic:

### Atomic Escrow & Financial Ledger Integrity:
* **Zero Float Precision:** Utilizes strict `DecimalField` configurations paired with PostgreSQL database-level `CheckConstraint` validation to enforce non-negative balances and prevent monetary rounding vulnerabilities.
* **Pessimistic Concurrency Control:** Wraps deposit holds and rental approvals inside `transaction.atomic()` alongside PostgreSQL row-level locks (`select_for_update()`), completely eliminating race conditions during concurrent payouts or booking approvals.

### Idempotent Webhook Architecture:
* **At-Least-Once Delivery Safety:** Implements a database-enforced unique `idempotency_key` constraint for payment gateway webhooks. Duplicate network retry payloads are caught instantly via `IntegrityError`, guaranteeing zero duplicate billing or ledger modifications

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
### Event-Driven Late Penalty Engine (Celery + Redis):
* **Asynchronous Polling:** Configured Celery Beat background workers running periodic tasks to poll active rentals past their return deadline.
* **Automated State Transitions:** Automatically shifts booking states from `ACTIVE` to `OVERDUE` and computes progressive hourly/daily penalty deductions directly from the renter's held security deposit.

### Idempotent Webhook & Payment Architecture:
* **At-Least-Once Delivery Safety:** Simulates payment gateway webhook processing with database-enforced unique `idempotency_key` constraints.
* **Integrity Guardrails:** Catches duplicate network retry payloads instantly via `IntegrityError` inside atomic transactions, guaranteeing zero duplicate billing or unintended ledger modifications.
  
### Geospatial & Proximity Search:

* PostGIS PointField (SRID 4326) geometry indexing for spatial queries.
* Radius-based filtering using Distance annotations (lat, lng, radius_km).
* Address-based proximity search paired with Trigram similarity (pg_trgm) for location autocomplete suggestions.

### Interactive Leaflet.js Frontend Map:

* Browser Geolocation API integration with fallback to regional center search.
* Real-time debounced location search with auto-complete dropdowns.
* Dynamic marker rendering displaying daily rates, exact addresses, and distance to search location.

### Rental Request & Concurrency Engine:

* Pessimistic database locking during approvals to eliminate double-booking race conditions.
* Automatic rejection of overlapping pending requests upon approval of a booking.
* Rate limiting restricting users to a maximum of 5 concurrent pending requests.

### Inventory & Media Handling:

* Equipment listing management capped at 4 items per week per user to prevent inventory spamming.
* Automated storage cleanup removing thumbnail and gallery media files from storage upon listing deletion.

## Tech Stack
* Framework: Django, Django REST Framework (DRF)
* Asynchronous Task Queue & Broker: Celery, Celery Beat, Redis
* Database & Spatial Engine: PostgreSQL, PostGIS (django.contrib.gis)
* Caching & Session Storage: Redis (django-redis)
* Authentication & Docs: rest_framework_simplejwt, drf-spectacular (OpenAPI 3.0)
* Frontend Interface (For map only): Leaflet.js (OpenStreetMap tiles), Vanilla JavaScript (ES6+), HTML5/CSS3
