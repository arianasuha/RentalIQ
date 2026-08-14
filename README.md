# RentalIQ - Eqipment Rental Platform
A robust, RESTful backend API for an equipment rental ecosystem built with Python, Django, and Django REST Framework (DRF). Designed with enterprise-grade security practices, concurrency management, and clean code architecture.

## Key Highlights & Security Implementations
### JWT Security & Mitigation Strategies

Stateless Token Auth: Access & Refresh token rotation using djangorestframework-simplejwt.

Token Blacklisting: Automated token invalidation upon user logout.

Timing Attack Defense: Mitigated side-channel user enumeration timing attacks by running constant-time dummy password hashing routines when user lookups fail during authentication.

### Concurrency & Race Condition Safety

Pessimistic Locking / Atomic Transactions: Handles high-concurrency booking requests using select_for_update() within atomic database blocks to prevent double-booking race conditions.

### Data Integrity & Clean Storage Management

Soft Deletion Mechanism: Implemented custom soft-delete queries and model managers for both User and Equipment entities to preserve relational history and audit trails.

Ghost Image Resolution: Automated cleanup hooks and signals for media files to purge orphaned/stale image files from disk during soft deletion or image replacement.

### Role-Based Access Control (RBAC)

Strict permission classes controlling administrative actions—restricting Category CRUD operations exclusively to superusers/admins.

### Tech Stack
Framework: Django, Django REST Framework (DRF)

Authentication: djangorestframework-simplejwt (JWT Rotation & Blacklist)

Database: PostgreSQL
