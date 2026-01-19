# ADR: Internationalization (i18n) for User-Facing Text Fields

## Status

**Deferred**

## Context

Several domain models contain text fields intended for end-user display:

| Model | Field | Purpose |
|-------|-------|---------|
| Entity | `description` | Entity description shown in UI |
| Field | `label` | Display label for configuration fields |
| Value | `label` | Display label for selectable options |
| Rule | `description` | Human-readable rule explanation |
| Rule | `error_message` | Validation error shown to users |

In a real-world scenario, users may need to see these texts in their preferred language (e.g., Italian, English, German). This raises the question of whether to implement internationalization support.

## Decision

Internationalization is **not implemented** in the current version.

If required in the future, the recommended approach is **I18nString (JSONB)**: storing translations as a JSON object where keys are language codes.

```json
{
  "en": "Color",
  "it": "Colore",
  "de": "Farbe"
}
```

## Rationale

### Why defer?

1. **No concrete requirement**: There is no immediate use case requiring multi-language support.
2. **YAGNI principle**: Adding i18n now would introduce complexity without delivering value.
3. **Low migration cost**: Converting `String` columns to `JSONB` is straightforward if needed later.

### Why I18nString (JSONB) when implemented?

This approach was evaluated against alternatives:

| Approach | Pros | Cons |
|----------|------|------|
| **I18nString (JSONB)** | Simple, no JOINs, atomic reads, flexible | Less efficient per-language queries |
| **Translation table** | Normalized, workflow support | Complex JOINs, N+1 risk, slower reads |
| **Separate columns** | Type-safe, fast queries | Migration per language, not scalable |

For a configurator/rule engine, the typical access pattern is loading an entire `EntityVersion` with all fields, values, and rules. The frontend then selects the appropriate language. This pattern aligns well with JSONB: one query returns everything, and the client picks the language.

## Implementation Notes (for future reference)

### Schema change

```python
# Before
label: Mapped[str] = mapped_column(String(255))

# After
label: Mapped[dict] = mapped_column(JSON, default={"en": ""})
```

### Pydantic schema

```python
class I18nString(BaseModel):
    en: str
    it: str | None = None
    # Add languages as needed

    def get(self, lang: str, fallback: str = "en") -> str:
        return getattr(self, lang, None) or getattr(self, fallback) or ""
```

### API behavior

Return the full JSON object; let the client select the language:

```json
{
  "label": {"en": "Color", "it": "Colore"}
}
```

### Fallback strategy

If a translation is missing, fall back to English (`en`) as the default language.

### Checklist for implementers

If implementing i18n in the future:

- [ ] Update domain models and create database migration
- [ ] Update Pydantic schemas for API input/output
- [ ] Update seed data and fixtures
- [ ] Add/update tests covering multi-language scenarios
- [ ] Update project README with i18n usage documentation

## Consequences

- Text fields remain simple strings, keeping the codebase lean.
- Adopters needing i18n can implement it following this ADR.
- No additional validation, migration, or API complexity is introduced at this stage.
