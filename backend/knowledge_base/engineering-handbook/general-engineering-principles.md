# General Engineering Principles

## 1. Build for maintainability

Engineers SHOULD optimize code for readability and maintainability rather than cleverness. Code is read more often than it is written.

Implementations SHOULD:

- use clear names;
- keep functions and modules focused;
- avoid unnecessary abstraction;
- remove dead code;
- minimize duplicated business logic;
- document non-obvious design decisions.

## 2. Prefer simple solutions

Teams SHOULD choose the simplest design that satisfies the current requirements while allowing reasonable future change.

A new framework, service, database, queue, or infrastructure component SHOULD NOT be introduced unless it solves a demonstrated problem.

## 3. Separate concerns

Presentation, business logic, persistence, and external integrations SHOULD be separated where practical.

Business rules SHOULD NOT depend directly on UI components or transport-specific concerns such as HTTP request objects.

## 4. Configuration over hardcoding

Environment-specific values MUST NOT be hardcoded in application source code.

Configuration such as service URLs, feature flags, connection settings, and environment names SHOULD be supplied through environment variables or an approved configuration service.

Secrets are subject to the stricter requirements in the Security Standards.

## 5. Fail safely

Applications MUST handle expected failure conditions explicitly.

Errors SHOULD:

- provide useful diagnostic information to engineers;
- avoid exposing sensitive implementation details to end users;
- preserve data integrity;
- return an appropriate failure state rather than silently succeeding.

## 6. Dependency management

Third-party dependencies SHOULD be added only when they provide meaningful value.

Dependencies MUST be declared in the project's dependency manifest and SHOULD be version constrained or locked using the ecosystem's standard lock file.

Unused dependencies SHOULD be removed.

## 7. Backward compatibility

Public APIs and shared interfaces SHOULD remain backward compatible where practical.

Breaking changes MUST be identified explicitly and communicated to affected consumers before deployment.

## 8. Ownership

Every production service MUST have an identifiable owning team.

The owning team is responsible for:

- maintaining the service;
- responding to operational issues;
- reviewing dependency and security updates;
- maintaining relevant documentation;
- defining an escalation path.
