"""Deterministic bank file replay/revision detection; keep state in your own ledger."""

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class FileReceipt:
    """Audit metadata only; never put raw account/transaction data in a receipt."""

    message_type: str
    message_id: str
    content_sha256: str
    bytes_read: int


@dataclass(frozen=True)
class ReplayDecision:
    receipt: FileReceipt
    decision: str  # NEW | EXACT_REPLAY | CONFLICTING_MESSAGE_ID


def file_receipt(data: bytes, *, message_type: str, message_id: str) -> FileReceipt:
    if not isinstance(data, bytes):
        raise TypeError("Content must be bytes for a deterministic exact-file digest")
    if not message_type or not message_id:
        raise ValueError("Both message type and nonempty business message ID are required")
    return FileReceipt(message_type, message_id, sha256(data).hexdigest(), len(data))


def detect_replays(
    receipts: Iterable[FileReceipt], historical: Iterable[FileReceipt] = ()
) -> tuple[ReplayDecision, ...]:
    """Flag exact replays and a revised file with the same (message_type, MsgId).

    The caller must persist receipts transactionally with its Delta write; this
    function does not claim atomic exactly-once processing by itself.
    """
    hashes = set()
    ids: dict[tuple[str, str], set[str]] = {}
    for prior in historical:
        hashes.add((prior.message_type, prior.content_sha256))
        ids.setdefault((prior.message_type, prior.message_id), set()).add(prior.content_sha256)
    decisions = []
    for receipt in receipts:
        ident = (receipt.message_type, receipt.message_id)
        digest = (receipt.message_type, receipt.content_sha256)
        if digest in hashes:
            decision = "EXACT_REPLAY"
        elif ident in ids:
            decision = "CONFLICTING_MESSAGE_ID"
        else:
            decision = "NEW"
        decisions.append(ReplayDecision(receipt, decision))
        hashes.add(digest)
        ids.setdefault(ident, set()).add(receipt.content_sha256)
    return tuple(decisions)
