# Rule Engine

A headless, API-first rule engine for building product configurators (CPQ systems). Define entities with versioned schemas, configurable fields, and dynamic business rules that control visibility, availability, validation, and more.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Problem

Product configurators are complex. A laptop configurator needs to:
- Show/hide fields based on selections (GPU options only for "Pro" models)
- Filter available values dynamically (16GB RAM unavailable with entry-level CPU)
- Validate combinations (SSD + HDD cannot exceed chassis capacity)
- Generate SKU codes from selections (LPT-PRO-16G-512S)
- Support version management (draft v2 while v1 is live)
- Track configuration lifecycle (draft → finalized → archived)

Building this from scratch for every product is wasteful. This engine provides the foundation.

## The Solution

A **domain-agnostic rule engine** that separates *what* can be configured from *how* the UI presents it:

- **Headless**: Pure REST API, bring your own frontend
- **Versioned**: Draft, publish, archive entity schemas without downtime
- **Rule-driven**: Declarative JSON conditions control field behavior
- **Stateful configurations**: Save, clone, upgrade, finalize user configurations
- **SKU generation**: Automatic product codes from field selections

---

## Features

### Core Engine
- **5 rule types**: Visibility, Availability, Editability, Mandatory, Validation
- **Waterfall evaluation**: Rules processed in field order with cascading effects
- **Operator support**: Equals, NotEquals, GreaterThan, LessThan, In, NotIn, Contains, StartsWith, EndsWith, IsNull, IsNotNull
- **Cascading dropdowns**: Field B options filter based on Field A selection

### Version Management
- **Lifecycle states**: DRAFT → PUBLISHED → ARCHIVED
- **Single published version**: Publishing auto-archives the previous version
- **Deep cloning**: Clone versions with all fields, values, and rules
- **DRAFT-only editing**: Published/archived versions are immutable

### Configuration Lifecycle
- **DRAFT configurations**: Mutable, upgradeable to newer entity versions
- **FINALIZED configurations**: Immutable snapshots for legal/audit purposes
- **Clone & upgrade**: Fork configurations or migrate to latest schema
- **Soft delete**: Preserve audit trail for finalized records

### Security & Auth
- **JWT authentication**: Short-lived access tokens (30 min default)
- **Refresh token rotation**: Optional security hardening
- **Role-based access**: ADMIN, AUTHOR, USER with granular permissions
- **Rate limiting**: Configurable limits on auth endpoints

### SKU Generation
- **Base SKU + modifiers**: `LPT-PRO` + `-16G` + `-512S` → `LPT-PRO-16G-512S`
- **Custom delimiters**: Configure separator per entity version
- **Visibility-aware**: Hidden fields excluded from SKU
- **Free-value support**: Append modifier when text field is filled

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI 0.100+ |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Validation | Pydantic 2.0 |
| Auth | python-jose (JWT) + passlib (bcrypt) |
| Rate Limiting | slowapi |
| Testing | pytest + testcontainers |
| Infrastructure | Docker + Docker Compose |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- (Optional) Python 3.11+ for local development

### Run with Docker

```bash
# Clone the repository
git clone https://github.com/yourusername/rule-engine.git
cd rule-engine

# Create environment file
cp .env.example .env

# Start services
docker compose up --build

# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### Run Tests

```bash
# Run all tests (uses testcontainers, requires Docker)
pytest

# Run specific test categories
pytest tests/api/           # API endpoint tests
pytest tests/engine/        # Rule engine logic tests
pytest tests/integration/   # End-to-end workflows

# With coverage
pytest --cov=app --cov-report=html
```

### Environment Variables

```bash
# .env file
DATABASE_URL=postgresql://user:password@localhost:5432/rule_engine_db

# JWT Configuration
SECRET_KEY=your-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENABLE_TOKEN_ROTATION=false

# Rate Limiting
RATE_LIMIT_LOGIN=5/15minutes
RATE_LIMIT_REFRESH=10/5minutes
```

---

## Architecture

### Domain Model

```mermaid
erDiagram
    Entity ||--o{ EntityVersion : "has versions"
    EntityVersion ||--o{ Field : "contains"
    EntityVersion ||--o{ Rule : "contains"
    EntityVersion ||--o{ Configuration : "used by"
    Field ||--o{ Value : "has options"
    Rule }o--|| Field : "targets"
    Rule }o--o| Value : "targets (optional)"
    User ||--o{ Configuration : "owns"
    User ||--o{ RefreshToken : "has"

    Entity {
        int id PK
        string name UK
        string description
    }

    EntityVersion {
        int id PK
        int entity_id FK
        int version_number
        enum status "DRAFT|PUBLISHED|ARCHIVED"
        string sku_base
        string sku_delimiter
        datetime published_at
    }

    Field {
        int id PK
        int entity_version_id FK
        string name
        string label
        enum data_type "string|number|boolean|date"
        bool is_required
        bool is_readonly
        bool is_hidden
        bool is_free_value
        string default_value
        string sku_modifier_when_filled
        int step
        int sequence
    }

    Value {
        int id PK
        int field_id FK
        string value
        string label
        bool is_default
        string sku_modifier
    }

    Rule {
        int id PK
        int entity_version_id FK
        int target_field_id FK
        int target_value_id FK "nullable"
        enum rule_type "visibility|availability|editability|mandatory|validation"
        json conditions
        string error_message
    }

    Configuration {
        uuid id PK
        int entity_version_id FK
        uuid user_id FK
        string name
        enum status "DRAFT|FINALIZED"
        bool is_complete
        bool is_deleted
        json data
    }

    User {
        uuid id PK
        string email UK
        string hashed_password
        enum role "admin|author|user"
        bool is_active
    }

    RefreshToken {
        int id PK
        uuid user_id FK
        string token_hash UK
        datetime expires_at
        bool is_revoked
    }
```

### EntityVersion Lifecycle

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Create version
    DRAFT --> DRAFT: Edit fields/rules
    DRAFT --> PUBLISHED: Publish
    DRAFT --> [*]: Delete

    PUBLISHED --> ARCHIVED: New version published
    PUBLISHED --> PUBLISHED: Read only

    ARCHIVED --> ARCHIVED: Read only

    note right of DRAFT: Mutable\nCan add/edit/delete fields, values, rules
    note right of PUBLISHED: Immutable\nActive version for configurations
    note right of ARCHIVED: Immutable\nHistorical record
```

### Configuration Lifecycle

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Create configuration

    DRAFT --> DRAFT: Update inputs
    DRAFT --> DRAFT: Upgrade to new version
    DRAFT --> FINALIZED: Finalize
    DRAFT --> [*]: Hard delete

    FINALIZED --> FINALIZED: Read only
    FINALIZED --> DRAFT: Clone (new config)
    FINALIZED --> [*]: Soft delete (ADMIN only)

    note right of DRAFT: Mutable sandbox\nUser can modify, upgrade, delete
    note right of FINALIZED: Immutable snapshot\nLegal/audit preservation
```

### Rule Evaluation Flow

```mermaid
flowchart TD
    A[Receive configuration inputs] --> B[Load EntityVersion with Fields & Rules]
    B --> C[Sort fields by step, sequence]
    C --> D[Initialize field states]

    D --> E{For each field}
    E --> F[Get current value from inputs]
    F --> G[Apply VISIBILITY rules]
    G --> H{Is visible?}

    H -->|No| I[Mark hidden, skip remaining rules]
    H -->|Yes| J[Apply AVAILABILITY rules]

    J --> K[Filter available values]
    K --> L[Apply EDITABILITY rules]
    L --> M[Apply MANDATORY rules]
    M --> N[Apply VALIDATION rules]

    N --> O[Collect errors if any]
    O --> P[Store field state]
    P --> E

    E -->|Done| Q[Calculate is_complete]
    Q --> R[Generate SKU if configured]
    R --> S[Return calculation result]

    I --> P
```

---

## API Overview

Full interactive documentation available at `/docs` (Swagger UI) or `/redoc` when running.

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/token` | Login, returns access + refresh tokens |
| POST | `/auth/refresh` | Refresh access token |

### Entities & Versions
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/entities` | List entities |
| POST | `/entities` | Create entity |
| GET | `/versions?entity_id={id}` | List versions for entity |
| POST | `/versions` | Create DRAFT version |
| POST | `/versions/{id}/publish` | Publish version |
| POST | `/versions/{id}/clone` | Deep clone version |

### Fields, Values & Rules
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/fields?entity_version_id={id}` | List fields |
| POST | `/fields` | Create field (DRAFT only) |
| GET | `/values?field_id={id}` | List values for field |
| POST | `/values` | Create value (DRAFT only) |
| GET | `/rules?entity_version_id={id}` | List rules |
| POST | `/rules` | Create rule (DRAFT only) |

### Configurations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/configurations` | List user's configurations |
| POST | `/configurations` | Create configuration |
| PATCH | `/configurations/{id}` | Update inputs (DRAFT only) |
| GET | `/configurations/{id}/calculate` | Recalculate with current inputs |
| POST | `/configurations/{id}/clone` | Clone to new DRAFT |
| POST | `/configurations/{id}/upgrade` | Upgrade to latest version |
| POST | `/configurations/{id}/finalize` | Make immutable |

### Engine
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/engine/calculate` | Stateless calculation |

---

## Testing

The project includes 370+ tests across multiple categories:

| Category | Location | Description |
|----------|----------|-------------|
| API Tests | `tests/api/` | All CRUD operations, RBAC, lifecycle |
| Engine Tests | `tests/engine/` | Rule evaluation, operators, SKU |
| Integration | `tests/integration/` | End-to-end workflows |
| Performance | `tests/performance/` | Benchmarks |
| Stress | `tests/stress/` | Concurrency, race conditions |

```bash
# Run with verbose output
pytest -v

# Run specific test file
pytest tests/engine/test_sku_generation.py

# Run tests matching pattern
pytest -k "configuration and lifecycle"
```

See [docs/TESTING.md](docs/TESTING.md) for detailed test documentation.

---

## Design Decisions

### Intentional Scope Boundaries

This project focuses on core rule engine functionality. The following features are intentionally omitted:

| Feature | Status | Rationale |
|---------|--------|-----------|
| Redis caching | Not implemented | Premature optimization; PostgreSQL handles expected scale. Easy to add if needed. |
| Multi-tenancy | Not implemented | Adds significant complexity (tenant isolation, cross-tenant queries) without demonstrating new architectural patterns. |
| API versioning (v1/v2) | Not implemented | Single version appropriate for greenfield project. Versioning adds overhead best introduced when breaking changes are needed. |
| Internationalization | Deferred | See [ADR: i18n](docs/ADR_I18N.md). JSONB approach documented for future implementation. |
| GraphQL | Not implemented | REST is sufficient for this domain. GraphQL adds complexity without clear benefit for CPQ use case. |
| Event sourcing | Not implemented | Current state storage is simpler and sufficient. Audit trail via `AuditMixin` covers basic needs. |

### Key Architectural Choices

**Re-hydration strategy for configurations**: Configurations store raw inputs as JSON (`data` field) rather than denormalized snapshots. On read, the engine re-evaluates rules against the current EntityVersion schema. This enables version upgrades and ensures consistency.

**DRAFT-only editing**: Fields, Values, and Rules can only be modified on DRAFT versions. This prevents accidental changes to production configurations and ensures published versions are stable.

**Soft delete for FINALIZED**: Finalized configurations cannot be hard-deleted (except by ADMIN). This preserves audit trails for legal/compliance scenarios (e.g., issued quotes, submitted orders).

**UUID for configurations**: Configurations use UUID primary keys for secure external sharing (URLs that can't be guessed).

---

## Project Structure

```
rule_engine/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── database.py          # SQLAlchemy session management
│   ├── dependencies.py      # Dependency injection
│   ├── exceptions.py        # Custom exceptions
│   ├── models/
│   │   └── domain.py        # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response schemas
│   ├── routers/             # API endpoint handlers
│   ├── services/            # Business logic layer
│   │   ├── rule_engine.py   # Core calculation engine
│   │   ├── versioning.py    # Version lifecycle management
│   │   ├── auth.py          # Authentication logic
│   │   └── users.py         # User management
│   └── core/
│       ├── config.py        # Environment configuration
│       ├── security.py      # JWT, password hashing
│       └── rate_limit.py    # Rate limiting setup
├── alembic/                 # Database migrations
├── tests/                   # Test suite
├── docs/                    # Additional documentation
├── docker-compose.yml       # Development environment
├── Dockerfile               # Container image
└── requirements.txt         # Python dependencies
```

---

## Documentation

- [Testing Guide](docs/TESTING.md) - Test organization and running instructions
- [Security Features](docs/SECURITY_FEATURES.md) - Authentication and rate limiting
- [Token Rotation Demo](docs/ROTATION_DEMO.md) - Refresh token rotation examples
- [ADR: Internationalization](docs/ADR_I18N.md) - i18n architecture decision

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
