# Token Rotation Demo

## Scenario Comparison

### ❌ Without Rotation (REFRESH_TOKEN_ROTATION=false)

```bash
# 1. Login
POST /auth/token
Response: {
  "access_token": "abc123",
  "refresh_token": "xyz789",
  "token_type": "bearer"
}

# 2. After 30 minutes, refresh
POST /auth/refresh
Authorization: Bearer xyz789
Response: {
  "access_token": "def456",
  "token_type": "bearer"
}

# 3. 30 minutes later, refresh AGAIN with SAME token
POST /auth/refresh
Authorization: Bearer xyz789  # ✅ SAME token still works!
Response: {
  "access_token": "ghi789",
  "token_type": "bearer"
}

# Token "xyz789" remains valid for 7 days
```

**Client Implementation (Simple):**
```javascript
// Store once
localStorage.setItem('refresh_token', 'xyz789');

// Use multiple times without updating
async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  const response = await fetch('/auth/refresh', {
    headers: { 'Authorization': `Bearer ${refreshToken}` }
  });
  const data = await response.json();
  localStorage.setItem('access_token', data.access_token);
  // No need to update refresh_token!
}
```

---

### ✅ With Rotation (REFRESH_TOKEN_ROTATION=true)

```bash
# 1. Login
POST /auth/token
Response: {
  "access_token": "abc123",
  "refresh_token": "xyz789",
  "token_type": "bearer"
}

# 2. After 30 minutes, refresh
POST /auth/refresh
Authorization: Bearer xyz789
Response: {
  "access_token": "def456",
  "refresh_token": "aaa111",  # 🔄 NEW refresh token!
  "token_type": "bearer"
}
# Old token "xyz789" is now REVOKED

# 3. 30 minutes later, try to use OLD token
POST /auth/refresh
Authorization: Bearer xyz789  # ❌ OLD token - FAILS!
Response: 401 Unauthorized {
  "detail": "Invalid or expired refresh token"
}

# 4. Use NEW token instead
POST /auth/refresh
Authorization: Bearer aaa111  # ✅ NEW token works!
Response: {
  "access_token": "ghi789",
  "refresh_token": "bbb222",  # 🔄 Another NEW token!
  "token_type": "bearer"
}
```

**Client Implementation (More Complex):**
```javascript
// Store initially
localStorage.setItem('refresh_token', 'xyz789');

// Update on every refresh!
async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  const response = await fetch('/auth/refresh', {
    headers: { 'Authorization': `Bearer ${refreshToken}` }
  });
  const data = await response.json();

  // IMPORTANT: Update BOTH tokens!
  localStorage.setItem('access_token', data.access_token);
  if (data.refresh_token) {
    localStorage.setItem('refresh_token', data.refresh_token);
  }
}
```

---

## Security Implications

### Without Rotation

**If token is stolen:**
```
Attacker steals refresh token "xyz789"
↓
Attacker can use it for up to 7 days
↓
Legitimate user also uses it (works fine)
↓
No way to detect the theft!
```

### With Rotation

**If token is stolen:**
```
User has token "xyz789"
↓
Attacker steals "xyz789" and uses it first
  → Gets new token "aaa111" (user's token now invalid)
↓
User tries to use "xyz789"
  → FAILS with 401!
↓
You detect suspicious activity:
  - User reports "logged out unexpectedly"
  - Server sees old token reuse attempt
  - Revoke all user tokens immediately
  - Force user to re-login
```

**Detection mechanism:**
```python
# In verify_user_refresh_token():
if db_token.is_revoked:
    # This should only happen if:
    # 1. Token was rotated and someone tries to reuse old one
    # 2. Token was manually revoked

    logger.warning(
        f"SECURITY: Revoked token reuse attempt! "
        f"Token {db_token.id} for user {db_token.user_id}"
    )

    # Consider: Revoke ALL user tokens as precaution
    # auth_service.revoke_all_user_refresh_tokens(db, db_token.user_id)

    return None
```

---

## Trade-offs Summary

| Aspect | Without Rotation | With Rotation |
|--------|-----------------|---------------|
| **Security** | 🟡 Good | 🟢 Excellent |
| **Client Complexity** | 🟢 Simple | 🟡 Moderate |
| **Multi-Tab Support** | 🟢 Easy | 🔴 Difficult |
| **Token Theft Detection** | 🔴 No | 🟢 Yes |
| **Mobile App** | 🟢 Perfect | 🟢 Perfect |
| **Web App (Multi-Tab)** | 🟢 Perfect | 🟡 Needs sync |

---

## Recommendation

### Use Rotation (REFRESH_TOKEN_ROTATION=true) for:
- 🏦 Banking/Financial apps
- 🏥 Healthcare apps
- 📱 Native mobile apps
- 🎯 Single-device usage
- 🔒 High-security requirements

### Don't Use Rotation (REFRESH_TOKEN_ROTATION=false) for:
- 🌐 Multi-tab web apps
- 👥 Shared device usage
- 🎮 Gaming platforms
- 📊 Analytics dashboards
- 🧪 Development environments

---

## Testing Both Modes

```bash
# Test without rotation
echo "REFRESH_TOKEN_ROTATION=false" >> .env
uvicorn app.main:app --reload

# Test with rotation
echo "REFRESH_TOKEN_ROTATION=true" >> .env
uvicorn app.main:app --reload
```

Use the test script to verify behavior:
```bash
python tests/test_refresh_and_rate_limit.py
```
