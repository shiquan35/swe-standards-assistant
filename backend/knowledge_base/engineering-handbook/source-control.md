# Source Control Standards

## 1. Repository requirements

All production application code MUST be stored in an approved source control system.

Repositories SHOULD contain:

- a README;
- dependency manifests and lock files;
- build and test instructions;
- configuration examples where appropriate;
- ownership information.

Secrets, credentials, access tokens, private keys, and production configuration values MUST NOT be committed to source control.

## 2. Default branch

The default branch SHOULD be named `main`.

The default branch MUST be protected against direct pushes for production repositories. Changes SHOULD enter the default branch through pull requests.

## 3. Branch naming

Branches SHOULD use a descriptive prefix and short purpose.

Recommended patterns include:

- `feature/add-user-search`
- `fix/login-timeout`
- `docs/update-api-guide`
- `chore/upgrade-dependencies`
- `hotfix/payment-validation`

Branches SHOULD be short-lived and deleted after they are merged.

## 4. Commits

Commits SHOULD represent a logical unit of change.

Commit messages SHOULD explain the intent of the change. Teams MAY use Conventional Commits if they find the convention useful.

Examples:

- `feat: add account search endpoint`
- `fix: prevent duplicate invoice creation`
- `docs: clarify local setup`

Large unrelated changes SHOULD NOT be combined into a single commit solely for convenience.

## 5. Pull requests

Changes to protected branches MUST be submitted through a pull request.

A pull request SHOULD:

- have a clear title and description;
- explain why the change is needed;
- describe significant implementation decisions;
- identify relevant tests;
- link to a work item when one exists;
- remain small enough to review effectively.

Authors SHOULD review their own diff before requesting review.

## 6. Code review

At least one qualified reviewer other than the author MUST approve a production code change before merge.

High-risk changes MAY require additional reviewers according to team policy.

Reviewers SHOULD consider:

- correctness;
- security;
- maintainability;
- tests;
- backward compatibility;
- performance where relevant;
- observability;
- documentation.

The author MUST resolve blocking review comments before merge.

## 7. Merge requirements

Required automated checks MUST pass before a pull request is merged.

A repository SHOULD configure branch protection to enforce applicable checks and approvals.

Force pushes to the protected default branch MUST NOT be permitted.

## 8. Emergency changes

Emergency production fixes MAY use an expedited review process when normal review would cause unacceptable operational impact.

The change MUST still be recorded in source control and SHOULD receive retrospective review after the incident is stabilized.
