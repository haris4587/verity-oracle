"""
Direct-mode tests for the Verity oracle contract.

Run with:  python -m unittest discover -s tests -v
(or)       python -m pytest tests -q

These tests import contracts/verity_oracle.py against the in-process fake
GenLayer SDK in tests/fake_genlayer.py, then drive the full lifecycle:
source-set authentication, bond accounting, consensus adjudication, and
every settlement branch.
"""

import hashlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import fake_genlayer as glmod  # noqa: E402
from fake_genlayer import (  # noqa: E402
    Address,
    DynArray,
    Return,
    TreeMap,
    UserError,
    VALIDATOR_DIVERGENCE,
    VAULT,
    WEB_FIXTURES,
    _Response,
    gl,
    u256,
)

# Inject the fake SDK before importing the contract.
sys.modules["genlayer"] = glmod

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "verity_oracle", os.path.join(ROOT, "contracts", "verity_oracle.py")
)
verity_oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verity_oracle)  # type: ignore[union-attr]

VerityOracle = verity_oracle.VerityOracle

GEN = 10**18

OWNER = Address("0xOwner000000000000000000000000000000001")
REQUESTER = Address("0xRequester00000000000000000000000000001")
PROPOSER_A = Address("0xProposerA000000000000000000000000001")
PROPOSER_B = Address("0xProposerB000000000000000000000000002")
PROPOSER_C = Address("0xProposerC000000000000000000000000003")
OTHER = Address("0xOther000000000000000000000000000000000001")

SOURCE_BODIES = {
    "https://ledger.news/meridian-hack.html": b"<html><body><h1>Meridian v2 vault exploited</h1><p>Confirmed: on August 12, 2026 an attacker drained the vault.</p></body></html>",
    "https://blog.meridian.io/postmortem": b"<html><body><h1>Postmortem</h1><p>We confirm the August 12 exploit and are reimbursing users.</p></body></html>",
    "https://defi-watch.io/bulletin": b"<html><body><h1>Weekly bulletin</h1><p>Meridian exploit confirmed by on-chain forensics, losses estimated.</p></body></html>",
    "https://blockfront.com/meridian": b"<html><body><h1>Meridian coverage</h1><p>Independent analysts verified the attack timeline.</p></body></html>",
}

SOURCE_URLS = list(SOURCE_BODIES.keys())


def digest(url: str) -> str:
    return hashlib.sha256(SOURCE_BODIES[url]).hexdigest()


def bundle_hash(urls, hashes) -> str:
    canonical = json.dumps(
        {"hashes": list(hashes), "urls": list(urls)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Clock:
    def __init__(self, start: int = 1_800_000_000) -> None:
        self.t = start

    def now(self) -> u256:
        return u256(self.t)

    def advance(self, seconds: int) -> None:
        self.t += seconds


def deposit(contract, amount: int) -> None:
    """Simulate GenVM crediting message.value to the contract balance."""
    key = id(contract)
    VAULT.balances[key] = VAULT.balances.get(key, 0) + amount


def act_as(sender: Address, value: u256 = u256(0)) -> None:
    gl.message.sender_address = sender
    gl.message.value = value


def fresh_contract(clock: Clock) -> VerityOracle:
    act_as(OWNER)
    contract = VerityOracle()
    contract._now = clock.now  # type: ignore[method-assign]
    VAULT.transfers.clear()
    return contract


def serve_fixtures(urls=None) -> None:
    WEB_FIXTURES.clear()
    for url in (urls or SOURCE_URLS):
        WEB_FIXTURES[url] = _Response(200, SOURCE_BODIES[url])


def make_source_set(urls):
    return urls, [digest(u) for u in urls]


def open_request(
    contract,
    request_id: str = "req-001",
    question: str = "Did Meridian Protocol suffer a contract exploit on August 12, 2026?",
    urls=None,
    reward: int = 10 * GEN,
    window: int = 3600,
    grace: int = 300,
    category: str = "PROTOCOL_SECURITY",
):
    urls = urls or SOURCE_URLS
    _, hashes = make_source_set(urls)
    act_as(REQUESTER, u256(reward))
    contract.open_request(
        request_id,
        question,
        category,
        json.dumps(urls),
        json.dumps(hashes),
        bundle_hash(urls, hashes),
        u256(window),
        u256(grace),
    )
    deposit(contract, reward)


def propose(
    contract,
    proposal_id: str,
    answer: str,
    proposer: Address,
    citations=None,
    bond_override: int | None = None,
    rationale: str = "The authenticated sources establish this answer.",
):
    request = json.loads(contract.get_request("req-001"))
    bond = bond_override if bond_override is not None else request["bond_size"]
    act_as(proposer, u256(bond))
    contract.propose_answer(
        "req-001", proposal_id, answer, rationale, json.dumps(citations or SOURCE_URLS[:2])
    )
    deposit(contract, bond)


def set_verdict(verdict: str, quality: int = 80, citations=None) -> None:
    gl.nondet.default_verdict = {
        "verdict": verdict,
        "confidence_band": "HIGH",
        "evidence_quality": quality,
        "rationale": "The authenticated evidence supports " + verdict + ".",
        "citations": citations or list(SOURCE_URLS),
    }


def finalize(contract, clock: Clock) -> None:
    clock.advance(10_000)
    act_as(OTHER)
    contract.finalize("req-001")


class BundleTests(unittest.TestCase):
    def test_canonical_bundle_is_order_sensitive(self):
        urls, hashes = make_source_set(SOURCE_URLS[:2])
        self.assertEqual(
            verity_oracle._canonical_bundle(urls, hashes),
            bundle_hash(urls, hashes),
        )
        self.assertNotEqual(
            verity_oracle._canonical_bundle(list(reversed(urls)), list(reversed(hashes))),
            bundle_hash(urls, hashes),
        )

    def test_bundle_hash_commitment_is_stable(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        first = bundle_hash(urls, hashes)
        second = bundle_hash(urls, hashes)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        int(first, 16)  # raises if not hex


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        serve_fixtures()
        self.clock = Clock()
        self.contract = fresh_contract(self.clock)

    def test_requires_two_hosts_minimum(self):
        single_host = [
            "https://news.com/a",
            "https://news.com/b",
        ]
        bodies = [b"alpha", b"beta"]
        for u, b in zip(single_host, bodies):
            SOURCE_BODIES[u] = b
        urls, hashes = make_source_set(single_host)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-host", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(300),
            )
        for u in single_host:
            del SOURCE_BODIES[u]

    def test_subdomains_of_one_publisher_are_not_independent(self):
        urls = [
            "https://news.publisher.com/report",
            "https://blog.publisher.com/statement",
        ]
        for url, body in zip(urls, [b"report", b"statement"]):
            SOURCE_BODIES[url] = body
        _, hashes = make_source_set(urls)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-family", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(300),
            )
        for url in urls:
            del SOURCE_BODIES[url]

    def test_rejects_private_hosts(self):
        bad = ["https://example.com/a", "http://127.0.0.1:8080/secret"]
        for u, b in zip(bad, [b"x", b"y"]):
            SOURCE_BODIES[u] = b
        urls, hashes = make_source_set(bad)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-priv", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(300),
            )
        for u in bad:
            del SOURCE_BODIES[u]

    def test_rejects_non_https(self):
        urls = ["http://example.com/a", "https://example.com/b"]
        hashes = ["a" * 64, "b" * 64]
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-http", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), "c" * 64,
                u256(3600), u256(300),
            )

    def test_rejects_ambiguous_or_noncanonical_authorities(self):
        malformed = (
            "https://user@ledger.news/report",
            "https://ledger.news:443/report",
            "https://ledger.news/report?version=1",
            "https://127.0.0.1/report",
            "HTTPS://ledger.news/report",
        )
        for index, bad_url in enumerate(malformed):
            urls = [bad_url, SOURCE_URLS[1]]
            hashes = ["a" * 64, digest(SOURCE_URLS[1])]
            act_as(REQUESTER, u256(10 * GEN))
            with self.assertRaises((UserError, AssertionError), msg=bad_url):
                self.contract.open_request(
                    "req-bad-" + str(index), "Question?", "GENERAL",
                    json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                    u256(3600), u256(300),
                )

    def test_rejects_wrong_bundle_hash(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-bundle", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), "0" * 64,
                u256(3600), u256(300),
            )

    def test_rejects_oversized_source_payload_before_parsing(self):
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-large", "Question?", "GENERAL",
                " " * (verity_oracle.MAX_SOURCE_URLS_JSON_CHARS + 1), "[]", "0" * 64,
                u256(3600), u256(300),
            )

    def test_rejects_duplicate_urls(self):
        dup = [SOURCE_URLS[0], SOURCE_URLS[0]]
        _, hashes = make_source_set(dup)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-dup", "Question?", "GENERAL",
                json.dumps(dup), json.dumps(hashes), bundle_hash(dup, hashes),
                u256(3600), u256(300),
            )

    def test_window_bounds_enforced(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-win", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(60), u256(300),
            )

    def test_grace_period_has_an_upper_bound(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-grace", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(31 * 24 * 3600),
            )

    def test_request_id_rejects_composite_key_delimiter(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        act_as(REQUESTER, u256(10 * GEN))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req:unsafe", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(300),
            )

    def test_min_reward_enforced(self):
        urls, hashes = make_source_set(SOURCE_URLS)
        act_as(REQUESTER, u256(1000))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.open_request(
                "req-reward", "Question?", "GENERAL",
                json.dumps(urls), json.dumps(hashes), bundle_hash(urls, hashes),
                u256(3600), u256(300),
            )


class OpenRequestTests(unittest.TestCase):
    def setUp(self):
        serve_fixtures()
        self.clock = Clock()
        self.contract = fresh_contract(self.clock)
        open_request(self.contract)

    def test_opening_records_reserves(self):
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_requests"], 1)
        self.assertEqual(totals["reserved"], 10 * GEN)
        self.assertEqual(totals["balance"], 10 * GEN)
        self.assertEqual(totals["surplus"], 0)

    def test_bond_size_is_ten_percent(self):
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["bond_size"], 1 * GEN)
        self.assertEqual(request["reward_pool"], 10 * GEN)
        self.assertEqual(request["status"], "OPEN")
        self.assertEqual(request["bundle_hash"], bundle_hash(SOURCE_URLS, [digest(u) for u in SOURCE_URLS]))

    def test_duplicate_request_id_rejected(self):
        with self.assertRaises((UserError, AssertionError)):
            open_request(self.contract, "req-001")

    def test_recent_ids_tracks_requests(self):
        open_request(self.contract, "req-002")
        ids = json.loads(self.contract.get_recent_ids())
        self.assertEqual(ids, ["req-001", "req-002"])


class ProposalTests(unittest.TestCase):
    def setUp(self):
        serve_fixtures()
        self.clock = Clock()
        self.contract = fresh_contract(self.clock)
        open_request(self.contract)

    def test_propose_locks_bond(self):
        propose(self.contract, "prop-a", "TRUE", PROPOSER_A)
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_proposals"], 1)
        self.assertEqual(totals["reserved"], 11 * GEN)
        self.assertEqual(totals["balance"], 11 * GEN)
        record = json.loads(self.contract.get_proposal("req-001", "prop-a"))
        self.assertEqual(record["answer"], "TRUE")
        self.assertEqual(record["status"], "ACTIVE")
        self.assertEqual(record["bond"], 1 * GEN)

    def test_wrong_bond_rejected(self):
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-x", "TRUE", PROPOSER_A, bond_override=2 * GEN)

    def test_citation_must_be_locked_source(self):
        with self.assertRaises((UserError, AssertionError)):
            propose(
                self.contract, "prop-x", "TRUE", PROPOSER_A,
                citations=["https://evil.xyz/fake-news"],
            )

    def test_requires_two_unique_independent_citations(self):
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-one", "TRUE", PROPOSER_A, citations=SOURCE_URLS[:1])
        with self.assertRaises((UserError, AssertionError)):
            propose(
                self.contract, "prop-dup", "TRUE", PROPOSER_A,
                citations=[SOURCE_URLS[0], SOURCE_URLS[0]],
            )

    def test_rejects_oversized_citation_payload_before_parsing(self):
        request = json.loads(self.contract.get_request("req-001"))
        act_as(PROPOSER_A, u256(request["bond_size"]))
        with self.assertRaises((UserError, AssertionError)):
            self.contract.propose_answer(
                "req-001", "prop-large", "TRUE", "A valid rationale.",
                " " * (verity_oracle.MAX_CITATIONS_JSON_CHARS + 1),
            )

    def test_proposal_id_rejects_composite_key_delimiter(self):
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop:unsafe", "TRUE", PROPOSER_A)

    def test_request_caps_total_proposals(self):
        for index in range(verity_oracle.MAX_PROPOSALS_PER_REQUEST):
            proposer = Address("0xProposer" + str(index).zfill(32))
            propose(self.contract, "prop-" + str(index).zfill(2), "TRUE", proposer)
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-over", "TRUE", PROPOSER_A)

    def test_one_active_proposal_per_address(self):
        propose(self.contract, "prop-a", "TRUE", PROPOSER_A)
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-b", "FALSE", PROPOSER_A)

    def test_duplicate_proposal_id_rejected(self):
        propose(self.contract, "prop-a", "TRUE", PROPOSER_A)
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-a", "FALSE", PROPOSER_B)

    def test_invalid_answer_rejected(self):
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-a", "MAYBE", PROPOSER_A)

    def test_proposal_after_window_rejected(self):
        self.clock.advance(10_000)
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-late", "TRUE", PROPOSER_A)

    def test_proposal_on_settled_request_rejected(self):
        set_verdict("TRUE")
        finalize(self.contract, self.clock)
        with self.assertRaises((UserError, AssertionError)):
            propose(self.contract, "prop-late", "TRUE", PROPOSER_A)


class FinalizeSettlementTests(unittest.TestCase):
    def setUp(self):
        serve_fixtures()
        self.clock = Clock()
        self.contract = fresh_contract(self.clock)
        open_request(self.contract)

    def _proposals(self):
        propose(self.contract, "prop-a", "TRUE", PROPOSER_A)
        propose(self.contract, "prop-b", "FALSE", PROPOSER_B)

    def test_finalize_before_window_rejected(self):
        act_as(OTHER)
        with self.assertRaises((UserError, AssertionError)):
            self.contract.finalize("req-001")

    def test_no_proposals_refunds_requester(self):
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["status"], "EXPIRED")
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["reserved"], 0)
        self.assertEqual(totals["balance"], 0)
        self.assertEqual(totals["total_refunded"], 10 * GEN)
        refund = [t for t in VAULT.transfers if t["to"] == REQUESTER.hex]
        self.assertEqual(len(refund), 1)
        self.assertEqual(refund[0]["amount"], 10 * GEN)

    def test_true_verdict_pays_matching_proposer(self):
        self._proposals()
        set_verdict("TRUE")
        finalize(self.contract, self.clock)

        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["status"], "RESOLVED")
        self.assertEqual(request["final_verdict"], "TRUE")
        self.assertEqual(request["winning_proposal_id"], "prop-a")

        winner = json.loads(self.contract.get_proposal("req-001", "prop-a"))
        loser = json.loads(self.contract.get_proposal("req-001", "prop-b"))
        self.assertEqual(winner["status"], "WON")
        self.assertEqual(loser["status"], "LOST")

        totals = json.loads(self.contract.get_totals())
        # payout = reward 10 + winner bond 1 + loser bond 1 = 12 GEN
        self.assertEqual(totals["total_rewards_paid"], 12 * GEN)
        self.assertEqual(totals["total_bonds_slashed"], 1 * GEN)
        self.assertEqual(totals["reserved"], 0)
        self.assertEqual(totals["balance"], 0)

        payout = [t for t in VAULT.transfers if t["to"] == PROPOSER_A.hex]
        self.assertEqual(len(payout), 1)
        self.assertEqual(payout[0]["amount"], 12 * GEN)

        result = json.loads(self.contract.get_result("req-001"))
        self.assertEqual(result["verdict"], "TRUE")
        self.assertEqual(result["winner"], PROPOSER_A.hex)
        self.assertTrue(self.contract.is_resolved("req-001"))

    def test_false_verdict_pays_matching_proposer(self):
        self._proposals()
        set_verdict("FALSE")
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["final_verdict"], "FALSE")
        self.assertEqual(request["winning_proposal_id"], "prop-b")
        payout = [t for t in VAULT.transfers if t["to"] == PROPOSER_B.hex]
        self.assertEqual(payout[0]["amount"], 12 * GEN)

    def test_verdict_with_no_matching_proposal_refunds_reward_and_slashes(self):
        propose(self.contract, "prop-a", "FALSE", PROPOSER_A)
        set_verdict("TRUE")
        finalize(self.contract, self.clock)

        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["status"], "RESOLVED")
        self.assertEqual(request["winning_proposal_id"], "")
        loser = json.loads(self.contract.get_proposal("req-001", "prop-a"))
        self.assertEqual(loser["status"], "LOST")

        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_refunded"], 10 * GEN)
        self.assertEqual(totals["total_bonds_slashed"], 1 * GEN)
        self.assertEqual(totals["balance"], 1 * GEN)  # slashed bond = surplus
        self.assertEqual(totals["surplus"], 1 * GEN)

    def test_earliest_matching_proposal_wins(self):
        propose(self.contract, "prop-a", "TRUE", PROPOSER_A)
        propose(self.contract, "prop-b", "FALSE", PROPOSER_B)
        propose(self.contract, "prop-c", "TRUE", PROPOSER_C)
        set_verdict("TRUE")
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["winning_proposal_id"], "prop-a")

    def test_weak_verdict_coerced_to_unresolvable(self):
        self._proposals()
        set_verdict("TRUE", quality=10)  # below the 40 floor
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["final_verdict"], "UNRESOLVABLE")
        for pid in ("prop-a", "prop-b"):
            proposal = json.loads(self.contract.get_proposal("req-001", pid))
            self.assertEqual(proposal["status"], "RETURNED")
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_bonds_returned"], 2 * GEN)
        self.assertEqual(totals["total_refunded"], 10 * GEN)
        self.assertEqual(totals["balance"], 0)

    def test_binary_verdict_without_citations_is_unresolvable(self):
        self._proposals()
        gl.nondet.default_verdict = {
            "verdict": "TRUE",
            "confidence_band": "HIGH",
            "evidence_quality": 95,
            "rationale": "Unsupported binary answer.",
            "citations": [],
        }
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["final_verdict"], "UNRESOLVABLE")
        self.assertEqual(request["final_citations"], [])

    def test_malformed_jury_output_is_safe_unresolvable(self):
        self._proposals()
        gl.nondet.default_verdict = {"unexpected": "output"}
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["final_verdict"], "UNRESOLVABLE")
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_bonds_returned"], 2 * GEN)
        self.assertEqual(totals["total_refunded"], 10 * GEN)

    def test_all_stakes_returned_when_sources_unavailable(self):
        # Rebuild the world with dead sources.
        WEB_FIXTURES.clear()
        for url in SOURCE_URLS:
            WEB_FIXTURES[url] = RuntimeError("connection refused")
        self._proposals()
        gl.nondet.default_verdict = {
            "verdict": "TRUE",
            "confidence_band": "HIGH",
            "evidence_quality": 90,
            "rationale": "should never be used",
            "citations": list(SOURCE_URLS),
        }
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["final_verdict"], "UNRESOLVABLE")
        manifest = request["final_manifest"]
        self.assertTrue(all(entry["status"] == "UNAVAILABLE" for entry in manifest))
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["total_bonds_returned"], 2 * GEN)
        self.assertEqual(totals["balance"], 0)

    def test_tampered_source_is_excluded_from_verdict(self):
        # One source serves tampered bytes -> HASH_MISMATCH, two stay verified.
        tampered = SOURCE_URLS[3]
        WEB_FIXTURES[tampered] = _Response(200, b"<html>tampered content</html>")
        self._proposals()
        set_verdict("TRUE", citations=SOURCE_URLS[:3])
        finalize(self.contract, self.clock)
        request = json.loads(self.contract.get_request("req-001"))
        manifest = {entry["url"]: entry for entry in request["final_manifest"]}
        self.assertEqual(manifest[tampered]["status"], "HASH_MISMATCH")
        self.assertEqual(
            sum(1 for e in manifest.values() if e["status"] == "VERIFIED"), 3
        )
        self.assertEqual(request["final_verdict"], "TRUE")

    def test_consensus_disagreement_reverts_settlement(self):
        self._proposals()
        gl.nondet.default_verdict = {
            "verdict": "TRUE",
            "confidence_band": "HIGH",
            "evidence_quality": 90,
            "rationale": "leader says TRUE",
            "citations": list(SOURCE_URLS),
        }
        # Validator independently concludes FALSE -> no consensus.
        glmod.VALIDATOR_DIVERGENCE = {
            "verdict": "FALSE",
            "confidence_band": "HIGH",
            "evidence_quality": 90,
            "rationale": "validator says FALSE",
            "citations": list(SOURCE_URLS),
        }
        self.clock.advance(10_000)
        act_as(OTHER)
        with self.assertRaises(RuntimeError):
            self.contract.finalize("req-001")
        # No settlement was recorded.
        request = json.loads(self.contract.get_request("req-001"))
        self.assertEqual(request["status"], "OPEN")
        self.assertEqual(request["winning_proposal_id"], "")
        self.assertIsNone(glmod.VALIDATOR_DIVERGENCE)

    def test_finalize_twice_rejected(self):
        self._proposals()
        set_verdict("TRUE")
        finalize(self.contract, self.clock)
        with self.assertRaises((UserError, AssertionError)):
            self.contract.finalize("req-001")


class SurplusTests(unittest.TestCase):
    def setUp(self):
        serve_fixtures()
        self.clock = Clock()
        self.contract = fresh_contract(self.clock)
        open_request(self.contract)

    def test_slashed_bonds_become_withdrawable_surplus(self):
        propose(self.contract, "prop-a", "FALSE", PROPOSER_A)
        set_verdict("TRUE")
        finalize(self.contract, self.clock)

        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["surplus"], 1 * GEN)

        act_as(REQUESTER)
        with self.assertRaises((UserError, AssertionError)):
            self.contract.withdraw_surplus(u256(1 * GEN))  # requester is not owner

        act_as(OWNER)
        self.contract.withdraw_surplus(u256(1 * GEN))
        totals = json.loads(self.contract.get_totals())
        self.assertEqual(totals["surplus"], 0)
        self.assertEqual(totals["total_surplus_withdrawn"], 1 * GEN)

    def test_cannot_withdraw_more_than_surplus(self):
        set_verdict("TRUE")
        finalize(self.contract, self.clock)
        act_as(OWNER)
        with self.assertRaises((UserError, AssertionError)):
            self.contract.withdraw_surplus(u256(100 * GEN))


class ViewTests(unittest.TestCase):
    def test_version_view(self):
        serve_fixtures()
        clock = Clock()
        contract = fresh_contract(clock)
        self.assertEqual(contract.get_version(), verity_oracle.CONTRACT_VERSION)

    def test_get_request_unknown_rejected(self):
        serve_fixtures()
        clock = Clock()
        contract = fresh_contract(clock)
        with self.assertRaises((UserError, KeyError, AssertionError)):
            contract.get_request("does-not-exist")

    def test_manifest_is_part_of_settlement_record(self):
        serve_fixtures()
        clock = Clock()
        contract = fresh_contract(clock)
        open_request(contract)
        propose(contract, "prop-a", "TRUE", PROPOSER_A)
        set_verdict("TRUE")
        finalize(contract, clock)
        request = json.loads(contract.get_request("req-001"))
        self.assertEqual(len(request["final_manifest"]), 4)
        for entry in request["final_manifest"]:
            self.assertEqual(len(entry["committed_sha256"]), 64)
            self.assertEqual(len(entry["fetched_sha256"]), 64)
            self.assertIn(entry["status"], ("VERIFIED", "HASH_MISMATCH", "UNAVAILABLE"))

        result = json.loads(contract.get_result("req-001"))
        self.assertEqual(result["citations"], sorted(SOURCE_URLS))
        self.assertEqual(result["confidence_band"], "HIGH")
        self.assertEqual(result["evidence_quality"], 80)
        self.assertEqual(len(result["decision_hash"]), 64)
        self.assertEqual(result["decision_hash"], request["final_decision_hash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
