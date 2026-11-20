from collections import Counter
from datetime import date

from app.modules.m4_tiers.service import calculate_period
from app.modules.m5_refunds.credits import deduction_map
from app.modules.m5_refunds.service import previous_period_credits
from app.modules.m3_calendar.month import month_window


def month_iter(first, last):
    year, month = (int(part) for part in first.split("-"))
    last_year, last_month = (int(part) for part in last.split("-"))
    while (year, month) <= (last_year, last_month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return


def rebuild_inputs(source_run):
    sales = {}
    for row in source_run["收银行"]:
        sales[row["流水号"]] = {
            "id": row["流水号"],
            "shop": row["柜台"],
            "day": date.fromisoformat(row["销售日"]),
            "cents": row["销售分"],
            "version": row["版本"],
            "line": row["行号"],
        }
    refunds = []
    for row in source_run["退单证据"]:
        origin = sales[row["原单号"]]
        refunds.append(
            {
                "id": row["流水号"],
                "shop": row["柜台"],
                "day": date.fromisoformat(row["入账日"]),
                "cents": row["退单分"],
                "origin": row["原单号"],
                "source_period": origin["day"].isoformat()[:7],
                "line": row["行号"],
            }
        )
    exempt = {
        (row["柜台"], date.fromisoformat(row["日期"]))
        for row in source_run["日历例外"]
        if row["状态"] == "免保底"
    }
    contracts = [
        {
            "shop": row["柜台"],
            "version": row["版本"],
            "start": date.fromisoformat(row["起始"]),
            "end": date.fromisoformat(row["截止"]),
            "floor": row["月保底分"],
            "tiers": [tuple(band) for band in row["阶梯档"]],
        }
        for row in source_run["合同版本"]
    ]
    statement = {row["柜台"]: row["实缴分"] for row in source_run["柜台对账"]}
    source_due = {row["柜台"]: row["应缴分"] for row in source_run["柜台对账"]}
    return sales, refunds, exempt, contracts, statement, source_due


def apply_corrections(contracts, changes):
    override = {(row["柜台"], row["版本"]): row for row in changes}
    corrected = []
    for contract in contracts:
        key = (contract["shop"], contract["version"])
        if key not in override:
            corrected.append(dict(contract))
            continue
        change = override[key]
        corrected.append(
            {
                **contract,
                "floor": change.get("新月保底分", contract["floor"]),
                "tiers": (
                    [tuple(band) for band in change["新阶梯档"]]
                    if "新阶梯档" in change
                    else contract["tiers"]
                ),
            }
        )
    return corrected


def bill_map(rows):
    return {(row["柜台"], row["版本"]): row["应计分"] for row in rows}


def credit_map(credit_rows):
    grouped = Counter()
    for row in credit_rows:
        grouped[(row["柜台"], row["版本"])] += row["调整分"]
    return grouped


def recompute(source_run, canon):
    sales, refunds, exempt, contracts, statement, source_due = rebuild_inputs(source_run)
    corrected_contracts = apply_corrections(contracts, canon["更正条目"])
    current_period = canon["当期"]
    cur_start, cur_end = month_window(current_period)

    source_current = bill_map(source_run["分段核算"])
    source_credits = credit_map(source_run["旧期回冲"])

    monthly_rows = []
    history_delta = Counter()
    current_accrual_delta = Counter()
    cross_check = "一致"
    for period in month_iter(canon["生效账期"], current_period):
        _, end = month_window(period)
        deductions = deduction_map(refunds, end)
        original = bill_map(calculate_period(sales, deductions, contracts, exempt, period)[0])
        corrected = bill_map(
            calculate_period(sales, deductions, corrected_contracts, exempt, period)[0]
        )
        if period == current_period and original != source_current:
            cross_check = "不一致"
        for key in sorted(original.keys() | corrected.keys()):
            old_value, new_value = original.get(key, 0), corrected.get(key, 0)
            monthly_rows.append(
                {
                    "账期": period,
                    "柜台": key[0],
                    "版本": key[1],
                    "原账分": old_value,
                    "更正后分": new_value,
                    "月差额分": new_value - old_value,
                    "源批次分": source_current.get(key) if period == current_period else None,
                }
            )
            if period < current_period:
                history_delta[key[0]] += new_value - old_value
            else:
                current_accrual_delta[key[0]] += new_value - old_value

    original_credits = previous_period_credits(
        sales, refunds, contracts, exempt, cur_start, cur_end
    )
    corrected_credits = previous_period_credits(
        sales, refunds, corrected_contracts, exempt, cur_start, cur_end
    )
    if credit_map(original_credits) != source_credits:
        cross_check = "不一致"
    credit_delta = Counter()
    for key in set(credit_map(original_credits)) | set(credit_map(corrected_credits)):
        credit_delta[key[0]] += (
            credit_map(corrected_credits).get(key, 0) - credit_map(original_credits).get(key, 0)
        )

    shops = sorted(
        set(statement)
        | set(source_due)
        | {row["柜台"] for row in monthly_rows}
        | {row["柜台"] for row in corrected_credits}
    )
    settle_rows = []
    for shop in shops:
        carry = history_delta[shop] + current_accrual_delta[shop] + credit_delta[shop]
        original_due = source_due.get(shop, 0)
        paid = statement.get(shop)
        corrected_due = original_due + carry
        difference = corrected_due - paid if paid is not None else None
        status = (
            "缺缴款单"
            if paid is None
            else "应补"
            if difference > 0
            else "应退"
            if difference < 0
            else "已平"
        )
        settle_rows.append(
            {
                "柜台": shop,
                "历史月差额分": history_delta[shop],
                "本期应计差额分": current_accrual_delta[shop],
                "回冲差额分": credit_delta[shop],
                "承接差额分": carry,
                "原应缴分": original_due,
                "更正后应缴分": corrected_due,
                "实缴分": paid,
                "收缴差额分": difference,
                "对账": status,
            }
        )

    totals = {
        "原应缴分": sum(row["原应缴分"] for row in settle_rows),
        "更正后应缴分": sum(row["更正后应缴分"] for row in settle_rows),
        "承接差额分": sum(row["承接差额分"] for row in settle_rows),
        "实缴分": sum(row["实缴分"] for row in settle_rows if row["实缴分"] is not None),
        "收缴差额分": sum(row["收缴差额分"] for row in settle_rows if row["收缴差额分"] is not None),
        "缺单应缴分": sum(
            row["更正后应缴分"] for row in settle_rows if row["实缴分"] is None
        ),
    }
    return monthly_rows, settle_rows, totals, corrected_credits, cross_check


def correction_basis(source_run, changes):
    index = {(row["柜台"], row["版本"]): row for row in source_run["合同版本"]}
    basis = []
    for change in changes:
        key = (change["柜台"], change["版本"])
        original = index[key]
        basis.append(
            {
                "柜台": key[0],
                "版本": key[1],
                "原月保底分": original["月保底分"],
                "新月保底分": change.get("新月保底分"),
                "原阶梯档": [list(band) for band in original["阶梯档"]],
                "新阶梯档": change.get("新阶梯档"),
            }
        )
    return basis
