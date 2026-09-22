# Open-Strix vs Hermes SAM.gov Pilot

## Purpose
Run a 21-day controlled comparison above the existing deterministic SAM.gov scanner without changing its scoring or search logic.

## Control
The existing Python scanner remains the source of the daily candidate pool. Both agents receive the exact same normalized JSON handoff. Neither agent may modify the scanner, contact an agency, submit a response, or send external communications.

## Daily agent output
Each agent must return valid JSON for each opportunity it elevates:
- fit: Strong | Possible | Weak
- pursuit: Prime | Team | Subcontract | Monitor | Pass
- confidence: 0-100
- why
- capability_match
- gaps
- partner_need
- urgency
- next_action
- missing_information
- source_citations: solicitation/document references used

## Jim feedback
Every surfaced opportunity is graded with:
- overall_fit: 1-5
- worth_time: Yes | Maybe | No
- pursuit_posture: Prime | Team | Subcontract | Monitor | Pass
- agent_was_right: Yes | Partly | No
- note: optional
- outcome: Pursued | Bid | Partnered | Won | Lost | No-bid | Pending

Jim's feedback is ground truth for the pilot.

## Proposal challenge
Only opportunities Jim approves advance. Both agents receive the same solicitation package and independently prepare:
1. synopsis
2. compliance matrix with document/page citations
3. submission requirements and deadline
4. evaluation criteria
5. technical approach
6. management/staffing approach
7. verified capability mapping
8. verified past-performance mapping
9. gaps and teaming needs
10. assumptions / CO questions
11. required proposal outline
12. first-draft response
13. pre-submission compliance checklist

Never fabricate capabilities, past performance, personnel, certifications, pricing, or solicitation requirements. Missing evidence must be flagged.

Where practical, proposal drafts are presented as Draft A / Draft B before the agent identity is revealed.

## Proposal feedback
Score 1-5:
- solicitation_understanding
- compliance
- technical_response
- capability_accuracy
- factual_accuracy
- usefulness

Also record editing_minutes and free-text corrections.

## Comparison metrics
- agreement with Jim on pursue/pass
- mean absolute difference from Jim's 1-5 fit
- high-value miss rate (Jim 4-5 not elevated)
- false-positive rate
- confidence calibration
- proposal quality
- editing minutes to usable draft
- repeated-error rate after feedback
- model/API cost per useful opportunity
- downstream pursuit/bid/award outcomes

## Guardrails
- Read/analyze/report only during the pilot.
- No submission or external outreach without Jim's explicit approval.
- Do not expose SAM.gov, email, GitHub, or model credentials to either agent unless required and separately scoped.
- Keep the same underlying LLM/model for both agents whenever practical; log deviations.
- Agent-specific feedback is returned only to the agent that generated the analysis/draft.
