from app.errors import InputError
from app.modules.m1_intake.amounts import cents


def parse_tiers(records):
    """与 M2 合同归一相同的阶梯校验：元边界 + 万分比整数费率。"""
    if not isinstance(records, list) or not records or len(records) > 12:
        raise InputError("BAD_REVISION", "阶梯须为 1 至 12 档")
    tiers = []
    previous = 0
    for index, row in enumerate(records):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise InputError("BAD_REVISION", "阶梯档位格式无效")
        ceiling, points = row
        if ceiling is None:
            limit = None
        else:
            try:
                limit = cents(ceiling)
            except ValueError as exc:
                raise InputError("BAD_REVISION", "阶梯边界金额无效") from exc
        if (limit is None and index != len(records) - 1) or (limit is not None and limit <= previous):
            raise InputError("BAD_REVISION", "档位边界须严格递增且末档无上限")
        if type(points) is not int or not 0 <= points <= 10000:
            raise InputError("BAD_REVISION", "费率须为万分比整数")
        tiers.append((limit, points))
        if limit is not None:
            previous = limit
    if tiers[-1][0] is not None:
        raise InputError("BAD_REVISION", "阶梯须以无上限档结束")
    return tiers


def tier_records(tiers):
    return [[limit, points] for limit, points in tiers]
