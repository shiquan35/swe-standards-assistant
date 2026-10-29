# Coding Standards

## 1. General requirements

Projects MUST use the standard formatter and linter selected by the owning team.

Formatting SHOULD be automated rather than manually enforced during code review.

Code MUST NOT contain unresolved merge markers, debugging statements intended only for local development, or commented-out blocks of obsolete code.

## 2. Naming

Names SHOULD communicate intent.

Variables and functions SHOULD use the language ecosystem's conventional naming style. Abbreviations SHOULD be avoided unless they are widely understood in the project domain.

Boolean names SHOULD make the true/false meaning obvious, for example:

- `is_active`
- `has_permission`
- `can_retry`

## 3. Functions and modules

Functions SHOULD have a single clear responsibility.

Long functions SHOULD be decomposed when doing so improves readability, testability, or reuse. There is no organization-wide maximum function length.

Modules SHOULD group related behavior and expose a deliberate public interface.

## 4. Comments

Comments SHOULD explain why a decision exists rather than restating what straightforward code already says.

TODO comments SHOULD include enough context to understand the outstanding work. Teams SHOULD link long-lived TODOs to a tracked work item.

## 5. Error handling

Expected errors SHOULD be handled explicitly.

Applications MUST NOT use an empty catch or exception handler that silently discards an error unless the behavior is intentional and documented.

Internal exception details and stack traces MUST NOT be returned directly to external users.

## 6. Asynchronous code

Independent asynchronous operations SHOULD be executed concurrently when doing so is safe and materially improves latency.

Operations that depend on earlier results MUST remain ordered.

Concurrency MUST NOT compromise data consistency or exceed downstream service limits.

## 7. Type safety

Projects using languages with static typing SHOULD enable appropriate type checking in CI.

For TypeScript projects, application code SHOULD avoid `any` when a useful type can reasonably be expressed.

For Python projects, type hints SHOULD be used for public functions, service boundaries, and complex domain logic.

## 8. Frontend standards

User interfaces SHOULD:

- use semantic HTML;
- support keyboard navigation;
- provide accessible labels for interactive controls;
- represent loading, empty, success, and error states;
- avoid exposing secrets in client-side bundles.

Reusable UI behavior SHOULD be extracted into components when reuse or complexity justifies it.

## 9. Backend standards

Backend services SHOULD separate request validation, business logic, and persistence concerns.

Request data MUST be validated before it is used in business operations.

External calls SHOULD define sensible connection and request timeouts.

## 10. Dependency boundaries

Code SHOULD depend on stable interfaces rather than implementation details where this meaningfully improves testability or replaceability.

Teams SHOULD avoid abstraction layers that merely forward calls without adding a useful boundary.
