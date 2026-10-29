# API Standards

## 1. General design

HTTP APIs SHOULD follow resource-oriented REST conventions unless another protocol is better suited to the use case.

Resource names SHOULD use nouns rather than actions.

Preferred:

`GET /users/123`

Avoid:

`GET /getUser?id=123`

API paths SHOULD use lowercase names and a consistent pluralization convention.

## 2. HTTP methods

Use HTTP methods according to their intended semantics:

- `GET` retrieves a resource and MUST NOT intentionally modify application state.
- `POST` creates a resource or initiates a non-idempotent operation.
- `PUT` replaces a resource and SHOULD be idempotent.
- `PATCH` partially updates a resource.
- `DELETE` removes a resource and SHOULD be idempotent from the client's perspective.

## 3. Status codes

APIs MUST return HTTP status codes that reflect the outcome of the request.

Common examples:

- `200 OK` — successful request.
- `201 Created` — resource created.
- `204 No Content` — successful request with no response body.
- `400 Bad Request` — malformed or invalid request.
- `401 Unauthorized` — authentication is required or invalid.
- `403 Forbidden` — authenticated caller lacks permission.
- `404 Not Found` — requested resource does not exist.
- `409 Conflict` — request conflicts with current resource state.
- `422 Unprocessable Content` — syntactically valid request fails semantic validation.
- `429 Too Many Requests` — rate limit exceeded.
- `500 Internal Server Error` — unexpected server failure.

## 4. Request validation

All externally supplied input MUST be validated at the service boundary.

Validation SHOULD cover:

- required fields;
- data types;
- allowed ranges;
- string lengths;
- accepted formats;
- allowed enumeration values.

Invalid input SHOULD produce a consistent error response.

## 5. Error responses

An API SHOULD use a consistent error structure.

Example:

```json
{
  "error": {
    "code": "INVALID_EMAIL",
    "message": "The email address is invalid.",
    "request_id": "req_123"
  }
}
```

Error messages returned to clients MUST NOT reveal secrets, database credentials, stack traces, or sensitive internal implementation details.

## 6. Authentication and authorization

Protected API endpoints MUST authenticate callers.

Authorization MUST be enforced server-side for every protected operation. Hiding an action in the frontend is not an authorization control.

## 7. Pagination

Endpoints returning potentially large collections SHOULD support pagination.

Cursor-based pagination is preferred for large or frequently changing datasets. Offset pagination MAY be used for small or stable collections.

APIs SHOULD impose a maximum page size.

## 8. Versioning

Breaking API changes MUST be versioned or introduced through a documented migration strategy.

Teams SHOULD avoid creating a new API version for additive, backward-compatible changes.

## 9. Idempotency

Operations that may be safely retried but could create duplicate side effects SHOULD support an idempotency mechanism where duplicate execution presents meaningful risk.

Payment creation and other high-impact transaction endpoints are examples where idempotency keys are strongly recommended.

## 10. API documentation

Externally consumed and cross-team APIs MUST have machine-readable or equivalent maintained documentation.

For REST APIs, OpenAPI is the preferred specification format.

Documentation SHOULD include authentication requirements, request and response schemas, error cases, and representative examples.
