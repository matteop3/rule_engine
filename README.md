# Rule Engine

A headless, API-first rule engine for building product configurators (CPQ systems). Define entities with versioned schemas, configurable fields, and dynamic business rules that control visibility, availability, validation, and more.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/matteop3/rule_engine/actions/workflows/ci.yml/badge.svg)](https://github.com/matteop3/rule_engine/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/matteop3/rule_engine/branch/main/graph/badge.svg)](https://codecov.io/gh/matteop3/rule_engine)

---

## The Problem

Product configurators are complex. A laptop configurator needs to:
- Show/hide fields based on selections (GPU options only for "Pro" models)
- Force field values based on conditions (Enterprise chassis forces cooling = "Passive")
- Filter available values dynamically (16GB RAM unavailable with entry-level CPU)
- Validate combinations (Pro GPU not allowed with Compact chassis)
- Generate SKU codes from selections (LPT-PRO-16G-512S)
- Support version management (draft v2 while v1 is live)
- Track configuration lifecycle (draft → finalized)

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
- **6 rule types**: Visibility, Calculation, Availability, Editability, Mandatory, Validation
- **Waterfall evaluation**: Rules processed in field order with cascading effects
- **Operator support**: Equals, NotEquals, GreaterThan, GreaterThanOrEqual, LessThan, LessThanOrEqual, In
- **Cascading dropdowns**: Field B options filter based on Field A selection

### Version Management
- **Lifecycle states**: DRAFT → PUBLISHED → ARCHIVED
- **Single published version**: Publishing auto-archives the previous version
- **Deep cloning**: Clone versions with all fields, values, rules, and BOM data
- **DRAFT-only editing**: Published/archived versions are immutable

### Configuration Lifecycle
- **DRAFT configurations**: Mutable, upgradeable to newer entity versions
- **FINALIZED configurations**: Immutable snapshots for legal/audit purposes (requires completeness)
- **Clone & upgrade**: Fork configurations or migrate to latest schema
- **Soft delete**: Preserve audit trail for finalized records

### Security & Auth
- **JWT authentication**: Short-lived access tokens (30 min default)
- **Refresh token rotation**: Optional security hardening
- **Role-based access**: ADMIN, AUTHOR, USER with granular permissions
- **Rate limiting**: Configurable limits on auth endpoints

### BOM Generation
- **Technical BOM**: Hierarchical component list with sub-assemblies (manufacturing/assembly)
- **Commercial BOM**: Flat priced line items for quotes and invoices
- **Conditional inclusion**: BOM items included/excluded based on field conditions (OR logic across rules)
- **Dynamic quantities**: Resolve from numeric field values or use static defaults
- **Line totals & aggregation**: Auto-computed `line_total` and `commercial_total` with part-number aggregation

### SKU Generation
- **Base SKU + modifiers**: `LPT-PRO` + `-16G` + `-512S` → `LPT-PRO-16G-512S`
- **Custom delimiters**: Configure separator per entity version
- **Visibility-aware**: Hidden fields excluded from SKU
- **Free-value support**: Append modifier when text field is filled

### Performance
- **Version data caching**: PUBLISHED EntityVersion data cached in-memory with configurable TTL
- **Safe by design**: Only immutable PUBLISHED versions are cached; DRAFT versions always hit the database
- **Observable**: Hit/miss counters available via `cache.stats()` for monitoring effectiveness
- **Auto-eviction**: TTL-based expiry + max size limit prevent unbounded memory growth

### Observability
- **Structured JSON logging**: All log output (application + uvicorn) in machine-parseable JSON
- **Request correlation**: Every request gets a unique `X-Request-ID` header, propagated through all log entries
- **Configurable format**: JSON (production) or human-readable (development) via `LOG_JSON` setting

### Example

```bash
POST /engine/calculate
```
```json
{
  "entity_id": 1,
  "current_state": [
    {"field_id": 1, "value": "Pro"},
    {"field_id": 2, "value": "16GB"}
  ]
}
```

```jsonc
{
  "entity_id": 1,
  "is_complete": false,
  "generated_sku": "LPT-PRO-16G",
  "fields": [
    {
      "field_id": 1,
      "field_name": "product_type",
      "field_label": "Product Type",
      "current_value": "Pro",
      "available_options": [
        {"id": 1, "value": "Standard", "label": "Standard", "is_default": true},
        {"id": 2, "value": "Pro", "label": "Pro", "is_default": false}
      ],
      "is_required": true,
      "is_readonly": false,
      "is_hidden": false,
      "error_message": null
    }
    // ... ram, gpu, etc.
  ]
}
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI 0.100+ |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Validation | Pydantic 2.0 |
| Auth | python-jose (JWT) + bcrypt |
| Rate Limiting | slowapi |
| Testing | pytest + testcontainers |
| Observability | python-json-logger + correlation IDs |
| Infrastructure | Docker + Docker Compose |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- (Optional) Python 3.11+ for local development

### Run with Docker

```bash
# Clone the repository
git clone https://github.com/matteop3/rule-engine.git
cd rule-engine

# Create environment file
cp .env.example .env

# Start services
make build          # or: docker compose up --build -d

# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs

# See all available commands
make help
```

### Load Demo Data

The project includes a seed script that populates the database with a realistic insurance configurator scenario, covering all engine features:

```bash
# With the database running:
python seed_data.py
```

This creates:

| Resource | Count | Details |
|----------|-------|---------|
| Entity + Version | 1 | "Auto Insurance Gold" with SKU generation |
| Fields | 15 | 4 steps, all data types (string, number, boolean, date) |
| Values | 35 | With SKU modifiers |
| Rules | 19 | All 6 rule types, all 7 operators |
| BOM Items | 8 | 5 TECHNICAL (incl. hierarchy) + 3 COMMERCIAL (with pricing) |
| BOM Rules | 4 | Conditional inclusion, OR logic |
| Users | 3 | One per role (see below) |
| Configurations | 3 | 1 finalized + 2 drafts |

**Demo users** (password: `password123`):

| Email | Role | Permissions |
|-------|------|-------------|
| `admin@demo.com` | ADMIN | Full access, soft delete finalized configs |
| `author@demo.com` | AUTHOR | Create/edit entities, fields, rules |
| `user@demo.com` | USER | Create/edit configurations |

**Try it out** — get a token and call the engine:

```bash
# Login
curl -X POST http://localhost:8000/auth/token \
  -d "username=user@demo.com&password=password123"

# Calculate state (stateless, auth required)
curl -X POST http://localhost:8000/engine/calculate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"entity_id": 1, "current_state": [
    {"field_id": 1, "value": "John Doe"},
    {"field_id": 2, "value": "1990-01-01"},
    {"field_id": 3, "value": "EMPLOYEE"},
    {"field_id": 4, "value": "CAR"},
    {"field_id": 5, "value": 25000}
  ]}'
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

# Logging
LOG_LEVEL=INFO
LOG_JSON=true            # Set to false for human-readable logs in development

# Caching
CACHE_TTL_SECONDS=300    # TTL for cached PUBLISHED version data
CACHE_MAX_SIZE=100       # Max cached versions in memory
```

---

## Architecture

### Domain Model

```mermaid
erDiagram
    Entity ||--o{ EntityVersion : "has versions"
    EntityVersion ||--o{ Field : "contains"
    EntityVersion ||--o{ Rule : "contains"
    EntityVersion ||--o{ BOMItem : "contains"
    EntityVersion ||--o{ Configuration : "used by"
    Field ||--o{ Value : "has options"
    Rule }o--|| Field : "targets"
    Rule }o--o| Value : "targets (optional)"
    BOMItem ||--o{ BOMItem : "has children"
    BOMItem ||--o{ BOMItemRule : "has rules"
    BOMItem }o--o| Field : "quantity from"
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
        enum rule_type "visibility|calculation|availability|editability|mandatory|validation"
        json conditions
        string error_message "nullable, VALIDATION only"
        string set_value "nullable, CALCULATION only"
    }

    BOMItem {
        int id PK
        int entity_version_id FK
        int parent_bom_item_id FK "nullable, self-ref"
        enum bom_type "TECHNICAL|COMMERCIAL"
        string part_number
        string description
        decimal quantity
        int quantity_from_field_id FK "nullable"
        decimal unit_price "nullable, COMMERCIAL only"
        int sequence
    }

    BOMItemRule {
        int id PK
        int bom_item_id FK
        int entity_version_id FK
        json conditions
        string description
    }

    Configuration {
        uuid id PK
        int entity_version_id FK
        uuid user_id FK
        string name
        enum status "DRAFT|FINALIZED"
        bool is_complete
        string generated_sku "nullable"
        decimal bom_total_price "nullable"
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
    DRAFT --> FINALIZED: Finalize (if complete)
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
    H -->|Yes| CA[Apply CALCULATION rules]

    CA --> CB{Is calculated?}
    CB -->|Yes| CC[Set forced value, mark readonly, skip to MANDATORY]
    CB -->|No| J[Apply EDITABILITY rules]

    J --> K[Apply AVAILABILITY rules]
    K --> L[Filter available values]
    L --> M[Apply MANDATORY rules]
    CC --> M
    M --> N[Apply VALIDATION rules]

    N --> O[Collect errors if any]
    O --> P[Store field state]
    P --> E

    E -->|Done| Q[Calculate is_complete]
    Q --> R[Generate SKU if configured]
    R --> BOM[Evaluate BOM: inclusion, quantities, totals]
    BOM --> S[Return calculation result]

    I --> P
```

### Key Architectural Choices

**Re-hydration strategy for configurations**: Configurations store raw inputs as JSON (`data` field) rather than denormalized snapshots. On read, the engine re-evaluates rules against the current EntityVersion schema. This enables version upgrades and ensures consistency. Key derived values (`is_complete`, `generated_sku`) are cached on the record for queryability. See [ADR: Re-hydration](docs/ADR_REHYDRATION.md).

**DRAFT-only editing**: Fields, Values, and Rules can only be modified on DRAFT versions. This prevents accidental changes to production configurations and ensures published versions are stable.

**Soft delete for FINALIZED**: Finalized configurations cannot be hard-deleted (except by ADMIN). This preserves audit trails for legal/compliance scenarios (e.g., issued quotes, submitted orders).

**UUID for configurations**: Configurations use UUID primary keys for secure external sharing (URLs that can't be guessed).

**In-memory caching for PUBLISHED versions**: PUBLISHED EntityVersion data (fields, values, rules)
is cached in-process as frozen dataclasses, decoupled from SQLAlchemy sessions. Only immutable
PUBLISHED versions are cached. The cache auto-invalidates on version archival and provides
hit/miss counters for observability.

**Structured logging with request correlation**: All application and uvicorn logs share a unified
JSON format (configurable to plain-text for development). Every request is tagged with a unique
`X-Request-ID` (auto-generated UUID4 or client-provided), injected into log records via
`contextvars` and echoed in the response headers for end-to-end traceability.

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

### BOM Items & BOM Item Rules
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/bom-items?entity_version_id={id}` | List BOM items |
| POST | `/bom-items` | Create BOM item (DRAFT only) |
| PATCH | `/bom-items/{id}` | Update BOM item (DRAFT only) |
| DELETE | `/bom-items/{id}` | Delete BOM item (DRAFT only) |
| GET | `/bom-item-rules?entity_version_id={id}` | List BOM item rules |
| POST | `/bom-item-rules` | Create BOM item rule (DRAFT only) |
| PATCH | `/bom-item-rules/{id}` | Update BOM item rule (DRAFT only) |
| DELETE | `/bom-item-rules/{id}` | Delete BOM item rule (DRAFT only) |

### Configurations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/configurations` | List user's configurations |
| POST | `/configurations` | Create configuration |
| PATCH | `/configurations/{id}` | Update inputs (DRAFT only) |
| GET | `/configurations/{id}/calculate` | Recalculate with current inputs |
| POST | `/configurations/{id}/clone` | Clone to new DRAFT |
| POST | `/configurations/{id}/upgrade` | Upgrade to latest version |
| POST | `/configurations/{id}/finalize` | Make immutable (requires completeness) |

### Engine
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/engine/calculate` | Stateless calculation |

---

## Testing

The project includes 975+ tests across multiple categories:

| Category | Location | Description |
|----------|----------|-------------|
| API Tests | `tests/api/` | CRUD operations, RBAC, lifecycle, input validation |
| Engine Tests | `tests/engine/` | Rule evaluation, operators, SKU, BOM edge cases, mutation kills |
| Integration | `tests/integration/` | End-to-end workflows, BOM lifecycle |
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
| Redis caching | In-memory TTL cache | PUBLISHED version data cached in-process. Redis not needed at current scale; upgrade path documented if multi-instance is needed. |
| API versioning (v1/v2) | Not implemented | Single version appropriate for greenfield project. Versioning adds overhead best introduced when breaking changes are needed. |
| Internationalization | Deferred | See [ADR: i18n](docs/ADR_I18N.md). JSONB approach documented for future implementation. |
| GraphQL | Not implemented | REST is sufficient for this domain. GraphQL adds complexity without clear benefit for CPQ use case. |
| Cross-field expressions | Not implemented | See [ADR: Rule Expressions](docs/ADR_RULE_EXPRESSIONS.md). Single-field conditions keep rules simple and declarative. |
| Inference tree evaluation | Not implemented | See [ADR: Inference Tree](docs/ADR_INFERENCE_TREE.md). Waterfall model is simpler and sufficient for typical CPQ scenarios. |
| Pagination metadata | Not implemented | List endpoints return plain arrays with a 100-record limit and `skip`/`limit` parameters, but no total count or `has_more` indicator. For fields and values this is adequate (CPQ domains typically have 10-30 fields and 5-15 values per field), while for entities, versions, configurations, and users the client must paginate blindly. If needed, pagination metadata could be added via HTTP headers (`X-Total-Count`, `X-Has-More`) to avoid breaking the response format. |

---

## Project Structure

```
rule_engine/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── database.py          # SQLAlchemy session management
│   ├── dependencies/          # Dependency injection (package)
│   │   ├── __init__.py        # Re-exports for backward compatibility
│   │   ├── auth.py            # Authentication & authorization deps
│   │   ├── services.py        # Service factories + transaction helper
│   │   ├── fetchers.py        # Data retrieval helpers
│   │   └── validators.py      # Business rule validation helpers
│   ├── middleware/
│   │   └── request_id.py     # Request correlation ID middleware
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
│       ├── cache.py         # In-memory TTL cache + cached data models
│       ├── logging.py       # Structured logging setup
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

- [OpenAPI Specification](openapi.json) - Full API spec (importable in Postman, Insomnia, etc.)
- [API Examples](api.http) - Ready-to-use API calls for VS Code REST Client
- [Testing Guide](docs/TESTING.md) - Test organization and running instructions
- [Security Features](docs/SECURITY_FEATURES.md) - Authentication and rate limiting
- [Token Rotation Demo](docs/ROTATION_DEMO.md) - Refresh token rotation examples
- [ADR: Internationalization](docs/ADR_I18N.md) - i18n architecture decision
- [ADR: Rule Expressions](docs/ADR_RULE_EXPRESSIONS.md) - Why rules use single-field conditions
- [ADR: Calculation Rules](docs/ADR_CALCULATION_RULES.md) - How CALCULATION rules derive field values
- [ADR: Inference Tree](docs/ADR_INFERENCE_TREE.md) - Why rules use waterfall evaluation instead of a dependency graph
- [ADR: Re-hydration](docs/ADR_REHYDRATION.md) - Why configurations store raw inputs and recalculate on read
- [ADR: BOM Generation](docs/ADR_BOM.md) - BOM design decisions (single table, hierarchy, pricing, aggregation)

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
