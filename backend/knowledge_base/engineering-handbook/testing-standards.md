# Testing Standards

## 1. Testing principles

Automated tests SHOULD provide confidence that important behavior works and regressions are detected.

Teams SHOULD prioritize tests around business-critical behavior, complex logic, security boundaries, and previously observed defects.

Tests SHOULD be deterministic and independently repeatable.

## 2. Unit tests

Unit tests SHOULD cover isolated business logic and important edge cases.

A unit test SHOULD:

- execute quickly;
- avoid unnecessary network access;
- control external dependencies;
- make the expected behavior clear.

## 3. Integration tests

Integration tests SHOULD verify important boundaries such as:

- database access;
- message queues;
- external service adapters;
- authentication integrations;
- API-to-persistence behavior.

Tests MUST NOT call real production systems.

## 4. End-to-end tests

End-to-end tests SHOULD cover a small set of critical user journeys.

Teams SHOULD avoid using end-to-end tests as the only form of automated testing because they are generally slower and harder to diagnose than lower-level tests.

## 5. Test coverage

There is no organization-wide mandatory percentage for code coverage.

Teams SHOULD use coverage as a diagnostic signal rather than a target by itself. A high coverage percentage does not replace meaningful assertions or appropriate test cases.

Critical logic SHOULD be tested even when the overall repository coverage target has already been reached.

## 6. Pull request testing

Required automated tests MUST pass before production code is merged into a protected branch.

A code change SHOULD include new or updated tests when it changes testable behavior.

Bug fixes SHOULD include a regression test when practical.

## 7. Test data

Automated tests SHOULD use synthetic or appropriately sanitized data.

Production personal data, credentials, and secrets MUST NOT be copied into local test fixtures or committed to a repository.

## 8. Flaky tests

Known flaky tests SHOULD be investigated promptly.

A flaky test MUST NOT be repeatedly retried indefinitely to hide instability. If temporarily quarantined, the test SHOULD have an owner or tracked remediation item.

## 9. Performance testing

Services with material performance or scalability requirements SHOULD define measurable performance targets and test against them before significant releases.

Load tests against production MUST be coordinated with the service owner and operations stakeholders.
