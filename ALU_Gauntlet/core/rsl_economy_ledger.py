"""Idempotent RSL Coin ledger shared by every earn/spend path.

Every event gets a deterministic transaction reference so retries cannot award
or charge the same event twice. MongoDB transactions are used when the backing
database exposes a client, so a crash cannot leave a balance change separated
from its ledger record.
"""
from __future__ import annotations

import time
import hashlib


def _result(existing: dict, transaction_id: str) -> dict:
    status = str(existing.get("status") or "").casefold()
    if status != "completed":
        return {
            "ok": False,
            "duplicate": True,
            "reason": "transaction_pending",
            "amount": int(existing.get("amount", 0) or 0),
            "balance_after": existing.get("balance_after"),
            "transaction_id": transaction_id,
        }
    return {
        "ok": True,
        "duplicate": True,
        "amount": int(existing.get("amount", 0) or 0),
        "balance_after": existing.get("balance_after"),
        "transaction_id": transaction_id,
    }


async def _apply_without_transaction(
    db,
    *,
    transaction_id: str,
    guild_id: str,
    user_id: str,
    amount: int,
    transaction_type: str,
    reference_id: str,
    reason: str,
    metadata: dict | None,
) -> dict:
    """Compatibility fallback for lightweight DB wrappers without sessions."""
    now = time.time()
    try:
        await db.rsl_economy_transactions.insert_one({
            "_id": transaction_id,
            "guild_id": guild_id,
            "user_id": user_id,
            "type": str(transaction_type),
            "reference_id": reference_id,
            "reason": str(reason),
            "amount": amount,
            "status": "pending",
            "created_at": now,
            "metadata": metadata or {},
        })
    except Exception:
        existing = await db.rsl_economy_transactions.find_one({"_id": transaction_id})
        if existing:
            return _result(existing, transaction_id)
        raise

    query = {"_id": f"{guild_id}_{user_id}"}
    if amount < 0:
        query["rsl_coins"] = {"$gte": abs(amount)}
    marker = hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()
    result = await db.drivers.update_one(
        query,
        {
            "$inc": {"rsl_coins": amount},
            "$set": {f"rsl_coin_ledger_markers.{marker}": now},
        },
    )
    if getattr(result, "modified_count", 0) != 1:
        await db.rsl_economy_transactions.delete_one({"_id": transaction_id})
        return {
            "ok": False,
            "reason": "insufficient_coins_or_profile_missing",
            "transaction_id": transaction_id,
        }

    profile = await db.drivers.find_one(
        {"_id": f"{guild_id}_{user_id}"},
        {"rsl_coins": 1},
    )
    balance_after = int((profile or {}).get("rsl_coins", 0) or 0)
    await db.rsl_economy_transactions.update_one(
        {"_id": transaction_id},
        {"$set": {
            "status": "completed",
            "balance_after": balance_after,
            "completed_at": time.time(),
        }},
    )
    return {
        "ok": True,
        "duplicate": False,
        "amount": amount,
        "balance_after": balance_after,
        "transaction_id": transaction_id,
    }


async def reconcile_pending_coin_transactions(db, *, guild_id: str, limit: int = 500) -> dict:
    """Recover non-transactional pending coin ledger rows safely."""
    gid = str(guild_id)
    repaired = skipped = failed = 0
    cursor = db.rsl_economy_transactions.find(
        {"guild_id": gid, "status": "pending"}
    ).sort("created_at", 1).limit(max(1, min(1000, int(limit))))
    async for row in cursor:
        transaction_id = str(row.get("_id") or "")
        user_id = str(row.get("user_id") or "")
        if not transaction_id or not user_id:
            failed += 1
            continue
        marker = hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()
        profile = await db.drivers.find_one(
            {"_id": f"{gid}_{user_id}"},
            {"rsl_coins": 1, f"rsl_coin_ledger_markers.{marker}": 1},
        )
        if not profile:
            failed += 1
            continue
        markers = profile.get("rsl_coin_ledger_markers") or {}
        if marker not in markers:
            try:
                result = await _apply_without_transaction(
                    db,
                    transaction_id=transaction_id,
                    guild_id=gid,
                    user_id=user_id,
                    amount=int(row.get("amount", 0) or 0),
                    transaction_type=str(row.get("type") or "recovery"),
                    reference_id=str(row.get("reference_id") or ""),
                    reason=str(row.get("reason") or "Recovered pending RSL coin transaction"),
                    metadata=row.get("metadata") or {},
                )
                if result.get("ok"):
                    repaired += 1
                else:
                    skipped += 1
            except Exception:
                failed += 1
            continue
        balance_after = int(profile.get("rsl_coins", 0) or 0)
        result = await db.rsl_economy_transactions.update_one(
            {"_id": transaction_id, "status": "pending"},
            {"$set": {"status": "completed", "balance_after": balance_after, "completed_at": time.time()}},
        )
        if getattr(result, "modified_count", 0) == 1:
            repaired += 1
        else:
            skipped += 1
    return {"repaired": repaired, "skipped": skipped, "failed": failed}


async def apply_coin_transaction(
    db,
    *,
    guild_id: str,
    user_id: str,
    amount: int,
    transaction_type: str,
    reference_id: str,
    reason: str,
    metadata: dict | None = None,
) -> dict:
    guild_id, user_id = str(guild_id), str(user_id)
    amount = int(amount)
    reference_id = str(reference_id)
    transaction_id = f"{guild_id}:{user_id}:{reference_id}"

    existing = await db.rsl_economy_transactions.find_one({"_id": transaction_id})
    if existing:
        return _result(existing, transaction_id)

    client = getattr(db, "client", None)
    if client is None:
        return await _apply_without_transaction(
            db,
            transaction_id=transaction_id,
            guild_id=guild_id,
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            reason=reason,
            metadata=metadata,
        )

    now = time.time()
    document = {
        "_id": transaction_id,
        "guild_id": guild_id,
        "user_id": user_id,
        "type": str(transaction_type),
        "reference_id": reference_id,
        "reason": str(reason),
        "amount": amount,
        "status": "pending",
        "created_at": now,
        "metadata": metadata or {},
    }
    profile_id = f"{guild_id}_{user_id}"

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.rsl_economy_transactions.insert_one(document, session=session)

                query = {"_id": profile_id}
                if amount < 0:
                    query["rsl_coins"] = {"$gte": abs(amount)}
                result = await db.drivers.update_one(
                    query,
                    {"$inc": {"rsl_coins": amount}},
                    session=session,
                )
                if getattr(result, "modified_count", 0) != 1:
                    raise ValueError("insufficient_coins_or_profile_missing")

                profile = await db.drivers.find_one(
                    {"_id": profile_id},
                    {"rsl_coins": 1},
                    session=session,
                )
                balance_after = int((profile or {}).get("rsl_coins", 0) or 0)
                await db.rsl_economy_transactions.update_one(
                    {"_id": transaction_id},
                    {"$set": {
                        "status": "completed",
                        "balance_after": balance_after,
                        "completed_at": time.time(),
                    }},
                    session=session,
                )
    except ValueError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "transaction_id": transaction_id,
        }
    except Exception:
        existing = await db.rsl_economy_transactions.find_one({"_id": transaction_id})
        if existing:
            return _result(existing, transaction_id)
        raise

    return {
        "ok": True,
        "duplicate": False,
        "amount": amount,
        "balance_after": balance_after,
        "transaction_id": transaction_id,
    }


async def recent_coin_transactions(
    db,
    *,
    guild_id: str,
    user_id: str,
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(50, int(limit)))
    return await (
        db.rsl_economy_transactions.find(
            {
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "status": "completed",
            },
            {
                "_id": 0,
                "type": 1,
                "reference_id": 1,
                "reason": 1,
                "amount": 1,
                "balance_after": 1,
                "created_at": 1,
                "metadata": 1,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
        .to_list(length=limit)
    )
