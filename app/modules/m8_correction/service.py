from time import perf_counter

from app.errors import InputError
from app.modules.m8_correction.engine import correction_basis, recompute
from app.modules.m8_correction.request import revision_id, revision_manifest, validate_request


def revise_once(run_store, revision_store, payload):
    source_id = payload.get("source") if hasattr(payload, "get") else None
    source_run = run_store.get(source_id) if isinstance(source_id, str) else None
    if source_run is None:
        raise InputError("BAD_SOURCE", "源月结批次不存在，无法更正")
    canon = validate_request(payload, source_run)
    key = revision_id(canon)
    existing = revision_store.get(key)
    if existing is not None:
        return existing, True
    started = perf_counter()
    monthly, settle, totals, credits, cross_check = recompute(source_run, canon)
    revision = {
        "更正清单": revision_manifest(key, canon, source_run, round((perf_counter() - started) * 1000), cross_check),
        "更正依据": correction_basis(source_run, canon["更正条目"]),
        "分月重算": monthly,
        "承接结算": settle,
        "更正勾稽": totals,
        "更正后回冲": [
            {
                "原账期": row["原账期"],
                "柜台": row["柜台"],
                "版本": row["版本"],
                "回冲前分": row["回冲前分"],
                "回冲后分": row["回冲后分"],
                "调整分": row["调整分"],
                "退单号": row["退单号"],
            }
            for row in credits
        ],
    }
    return revision_store.save(key, revision)
