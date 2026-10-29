# CI/CD and Deployment Standards

## 1. Continuous integration

Production repositories SHOULD run automated validation for pull requests.

Applicable CI checks SHOULD include:

- formatting or linting;
- automated tests;
- type checking where used;
- build validation;
- security or dependency checks where available.

Required CI checks MUST pass before merge.

## 2. Build artifacts

Deployments SHOULD use immutable, versioned build artifacts.

The same artifact SHOULD be promoted between environments where practical rather than rebuilt independently for each environment.

Artifact versions SHOULD be traceable to the source commit that produced them.

## 3. Environments

Production systems SHOULD have at least one non-production environment suitable for validating meaningful changes.

Environment-specific configuration MUST be externalized from the application artifact.

Production credentials MUST NOT be used in development or test environments.

## 4. Deployment automation

Production deployments SHOULD be automated and repeatable.

Manual production steps SHOULD be documented when automation is not practical.

Infrastructure SHOULD be managed as code where the platform and project scale make this appropriate.

## 5. Deployment strategy

Services SHOULD select a deployment strategy appropriate to their risk and availability requirements.

Examples include:

- rolling deployments;
- blue-green deployments;
- canary releases.

High-risk releases SHOULD use a strategy that limits blast radius where the platform supports it.

## 6. Database deployment

Database migrations MUST be included in the release process when required.

Teams SHOULD assess whether a migration is backward compatible before deploying application instances that depend on it.

## 7. Rollback and recovery

Production services MUST have a documented method to recover from a failed deployment.

Recovery MAY involve rollback, roll-forward, traffic switching, or another tested strategy.

Teams SHOULD NOT assume application rollback will automatically reverse a destructive database migration.

## 8. Production approvals

Teams SHOULD apply deployment approvals proportionate to the system's risk.

An approval process SHOULD NOT rely solely on an individual who authored the change for high-risk production deployments.

## 9. Feature flags

Feature flags MAY be used to separate code deployment from feature release.

Long-lived flags SHOULD have an owner and SHOULD be removed after they are no longer needed.

Sensitive authorization decisions MUST NOT rely solely on client-side feature flags.
