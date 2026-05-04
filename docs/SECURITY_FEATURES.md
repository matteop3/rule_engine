# Security Features Documentation

This document describes the security enhancements implemented in the Rule Engine API.

## 🔄 Refresh Token Mechanism

### Overview

The refresh token mechanism provides a secure way to maintain user sessions without requiring frequent re-authentication. It implements a two-token system:

- **Access Token**: Short-lived JWT (30 minutes default) used for API requests
- **Refresh Token**: Long-lived token (7 days default) used ONLY to obtain new access tokens

### Benefits

✅ **Security**: Compromised access tokens expire quickly (30 min)
✅ **User Experience**: Users don't need to re-login every 30 minutes
✅ **Revocation**: Individual refresh tokens can be revoked for security incidents
✅ **Audit Trail**: Token usage is tracked (last_used_at, user_agent, IP address)

### How It Works

#### 1. Initial Login

```bash
POST /auth/token
Content-Type: application/x-www-form-urlencoded

username=user@example.com&password=SecurePass123!
```

**Response:**
```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "a1b2c3d4...",
  "token_type": "bearer"
}
```

#### 2. Using Access Token

```bash
GET /api/v1/entities
Authorization: Bearer eyJhbG...
```

#### 3. When Access Token Expires (after 30 min)

```bash
GET /api/v1/entities
Authorization: Bearer eyJhbG...

# Response: 401 Unauthorized
```

#### 4. Refresh Access Token

```bash
POST /auth/refresh
Authorization: Bearer a1b2c3d4...
```

**Response:**
```json
{
  "access_token": "eyJuZX...",
  "token_type": "bearer"
}
```

#### 5. Continue with New Access Token

```bash
GET /api/v1/entities
Authorization: Bearer eyJuZX...

# Response: 200 OK
```

### Database Schema

Refresh tokens are stored in the `refresh_tokens` table:

```sql
CREATE TABLE refresh_tokens (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT 0,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    user_agent VARCHAR(500),
    ip_address VARCHAR(45),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Security Features

1. **Token Hashing**: Refresh tokens are stored as SHA-256 hashes (never plaintext)
2. **Expiration**: Tokens automatically expire after 7 days
3. **Revocation**: Tokens can be revoked individually or all at once per user
4. **Audit Trail**: Tracks when tokens are created, used, and from which IP/user agent
5. **Validation**: Multiple checks (exists, not revoked, not expired, hash matches)

### Configuration

In `.env`:

```bash
# Refresh token expiration (in days)
REFRESH_TOKEN_EXPIRE_DAYS=7
```

### Token Rotation (Configurable)

For enhanced security, you can enable refresh token rotation. This creates a new refresh token each time you use the old one (and revokes the old one).

#### Enable Token Rotation

Simply set this in your `.env` file:

```bash
# Enable refresh token rotation (recommended for production)
REFRESH_TOKEN_ROTATION=true
```

#### How It Works

**With Rotation Disabled (default):**
```bash
POST /auth/refresh
Authorization: Bearer <refresh_token>

# Response:
{
  "access_token": "new_access_token",
  "token_type": "bearer"
}
# Same refresh token continues to work until expiration
```

**With Rotation Enabled:**
```bash
POST /auth/refresh
Authorization: Bearer <old_refresh_token>

# Response:
{
  "access_token": "new_access_token",
  "refresh_token": "new_refresh_token",  # NEW token returned!
  "token_type": "bearer"
}
# Old refresh token is now revoked and cannot be reused
```

The revoke of the old token and the creation of the new one run in a single
database transaction, so a rotation either fully succeeds or fully rolls back —
the caller never ends up with no valid refresh token.

#### When to Enable Rotation

✅ **Enable (REFRESH_TOKEN_ROTATION=true) if:**
- High security requirements (banking, healthcare, etc.)
- Single device per user (mobile app)
- Can handle client-side token updates
- Want maximum protection against token theft

❌ **Keep Disabled (REFRESH_TOKEN_ROTATION=false) if:**
- Multiple devices/tabs per user
- Simpler client implementation needed
- Lower security requirements
- Development/testing environment

### Management Functions

The `AuthService` provides several management functions:

```python
# Revoke a specific token
auth_service.revoke_refresh_token(db, token_id)

# Revoke all tokens for a user (logout from all devices)
auth_service.revoke_all_user_refresh_tokens(db, user_id)

# Clean up expired tokens (run periodically)
auth_service.cleanup_expired_tokens(db)
```

---

## 🚦 Rate Limiting

### Overview

Rate limiting prevents abuse and brute force attacks by limiting the number of requests a client can make within a time window.

### Protection Against

🛡️ **Brute Force Attacks**: Limits password guessing attempts
🛡️ **DDoS Attacks**: Prevents overwhelming the server
🛡️ **API Abuse**: Protects against excessive usage

### Rate Limits

#### Login Endpoint (`/auth/token`)

- **Limit**: 5 attempts per 15 minutes per IP
- **Purpose**: Prevent brute force password attacks

```bash
# After 5 failed attempts:
POST /auth/token

Response: 429 Too Many Requests
{
  "error": "rate_limit_exceeded",
  "detail": "Too many requests. Please try again later.",
  "retry_after": null
}
```

#### Refresh Endpoint (`/auth/refresh`)

- **Limit**: 10 attempts per 5 minutes per IP
- **Purpose**: Prevent refresh token abuse

#### General API Endpoints

- **Limit**: 60 requests per minute per IP (can be applied to specific endpoints)
- **Purpose**: Prevent API abuse

### Configuration

In `.env`:

```bash
# Enable/disable rate limiting
RATE_LIMIT_ENABLED=true

# Login endpoint limits
RATE_LIMIT_LOGIN_ATTEMPTS=5
RATE_LIMIT_LOGIN_WINDOW_MINUTES=15

# Refresh endpoint limits
RATE_LIMIT_REFRESH_ATTEMPTS=10
RATE_LIMIT_REFRESH_WINDOW_MINUTES=5

# General API limit
RATE_LIMIT_API_PER_MINUTE=60

# Refresh token rotation
REFRESH_TOKEN_ROTATION=false
```

### Implementation Details

Rate limiting is implemented using [slowapi](https://github.com/laurents/slowapi), which provides:

- **In-memory storage**: Simple, fast, single-instance (default)
- **Redis support**: For production multi-instance deployments
- **Per-IP tracking**: Limits based on client IP address
- **Customizable**: Can be extended to track by user ID, API key, etc.

### Applying to Custom Endpoints

To apply rate limiting to your own endpoints:

```python
from app.core.rate_limit import limiter

@router.get("/my-endpoint")
@limiter.limit("10/minute")  # 10 requests per minute
async def my_endpoint(request: Request):
    return {"message": "Hello"}
```

### Production Considerations

For production deployments with multiple instances, consider using Redis:

```python
# In app/core/rate_limit.py
limiter = Limiter(
    key_func=get_client_identifier,
    storage_uri="redis://localhost:6379",  # Use Redis instead of memory://
)
```

### Monitoring

Rate limit events are logged:

```
WARNING: Rate limit exceeded for 192.168.1.100 on endpoint /auth/token
```

---

## 🛡️ BOM Endpoint Access Control

### Overview

BOM Item and BOM Item Rule endpoints follow the same RBAC model as Fields, Values, and Rules:

| Role | BOM Item CRUD | BOM Item Rule CRUD | Read |
|------|--------------|-------------------|------|
| **ADMIN** | Full access | Full access | All versions |
| **AUTHOR** | Full access | Full access | All versions |
| **USER** | Denied (HTTP 403) | Denied (HTTP 403) | Via engine only |

### Additional Constraints

- **DRAFT-only**: BOM items and rules can only be created, updated, or deleted on DRAFT versions (HTTP 409 for PUBLISHED/ARCHIVED)
- **COMMERCIAL-is-root**: COMMERCIAL BOM items cannot have a parent (HTTP 400)
- **Price consistency**: COMMERCIAL items with the same `part_number` in the same version must have identical `unit_price` (HTTP 409)
- **Pricing by type**: TECHNICAL items reject `unit_price`; COMMERCIAL items require it (HTTP 400)

---

## 🔍 Request Tracing (X-Request-ID)

### Overview

Every HTTP request is assigned a unique correlation ID (`X-Request-ID`) via middleware. This ID is:

- **Generated automatically** as a UUID4, or **propagated** from a client-supplied `X-Request-ID` header
- **Injected into every log record** via a `contextvars`-based logging filter
- **Echoed back** in the response headers for client-side correlation

### Security Relevance

Request correlation IDs are essential for:

- **Incident investigation**: Trace all log entries related to a specific request
- **Audit trail correlation**: Link application events to specific API calls
- **Abuse detection**: Correlate rate-limited or suspicious requests across log aggregation systems
- **Support workflows**: Users can report the `X-Request-ID` from a failed response for fast log lookup

### Example

```bash
# Request
curl -v http://localhost:8000/entities

# Response header
< X-Request-ID: 3f2504e0-4f89-11d3-9a0c-0305e82c3301

# Corresponding log line (JSON mode)
{"asctime": "2025-01-15T10:30:00", "levelname": "INFO", "name": "app.routers.entities",
 "message": "Listing entities", "request_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301"}
```

---

## 🧪 Testing

### Manual Testing

1. **Start the server:**
   ```bash
   source venv/bin/activate
   uvicorn app.main:app --reload
   ```

2. **Run the test script:**
   ```bash
   python test_refresh_and_rate_limit.py
   ```

### Test Cases

The test script verifies:

1. ✓ Login returns both access and refresh tokens
2. ✓ Refresh endpoint successfully generates new access token
3. ✓ Login rate limiting triggers after 5 attempts
4. ✓ Refresh rate limiting triggers after 10 attempts

---

## 📋 Migration Guide

### For Existing Databases

If you already have a database, run the migration:

```bash
source venv/bin/activate
python migrations/migrate.py
```

This will create the `refresh_tokens` table without affecting existing data.

### For New Deployments

The table will be created automatically when the application starts (via `Base.metadata.create_all()`).

---

## 🔐 Best Practices

### 1. Token Storage (Client-Side)

- **Access Token**: Can be stored in memory or sessionStorage
- **Refresh Token**: Should be stored in httpOnly cookies (most secure) or secure storage

### 2. Token Rotation

Consider enabling refresh token rotation for maximum security (see Optional section above).

### 3. Revocation on Security Events

Revoke all tokens when:
- User changes password
- User reports suspicious activity
- Account is compromised

```python
# Revoke all tokens for a user
auth_service.revoke_all_user_refresh_tokens(db, user_id)
```

### 4. Periodic Cleanup

Set up a cron job to clean expired tokens:

```bash
# Daily at 3 AM
0 3 * * * cd /path/to/project && python -c "from app.services.auth import AuthService; from app.database import get_db; db = next(get_db()); AuthService().cleanup_expired_tokens(db)"
```

### 5. Rate Limit Configuration

Adjust rate limits based on your use case:
- **Public APIs**: Stricter limits (5-10 req/min)
- **Internal APIs**: Looser limits (100+ req/min)
- **Authenticated users**: Can have higher limits than anonymous

### 6. Production Deployment

For production with multiple instances:
1. Use Redis for rate limiting storage
2. Enable refresh token rotation
3. Set up monitoring and alerting
4. Use secure httpOnly cookies for refresh tokens
5. Implement proper logging and audit trails

---

## 📚 Additional Resources

- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [slowapi Documentation](https://github.com/laurents/slowapi)

---

## 🐛 Troubleshooting

### Issue: Rate limiting not working

**Solution:**
1. Check `RATE_LIMIT_ENABLED=true` in `.env`
2. Restart the server after config changes
3. Verify slowapi is installed: `pip list | grep slowapi`

### Issue: Refresh token always returns 401

**Solution:**
1. Check token hasn't expired (7 days default)
2. Verify token wasn't revoked
3. Check database connection
4. Look at server logs for specific error

### Issue: "Token hash mismatch" error

**Solution:**
This indicates potential security issue or corruption. Token should be regenerated:
1. User should logout and login again
2. If persistent, check database integrity

---

## ✅ Summary

1. ✅ **Refresh Token Mechanism**
   - Two-token system (access + refresh)
   - Secure storage with hashing
   - Revocation support
   - Audit trail

2. ✅ **Rate Limiting**
   - Login endpoint protection (5/15min)
   - Refresh endpoint protection (10/5min)
   - Customizable limits
   - Easy to extend to other endpoints

Both features are production-ready and follow security best practices!