# Documentation Standards

## 1. Repository README

Production repositories MUST contain a README or equivalent entry point.

The README SHOULD explain:

- the purpose of the project;
- prerequisites;
- how to run it locally;
- how to run tests;
- important configuration requirements;
- where to find additional documentation.

## 2. Architecture documentation

Services with non-trivial architecture SHOULD maintain documentation describing major components and their relationships.

Architecture documentation SHOULD focus on decisions and boundaries that are not obvious from reading individual source files.

## 3. Architecture decision records

Teams SHOULD use Architecture Decision Records (ADRs) for important decisions that are costly or difficult to reverse.

An ADR SHOULD normally capture:

- context;
- decision;
- important alternatives considered;
- consequences.

## 4. API documentation

Cross-team and external APIs MUST have maintained interface documentation.

Documentation SHOULD be updated in the same change that modifies an API contract.

## 5. Operational documentation

Production services SHOULD have operational guidance covering common failure and recovery scenarios.

Runbooks SHOULD be concise enough to use during an incident and SHOULD link to relevant dashboards, logs, or procedures where appropriate.

## 6. Code comments

Documentation SHOULD NOT duplicate obvious code behavior.

Comments are most useful for constraints, rationale, workarounds, and behavior that would otherwise be surprising.

## 7. Keeping documentation current

Engineers SHOULD update documentation as part of the change that makes existing documentation inaccurate.

Known obsolete documentation SHOULD be corrected or clearly marked as obsolete.
