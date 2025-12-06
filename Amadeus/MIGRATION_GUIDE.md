# Database Migration Guide

## Overview

The Amadeus AI Assistant uses Alembic for database migrations, allowing you to version control and apply database schema changes safely.

## Setup

### 1. Install Alembic

```bash
pip install alembic
```

### 2. Initialize Migrations (First Time Only)

If migrations haven't been initialized yet:

```bash
cd Amadeus
alembic init migrations
```

This creates the migration directory structure.

## Creating Migrations

### Auto-generate Migration from Models

```bash
alembic revision --autogenerate -m "Description of changes"
```

This will:
- Compare current models with database schema
- Generate migration script automatically
- Create a new file in `migrations/versions/`

### Manual Migration

```bash
alembic revision -m "Description of changes"
```

Then edit the generated file to add your migration logic.

## Applying Migrations

### Apply All Pending Migrations

```bash
alembic upgrade head
```

### Apply Specific Migration

```bash
alembic upgrade <revision_id>
```

### Rollback Migration

```bash
alembic downgrade -1  # Rollback one version
alembic downgrade <revision_id>  # Rollback to specific version
```

## Migration Workflow

### 1. Make Model Changes

Edit `models.py` to add/modify tables or columns.

### 2. Generate Migration

```bash
alembic revision --autogenerate -m "Add new field to Task model"
```

### 3. Review Generated Migration

Check the generated file in `migrations/versions/`:
- Verify the changes are correct
- Add any data migrations if needed
- Test the migration on a copy of production data

### 4. Apply Migration

```bash
alembic upgrade head
```

### 5. Test

Run your test suite to ensure everything works:
```bash
pytest tests/
```

## Example: Adding an Index

### 1. Update Model

```python
# In models.py
class Task(Base):
    # ... existing fields ...
    priority = Column(Integer, index=True)  # Add indexed field
```

### 2. Generate Migration

```bash
alembic revision --autogenerate -m "Add priority index to tasks"
```

### 3. Review and Apply

```bash
# Review the generated migration file
# Then apply it
alembic upgrade head
```

## Best Practices

1. **Always Review**: Review auto-generated migrations before applying
2. **Test First**: Test migrations on a copy of production data
3. **Backup**: Backup database before applying migrations
4. **One Change Per Migration**: Keep migrations focused and atomic
5. **Descriptive Names**: Use clear, descriptive migration names
6. **Version Control**: Commit migration files to version control

## Troubleshooting

### Migration Conflicts

If you have conflicts:
```bash
# Check current revision
alembic current

# Check migration history
alembic history

# Resolve conflicts manually
```

### Database Out of Sync

If database is out of sync:
```bash
# Stamp database to current revision (if schema matches)
alembic stamp head

# Or create a new migration to sync
alembic revision --autogenerate -m "Sync database schema"
```

## Environment Variables

Migration settings can be configured via environment variables:
- `AMADEUS_DB_FILE`: Database file path
- `DB_ECHO`: Enable SQL logging (true/false)

## Production Deployment

### Pre-deployment Checklist

1. Backup production database
2. Test migration on staging environment
3. Review migration script
4. Schedule maintenance window if needed
5. Apply migration: `alembic upgrade head`
6. Verify application functionality
7. Monitor for errors

### Rollback Plan

Always have a rollback plan:
```bash
# If issues occur, rollback immediately
alembic downgrade -1
```

## Current Database Schema

The current schema includes:

- **tasks**: Tasks with status, created_at, completed_at (indexed)
- **notes**: Notes with title, content, tags (indexed)
- **reminders**: Reminders with status, time, created_at (indexed)

All tables have proper indexes for common query patterns.

