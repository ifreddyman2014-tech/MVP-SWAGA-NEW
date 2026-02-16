# Database Migrations

This directory contains SQL migration scripts for the SWAGA VPN database.

## How to apply migrations

### Using Docker:
```bash
docker exec -i swaga_postgres psql -U swaga_user -d swaga < migrations/add_location_to_servers.sql
```

### Using psql directly:
```bash
psql -h localhost -U swaga_user -d swaga -f migrations/add_location_to_servers.sql
```

## Available migrations

### add_location_to_servers.sql
**Purpose:** Fixes "transport method cannot be empty" error

**Changes:**
- Adds `location` field to `servers` table
- Sets default values for `network_type`, `security`, `flow`, `fingerprint`, and `spider_x`
- Ensures no critical fields are empty

**When to run:** If you're experiencing subscription activation errors or missing server fields.

## Verification

After running migrations, verify the changes:
```sql
SELECT id, name, location, network_type, security, flow FROM servers;
```

All servers should have non-empty values for these fields.
