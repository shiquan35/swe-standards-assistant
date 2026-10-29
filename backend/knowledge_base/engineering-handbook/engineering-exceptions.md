# Engineering Exceptions

## 1. Purpose

Engineering standards cannot anticipate every technical or business constraint. A documented exception process allows teams to deviate from a mandatory standard when there is a justified reason.

## 2. When an exception is required

An exception is required when a team intentionally cannot satisfy a requirement marked **MUST** or **MUST NOT** in this handbook.

Recommendations marked **SHOULD** normally allow engineering judgment and do not require a formal exception unless a separate team or regulatory policy says otherwise.

## 3. Exception record

An exception request SHOULD document:

- the standard being waived;
- affected system or scope;
- business or technical justification;
- risks introduced by the deviation;
- compensating controls;
- responsible owner;
- review or expiry date where appropriate.

## 4. Approval

Exceptions MUST be approved by an appropriate accountable owner.

Security-related exceptions MUST also follow the organization's security risk acceptance process.

An engineer MUST NOT approve their own high-risk exception as the sole approver.

## 5. Duration

Exceptions SHOULD be temporary where practical.

Time-limited exceptions SHOULD be reviewed before expiry. If the underlying constraint still exists, the owner should renew the exception with updated risk information rather than silently allowing it to lapse.

## 6. Tracking

Approved exceptions SHOULD be discoverable by the affected engineering and operational teams.

When the reason for an exception no longer applies, the team SHOULD restore compliance and close the exception.

## 7. Conflicting requirements

Legal, regulatory, contractual, security, or formally adopted project-specific requirements MAY impose stricter controls than this handbook.

Where requirements conflict, teams MUST follow the applicable higher-priority obligation and seek guidance from the relevant accountable owner when the correct interpretation is unclear.
