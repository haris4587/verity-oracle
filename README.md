# Verity — Bonded Truth Oracle

Verity is a standalone **GenLayer Intelligent Contract** for economically resolving factual TRUE/FALSE claims from authenticated public web evidence.

A requester funds a reward and commits 2–6 HTTPS sources together with their SHA-256 digests. Participants bond `TRUE` or `FALSE` proposals. After the proposal window closes, GenLayer validators independently fetch the committed sources during nondeterministic execution, verify the exact response bytes against the locked hashes, adjudicate the factual question with AI consensus, and then execute deterministic on-chain settlement.

This repository intentionally contains **only the Intelligent Contract, tests, a contract-consumer example, and deployment documentation**. It does not bundle a frontend, backend, database, or DApp.

## Why GenLayer is required

Verity cannot be implemented as a conventional deterministic smart contract because finalization requires judgment over public web evidence and natural-language claims. The contract uses GenLayer nondeterministic execution for web retrieval and AI adjudication, then converts the validator-agreed result into deterministic economic consequences.

The consensus-critical path is:

`locked URLs + SHA-256 commitments -> validator web retrieval -> byte authentication -> AI judgment -> validator consensus -> deterministic settlement`

## Core flow

1. `open_request(...)` — requester locks a factual question, category, 2–6 HTTPS evidence URLs, per-source SHA-256 hashes, a canonical bundle hash, and a reward.
2. `propose_answer(...)` — participants bond `TRUE` or `FALSE` and must cite 2–6 locked URLs spanning at least two publisher families.
3. `finalize(...)` — after the enforced deadline, validators re-fetch every locked source, authenticate fetched bytes, and adjudicate the question from authenticated evidence.
4. Settlement is deterministic after consensus:
   - matching verdict: earliest matching proposal receives the reward and bonded settlement;
   - TRUE/FALSE with no matching proposal: requester receives the reward back and losing bonds become surplus;
   - `UNRESOLVABLE`: requester reward and proposal bonds are returned without punishment.
5. Other contracts can consume finalized outcomes through `VerityOracleView.get_result()` and `is_resolved()`.

## Safety properties

- Canonical HTTPS resource URLs only: no credentials, ports, queries, fragments, IP literals, private/reserved hostnames, or ambiguous authorities.
- 2–6 sources required across at least two publisher families; subdomains of one registrable family do not count as independent.
- Exact SHA-256 authentication of fetched bytes.
- Proposal and verdict citations must belong to the fetched-and-authenticated locked evidence set.
- A punitive `TRUE`/`FALSE` settlement requires quality ≥60 plus at least two authenticated citations from independent publisher families.
- Every validator independently re-fetches the locked URLs and re-runs adjudication before accepting the leader's verdict and retrieval manifest.
- Minimum and maximum proposal/finalization windows are enforced in contract state.
- Request and proposal identifiers are restricted to collision-safe characters, and each request is capped at 32 proposals.
- Evidence outages and insufficient authenticated evidence resolve safely as `UNRESOLVABLE`.
- Weak or malformed validator output is coerced to the non-punitive `UNRESOLVABLE` state.
- The final verdict, citations, confidence, evidence quality, retrieval manifest, and bundle hash are bound by an on-chain `decision_hash`.
- Settlement accounting is covered across payout, refund, returned-bond, slashing, and surplus paths.

## Trust boundary

Verity answers the locked question **relative to the exact evidence bundle selected by the requester**. SHA-256 commitments prevent evidence substitution after opening, strict publisher-family rules reduce false source diversity, and validators independently judge the authenticated bytes. The contract does not claim that a caller-selected bundle is a complete representation of every fact on the public internet. Applications consuming Verity should display the locked URLs, final retrieval manifest, citations, and `decision_hash` so users can audit that scope.

See [`SECURITY.md`](./SECURITY.md) for the full threat model and settlement invariants.

## Repository layout

```text
contracts/
  verity_oracle.py
  examples/
    escrow_with_verity.py
tests/
  fake_genlayer.py
  test_verity_oracle.py
DEPLOY.md
```

## Tests

Run the local direct-mode regression suite:

```bash
python -m unittest discover -s tests -v
```

Current result: **48/48 tests passing**.

The local suite uses `tests/fake_genlayer.py` to deterministically exercise contract state transitions, evidence failures, consensus disagreement, deadline enforcement, proposal restrictions, and settlement accounting. It is not presented as a substitute for live GenLayer validator execution; finalized Studio/Explorer transactions are the deployment proof.

## Canonical source

Deploy exactly:

```text
contracts/verity_oracle.py
```

SHA-256 of the current canonical source:

```text
3cfc6476f0e4e6979051282fa5bc45a5623783c98777bf8624373d69400473ef
```

## Deployment and live verification

See [`DEPLOY.md`](./DEPLOY.md) for the Studio deployment and evidence checklist. After deployment, the repository will record the deployed contract address, transaction/Explorer links, exact commit SHA, and live write/read verification evidence.

## Reusable contract interface

`contracts/examples/escrow_with_verity.py` demonstrates how another Intelligent Contract can read a finalized Verity resolution through the contract interface and use it as a resolution primitive for escrow or conditional execution.
