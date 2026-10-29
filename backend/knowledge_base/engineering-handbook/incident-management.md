# Incident Management Standards

## 1. Definition

An incident is an unplanned event that materially degrades or interrupts a production service, compromises security, or risks important data.

Teams SHOULD use a severity model appropriate to their services.

## 2. Initial response

When an incident is detected, responders SHOULD first establish:

- user impact;
- affected services;
- approximate start time;
- current severity;
- immediate containment or mitigation options.

Restoring safe service is generally a higher priority during an active incident than identifying the complete root cause.

## 3. Incident ownership

Significant incidents SHOULD have a clearly identified incident lead.

The incident lead coordinates response activities and helps maintain a shared understanding of status and priorities.

Additional roles MAY include technical responders, communications owner, and subject-matter experts.

## 4. Communication

Material incidents SHOULD have a dedicated communication channel or incident record.

Updates SHOULD distinguish confirmed facts from hypotheses.

Customer or stakeholder communications MUST NOT speculate about causes that have not been established.

## 5. Changes during incidents

Emergency changes SHOULD be limited to actions necessary to mitigate or diagnose the incident.

Responders SHOULD record important commands, configuration changes, deployments, and decisions made during the incident.

## 6. Resolution

An incident SHOULD be considered stabilized when user impact has ended or reached an accepted temporary state and the service is sufficiently monitored.

Temporary mitigations SHOULD result in tracked follow-up work when a permanent fix remains necessary.

## 7. Post-incident review

Significant incidents SHOULD receive a post-incident review.

The review SHOULD focus on learning and system improvement rather than individual blame.

A useful review includes:

- impact;
- timeline;
- contributing factors;
- detection and response effectiveness;
- what went well;
- what could be improved;
- concrete follow-up actions.

## 8. Follow-up actions

Post-incident actions SHOULD have an owner and a priority.

Teams SHOULD prioritize changes that reduce recurrence, improve detection, or reduce the impact of similar failures.
