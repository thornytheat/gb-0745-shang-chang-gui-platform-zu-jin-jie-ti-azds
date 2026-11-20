import hashlib
import json
import re
from datetime import datetime, timezone

from app.config import RULE_VERSION
from app.errors import InputError
from app.modules.m1_intake.amounts import cents
from app.modules.m8_correction.terms import parse_tiers, tier_records

PERIOD_RE = re.compile(r"20[0-9]{2}-(?:0[1-9]|1[0-2])")


def validate_request(payload, source_run):
    if not hasattr(payload, "get"):
        raise InputError("BAD_REVISION", "更正请求字段无效")
    changes = payload.get("changes")
    if not isinstance(changes, list) or not changes or len(changes) > 50:
        raise InputError("BAD_REVISION", "至少提交一条合同更正，且不超过 50 条")
    contracts = source_run["合同版本"]
    index = {(row["柜台"], row["版本"]): row for row in contracts}
    normalized = []
    seen = set()
    for change in changes:
        if not hasattr(change, "get"):
            raise InputError("BAD_REVISION", "更正条目字段无效")
        try:
            shop = str(change["shop"]).strip()
            version = str(change["version"]).strip()
        except (KeyError, AttributeError, TypeError) as exc:
            raise InputError("BAD_REVISION", "更正条目须指定柜台与版本") from exc
        if not shop or not version:
            raise InputError("BAD_REVISION", "更正条目须指定柜台与版本")
        key = (shop, version)
        if key not in index:
            raise InputError("BAD_REVISION", f"柜台 {shop} 版本 {version} 不在源批次合同中")
        if key in seen:
            raise InputError("BAD_REVISION", "同一合同版本只能提交一条更正")
        seen.add(key)
        original = index[key]
        entry = {"柜台": shop, "版本": version}
        touched = False
        if "minimum" in change and change["minimum"] is not None:
            try:
                floor = cents(change["minimum"])
            except ValueError as exc:
                raise InputError("BAD_REVISION", "保底金额无效") from exc
            entry["新月保底分"] = floor
            if floor != original["月保底分"]:
                touched = True
        if "tiers" in change and change["tiers"] is not None:
            tiers = parse_tiers(change["tiers"])
            entry["新阶梯档"] = tier_records(tiers)
            if tier_records(tiers) != [list(row) for row in original["阶梯档"]]:
                touched = True
        if not touched:
            raise InputError("BAD_REVISION", f"柜台 {shop} 版本 {version} 的更正与原合同一致")
        normalized.append(entry)

    current_period = source_run["运行清单"]["账期"]
    effective = payload.get("effective")
    if effective in (None, ""):
        effective = min(
            datetime.fromisoformat(index[key]["起始"]).strftime("%Y-%m") for key in seen
        )
    if not isinstance(effective, str) or not PERIOD_RE.fullmatch(effective) or effective > current_period:
        raise InputError("BAD_REVISION", "生效账期须为不晚于当期的 YYYY-MM")
    earliest = min(datetime.fromisoformat(index[key]["起始"]).strftime("%Y-%m") for key in seen)
    if effective < earliest:
        raise InputError("BAD_REVISION", "生效账期不得早于所更正合同的起始月份")

    reason = payload.get("reason")
    if reason in (None, ""):
        reason = "合同费率更正"
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 200:
        raise InputError("BAD_REVISION", "更正说明须为 200 字以内的文本")
    return {
        "源批次": source_run["运行清单"]["批次"],
        "当期": current_period,
        "生效账期": effective,
        "更正说明": reason.strip(),
        "规则": RULE_VERSION,
        "更正条目": sorted(normalized, key=lambda row: (row["柜台"], row["版本"])),
    }


def revision_id(canon):
    body = json.dumps(canon, ensure_ascii=False, sort_keys=True).encode()
    return "rev-" + hashlib.sha256(body).hexdigest()[:20]


def revision_manifest(revision_id_value, canon, source_run, elapsed_ms, cross_check):
    return {
        "修订批次": revision_id_value,
        "源批次": canon["源批次"],
        "规则": canon["规则"],
        "账期": canon["当期"],
        "生效账期": canon["生效账期"],
        "更正说明": canon["更正说明"],
        "源输入摘要": source_run["运行清单"]["输入摘要"],
        "原账复核": cross_check,
        "生成时间": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "处理毫秒": elapsed_ms,
        "营业时区": "Asia/Shanghai",
    }
