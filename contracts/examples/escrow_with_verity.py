# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""
Example consumer: a delivery escrow that settles on a Verity resolution.

This file is educational, not part of the Verity deployment. It shows how
another Intelligent Contract uses Verity as a reusable resolution primitive
through the contract interface below. The escrow never adjudicates anything
itself — it delegates truth to Verity and enforces only the deterministic
money consequence.

Flow:
  1. buyer opens an escrow, funding it and naming a Verity request that asks
     "Did the seller deliver the committed milestone?"
  2. After Verity finalizes, anyone calls settle().
  3. verdict TRUE  -> escrow pays the seller
     verdict FALSE -> escrow refunds the buyer
     UNRESOLVABLE  -> escrow stays locked (parties resolve off-chain or
                      open a new, better-sourced Verity request)
"""

from genlayer import *


@gl.evm.contract_interface
class VerityOracle:
    class View:
        def get_result(self, request_id: str) -> str:
            pass

        def is_resolved(self, request_id: str) -> bool:
            pass

    class Write:
        pass


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


class DeliveryEscrow(gl.Contract):
    buyer: Address
    seller: Address
    oracle: Address
    request_id: str
    amount: u256
    settled: bool

    def __init__(self, seller: Address, oracle: Address, request_id: str):
        self.buyer = gl.message.sender_address
        self.seller = seller
        self.oracle = oracle
        self.request_id = request_id.strip()
        self.amount = u256(0)
        self.settled = False

    @gl.public.write.payable
    def fund(self) -> None:
        assert gl.message.sender_address == self.buyer, "only buyer"
        assert not self.settled, "escrow settled"
        assert self.amount == u256(0), "escrow already funded"
        assert gl.message.value > u256(0), "fund with GEN"
        self.amount = gl.message.value

    @gl.public.write
    def settle(self) -> None:
        assert not self.settled, "escrow settled"
        assert self.amount > u256(0), "escrow not funded"

        view = VerityOracle(self.oracle).view
        assert view.is_resolved(self.request_id), "verity request not resolved"

        import json
        result = json.loads(view.get_result(self.request_id))
        verdict = result.get("verdict", "")

        if verdict == "TRUE":
            self.settled = True
            _Recipient(self.seller).emit_transfer(value=self.amount)
        elif verdict == "FALSE":
            self.settled = True
            _Recipient(self.buyer).emit_transfer(value=self.amount)
        else:
            # UNRESOLVABLE or any unknown value: keep funds locked.
            raise gl.vm.UserError("Verity returned UNRESOLVABLE; open a better-sourced request")

    @gl.public.view
    def get_escrow(self) -> str:
        import json
        return json.dumps({
            "buyer": self.buyer.as_hex,
            "seller": self.seller.as_hex,
            "oracle": self.oracle.as_hex,
            "request_id": self.request_id,
            "amount": int(self.amount),
            "settled": self.settled,
        }, sort_keys=True)
