# Database Standards

## 1. Schema management

Production database schema changes MUST be represented as version-controlled migrations.

Engineers SHOULD NOT manually modify a production schema as the normal deployment process.

Migrations SHOULD be reproducible across supported environments.

## 2. Naming

Database objects SHOULD follow a consistent naming convention within a project.

Names SHOULD be descriptive and avoid ambiguous abbreviations.

Tables representing collections of domain entities SHOULD use a consistent singular or plural convention throughout the schema.

## 3. Primary keys

Application-owned relational tables SHOULD normally have a stable primary key.

The choice between integer and UUID-style identifiers depends on system requirements; there is no organization-wide requirement to use one format.

## 4. Foreign keys

Relational integrity SHOULD be enforced using foreign keys where appropriate.

Teams MUST consider deletion behavior explicitly. Cascading deletion SHOULD be used only when deleting the parent should unambiguously delete the dependent data.

## 5. Indexes

Indexes SHOULD be created based on demonstrated query patterns and performance requirements.

Teams SHOULD avoid adding indexes to every column because indexes increase storage requirements and write cost.

Production performance investigations SHOULD use query plans or equivalent database diagnostics where possible.

## 6. Queries

Applications MUST parameterize untrusted values in database queries.

Potentially expensive queries SHOULD be reviewed for:

- full table scans;
- unbounded result sets;
- inefficient joins;
- repeated queries inside loops;
- missing useful indexes.

## 7. Transactions

Operations that must succeed or fail as one logical unit SHOULD use a database transaction.

Transactions SHOULD be kept as short as practical and SHOULD NOT include slow external network calls unless the architecture specifically requires them.

## 8. Migrations and backward compatibility

Schema migrations for continuously deployed systems SHOULD be compatible with the currently running application version during rollout.

Destructive operations such as dropping a column SHOULD normally occur only after application code no longer depends on the object.

## 9. Production data

Production data MUST NOT be copied into development environments without authorization and appropriate sanitization.

Developers SHOULD use synthetic data for routine local development.

## 10. Backups

Production data stores containing important business data MUST have an appropriate backup or recovery strategy.

The service owner SHOULD understand the expected recovery point and recovery time objectives for the system.
