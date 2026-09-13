# Verity deployment and verification

Canonical source: `contracts/verity_oracle.py`

## 1. Verify the repository revision

Run:

```bash
python -m unittest discover -s tests -v
```

Expected result for this revision: **50 tests passing**.

Canonical source SHA-256:

```text
3330233500f73392410bc6186c4e6a3a91bbee7e7a2d7a40670fb6c38f4d55f4
```

You can reproduce it with:

```bash
python - <<'PY'
from pathlib import Path
import hashlib
p = Path('contracts/verity_oracle.py')
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
```

If `genvm-lint` is available, also run:

```bash
genvm-lint contracts/verity_oracle.py
```

## 2. Deploy in GenLayer Studio

1. Open GenLayer Studio.
2. Add `contracts/verity_oracle.py` as the Intelligent Contract source.
3. Run/debug the source first and resolve any Studio/GenVM error before deployment.
4. Deploy from the intended account. The constructor requires no arguments.
5. Wait for finalization and verify successful execution.
6. Record the contract address, deployment transaction, Explorer contract URL, deployed commit SHA, and canonical source hash.

### Finalized deployment

- Contract address: [`0xb9DfAFb2366944f83E99855966d0dBC90b879fa9`](https://explorer-studio.genlayer.com/address/0xb9DfAFb2366944f83E99855966d0dBC90b879fa9)
- Transaction: [`0x57daa68596b2766bfddd043294d0ac2d90c08fea9bcd8eea425e4c5035140a17`](https://explorer-studio.genlayer.com/tx/0x57daa68596b2766bfddd043294d0ac2d90c08fea9bcd8eea425e4c5035140a17)
- Source commit: [`917aa47`](https://github.com/haris4587/verity-oracle/commit/917aa47f3e3a99f19b2eed35de484c92943a61cc)
- Source SHA-256: `3330233500f73392410bc6186c4e6a3a91bbee7e7a2d7a40670fb6c38f4d55f4`
- Execution mode: Normal (Full Consensus), five initial validators
- Result: `FINALIZED`, consensus `Accepted`, GenVM `SUCCESS`

## 3. Read smoke test

After deployment, verify at minimum:

- `get_version()` returns `1.2.0`;
- `get_totals()` returns the initialized accounting state.

Verified live against the finalized deployment:

- `get_version()` returned `1.2.0`;
- `get_totals()` returned version `1.2.0` with zero balance, reserve, surplus, requests, proposals, resolutions, rewards, bonds, refunds, funding, and withdrawals.

## 4. Payable lifecycle verification

GenLayer Studio currently reports that token transfers are unsupported, so the payable reward/bond lifecycle cannot be truthfully demonstrated there. The 50-test direct-mode suite covers every payout, refund, bond return, slashing, surplus, and safe-`UNRESOLVABLE` branch. When Studio enables transfers, verify the full deployed lifecycle as follows:

1. Prepare 2–6 stable public HTTPS resources from at least two independent publisher families. URLs must use lowercase `https://`, include a path, and contain no credentials, custom port, query, fragment, backslash, or IP-literal authority.
2. Compute the SHA-256 digest of each exact response body and the canonical bundle hash expected by the contract.
3. Call payable `open_request(...)` with a reward of at least `0.001 GEN` and a proposal window of at least 300 seconds.
4. Read the request with `get_request(request_id)` and confirm the locked values.
5. From another account, call payable `propose_answer(...)` with the exact `bond_size` returned by the request and 2–6 unique locked citations spanning two publisher families.
6. Read the proposal with `get_proposal(request_id, proposal_id)`.
7. After `finalize_after`, call `finalize(request_id)`.
8. Verify `get_result(request_id)`, `get_request(request_id)`, and `is_resolved(request_id)` from finalized state. Confirm that `decision_hash` is a 64-character SHA-256 commitment and matches `final_decision_hash` in the full request record.

## 5. Evidence to preserve for the contribution

Keep direct links for:

- public contract-only GitHub repository;
- exact Git commit used for deployment;
- GenLayer Explorer contract page;
- deployment transaction;
- `open_request` transaction;
- `propose_answer` transaction;
- `finalize` transaction;
- finalized `get_result` / request state;
- optional failure-path proof demonstrating safe `UNRESOLVABLE` handling.

The finalized Explorer deployment and live reads prove GenLayer execution and validator consensus. The local suite supplies deterministic coverage for the payable lifecycle that the current Studio cannot execute.
