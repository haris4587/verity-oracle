# Verity security model

## Scope

Verity is an evidence-bounded oracle. It settles a binary question against the exact public response bytes committed when a request is opened. It does not claim to discover every relevant source on the internet or prove that a requester's evidence selection is complete.

## Consensus boundary

The deterministic request state locks the question, category, URLs, per-URL SHA-256 values, canonical bundle hash, reward, bond size, and deadlines before adjudication. During `finalize`, each validator independently:

1. fetches every locked URL;
2. hashes the exact response bytes;
3. excludes unavailable, oversized, non-2xx, and hash-mismatched responses;
4. applies the two-authenticated-source gate;
5. asks its own model to judge only the authenticated evidence; and
6. checks the leader's normalized verdict and full retrieval manifest against its independent run.

Settlement proceeds only after GenLayer consensus. Model wording may vary, but the economically meaningful verdict and authenticated retrieval record must agree.

## Defensive invariants

- Only canonical public DNS HTTPS resource URLs are accepted.
- Source diversity is counted by publisher family, not by subdomain.
- Request and proposal IDs cannot contain the `:` delimiter used by composite storage keys.
- Proposal count is capped, bounding finalization work and payout loops.
- A binary verdict requires evidence quality of at least 60 and at least two authenticated citations from independent publisher families.
- Malformed model output, insufficient authenticated evidence, or weak citation support becomes `UNRESOLVABLE`.
- `UNRESOLVABLE` returns the reward and every active bond; it never slashes a participant.
- `total_reserved` tracks all request rewards and active bonds. Owner withdrawal is limited to balance above that reserve.
- Final decision fields are committed by `decision_hash` together with the locked `bundle_hash`.

## Known limitations

- Exact-byte commitments are intentionally strict. Dynamic pages may later fail authentication and safely resolve as `UNRESOLVABLE`.
- A requester can still cherry-pick otherwise authentic sources. Consumers must treat the final answer as scoped to the displayed locked evidence bundle.
- Publisher-family grouping is deliberately conservative and is not a universal public-suffix implementation.
- Local tests use a small SDK stand-in. A finalized GenLayer Studio/Explorer deployment and live write-path transaction are required as execution proof.

## Responsible disclosure

Do not place secrets, private endpoints, signed URLs, or personal data in requests. Contract state and evidence URLs are public and permanent.
