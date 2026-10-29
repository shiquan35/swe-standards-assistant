# Security Standards

## 1. Security is a shared responsibility

Security requirements apply throughout design, implementation, review, deployment, and operations.

Teams MUST address known critical security risks before a production release unless a formally approved exception exists.

## 2. Secrets

Secrets MUST NOT be stored in source code, committed configuration files, container images, client-side bundles, or application logs.

Examples of secrets include:

- passwords;
- API keys;
- private keys;
- access tokens;
- database credentials;
- signing keys.

Production secrets MUST be stored in an approved secrets-management system.

Applications SHOULD obtain secrets at runtime using the platform's approved mechanism.

## 3. Authentication

Applications handling protected resources MUST authenticate users or calling services.

Password storage, when implemented by the application, MUST use an established adaptive password hashing algorithm and MUST NOT use reversible encryption or general-purpose fast hashes such as SHA-256 alone.

Teams SHOULD prefer established identity providers and authentication libraries over implementing authentication protocols themselves.

## 4. Authorization

Authorization MUST be enforced on the server or trusted service boundary.

Applications SHOULD follow least privilege: users, workloads, and administrators receive only the permissions required to perform their responsibilities.

Authorization checks SHOULD be based on verified identity and trusted server-side data.

## 5. Input handling

All untrusted input MUST be validated before use.

Database access MUST use parameterized queries or an ORM/query builder that safely parameterizes values.

Applications MUST NOT construct SQL commands by directly concatenating untrusted input.

Untrusted output rendered into HTML MUST be escaped or safely encoded according to its output context.

## 6. Transport security

Production network traffic carrying credentials, authentication tokens, personal data, or other sensitive information MUST use encrypted transport.

Public web applications MUST use HTTPS.

## 7. Sensitive data

Teams SHOULD minimize collection and retention of sensitive data.

Sensitive values MUST NOT be written to application logs unless an explicitly approved use case and suitable protection exist.

Access to sensitive production data MUST follow least-privilege principles.

## 8. Dependency security

Projects SHOULD use automated dependency vulnerability scanning where supported.

Known critical vulnerabilities in production dependencies MUST be evaluated promptly and remediated according to the organization's vulnerability-management process.

## 9. Security headers and browser applications

Web applications SHOULD configure appropriate browser security controls such as Content Security Policy, frame restrictions, and secure cookie attributes according to the application's architecture.

Authentication cookies carrying sensitive session identifiers MUST use `Secure` in production and SHOULD use `HttpOnly` and an appropriate `SameSite` policy.

## 10. File uploads

Applications accepting file uploads MUST validate file size and expected file type.

Uploaded files SHOULD be stored outside directly executable application paths.

Applications SHOULD perform malware scanning when the risk and deployment environment warrant it.

## 11. Logging security events

Security-relevant events SHOULD be logged when appropriate, including:

- repeated authentication failures;
- permission changes;
- administrative actions;
- suspicious access patterns.

Logs MUST NOT include raw passwords, complete authentication tokens, or private keys.

## 12. Reporting vulnerabilities

Suspected security vulnerabilities MUST be reported through the organization's approved security reporting process rather than discussed in public issue trackers.
