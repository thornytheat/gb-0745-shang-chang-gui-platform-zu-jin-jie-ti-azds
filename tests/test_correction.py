from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.errors import InputError
from app.modules.m7_publish.service import run_once
from app.modules.m8_correction.service import revise_once
from app.modules.m8_correction.store import RevisionStore
from app.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path):
    return RunStore(tmp_path / "runs.sqlite"), RevisionStore(tmp_path / "revisions.sqlite")


def _clean_run(tmp_path):
    runs, _ = _store(tmp_path)
    raw = (ROOT / "sample_data" / "clean.json").read_bytes()
    run, _ = run_once(runs, raw, "2026-11")
    return runs, run


def test_rate_correction_recomputes_every_month_and_carries_carry(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    revision, reused = revise_once(
        runs,
        revisions,
        {
            "source": run["运行清单"]["批次"],
            "changes": [
                {"shop": "001", "version": "N-A", "tiers": [["1000", 1200], [None, 2400]]}
            ],
        },
    )
    assert reused is False
    assert revision["更正清单"]["原账复核"] == "一致"
    assert [(row["账期"], row["原账分"], row["更正后分"], row["月差额分"]) for row in revision["分月重算"]] == [
        ("2026-10", 13000, 15600, 2600),
        ("2026-11", 18000, 21600, 3600),
    ]
    # 当月行回链源批次，历史月不回链
    assert [row["源批次分"] for row in revision["分月重算"]] == [None, 18000]
    settle = revision["承接结算"][0]
    assert (
        settle["历史月差额分"],
        settle["本期应计差额分"],
        settle["回冲差额分"],
        settle["承接差额分"],
    ) == (2600, 3600, -400, 5800)
    assert settle["原应缴分"] == 16000 and settle["更正后应缴分"] == 21800
    assert settle["实缴分"] == 16000 and settle["收缴差额分"] == 5800 and settle["对账"] == "应补"
    totals = revision["更正勾稽"]
    assert totals["更正后应缴分"] - totals["原应缴分"] == totals["承接差额分"]
    assert totals["更正后应缴分"] == totals["实缴分"] + totals["收缴差额分"] + totals["缺单应缴分"]


def test_original_contract_basis_kept_before_and_after(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    revision, _ = revise_once(
        runs,
        revisions,
        {
            "source": run["运行清单"]["批次"],
            "changes": [
                {
                    "shop": "001",
                    "version": "N-A",
                    "minimum": "200",
                    "tiers": [["1000", 1200], [None, 2400]],
                }
            ],
        },
    )
    basis = revision["更正依据"][0]
    assert basis["原月保底分"] == 0 and basis["新月保底分"] == 20000
    assert basis["原阶梯档"] == [[100000, 1000], [None, 2000]]
    assert basis["新阶梯档"] == [[100000, 1200], [None, 2400]]
    # 源批次合同仍是原费率、原保底，历史记录不被改写
    source = runs.get(run["运行清单"]["批次"])
    assert source["合同版本"][0]["阶梯档"] == [[100000, 1000], [None, 2000]]
    assert source["合同版本"][0]["月保底分"] == 0


def test_revision_is_idempotent_and_concurrency_safe(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    payload = {
        "source": run["运行清单"]["批次"],
        "changes": [{"shop": "001", "version": "N-A", "minimum": "90"}],
    }
    first, reused_first = revise_once(runs, revisions, payload)
    second, reused_second = revise_once(runs, revisions, payload)
    assert reused_first is False and reused_second is True
    assert first["更正清单"]["修订批次"] == second["更正清单"]["修订批次"]
    assert len(revisions.history()) == 1
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: revise_once(runs, revisions, payload), range(5)))
    assert sum(not reused for _, reused in results) == 0
    assert len(revisions.history()) == 1


def test_failed_generation_keeps_previous_revision(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    good = {
        "source": run["运行清单"]["批次"],
        "changes": [{"shop": "001", "version": "N-A", "minimum": "90"}],
    }
    revise_once(runs, revisions, good)
    for bad in (
        {"source": run["运行清单"]["批次"], "changes": [{"shop": "001", "version": "N-A"}]},
        {
            "source": run["运行清单"]["批次"],
            "changes": [{"shop": "999", "version": "N-A", "minimum": "10"}],
        },
        {
            "source": run["运行清单"]["批次"],
            "changes": [{"shop": "001", "version": "N-A", "tiers": [["1000", 99999]]}],
        },
        {
            "source": run["运行清单"]["批次"],
            "effective": "2026-12",
            "changes": [{"shop": "001", "version": "N-A", "minimum": "10"}],
        },
    ):
        with pytest.raises(InputError):
            revise_once(runs, revisions, bad)
    assert len(revisions.history()) == 1


def test_effective_month_limits_recomputed_span(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    revision, _ = revise_once(
        runs,
        revisions,
        {
            "source": run["运行清单"]["批次"],
            "effective": "2026-11",
            "changes": [{"shop": "001", "version": "N-A", "minimum": "90"}],
        },
    )
    assert {row["账期"] for row in revision["分月重算"]} == {"2026-11"}
    assert revision["承接结算"][0]["历史月差额分"] == 0


def test_floor_only_correction_on_mall_and_missing_statement(tmp_path):
    runs = RunStore(tmp_path / "runs.sqlite")
    raw = (ROOT / "sample_data" / "mall.json").read_bytes()
    run, _ = run_once(runs, raw, "2026-11")
    revisions = RevisionStore(tmp_path / "v.sqlite")
    revision, _ = revise_once(
        runs,
        revisions,
        {
            "source": run["运行清单"]["批次"],
            "changes": [{"shop": "002", "version": "N-B", "minimum": "360"}],
        },
    )
    assert revision["更正清单"]["原账复核"] == "一致"
    shop_002 = next(row for row in revision["承接结算"] if row["柜台"] == "002")
    assert shop_002["承接差额分"] == 2600
    assert shop_002["更正后应缴分"] == 15600 and shop_002["实缴分"] == 0
    # 缺缴款单柜台沿用源批次状态
    shop_003 = next(row for row in revision["承接结算"] if row["柜台"] == "003")
    assert shop_003["对账"] == "缺缴款单" and shop_003["实缴分"] is None
    assert shop_003["收缴差额分"] is None


def test_correction_api_and_single_export(client, tmp_path):
    created = client.post("/api/runs", json={"sample": "clean"})
    source_id = created.json["id"]
    payload = {
        "source": source_id,
        "changes": [{"shop": "001", "version": "N-A", "tiers": [["1000", 1200], [None, 2400]]}],
    }
    first = client.post("/api/corrections", json=payload)
    second = client.post("/api/corrections", json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json["id"] == second.json["id"] and second.json["reused"] is True
    revision_id = first.json["id"]

    listing = client.get(f"/api/corrections/{source_id}")
    assert listing.status_code == 200 and listing.json[0]["修订批次"] == revision_id
    detail = client.get(f"/api/correction/{revision_id}")
    assert detail.status_code == 200 and "分月重算" in detail.json

    page = client.get(f"/work/correction?run={source_id}&revision={revision_id}")
    assert page.status_code == 200 and "下载更正凭证" in page.get_data(as_text=True)

    # 同一导出端点、同一种 JSON 凭证，不引入第二种导出
    run_export = client.get(f"/api/export/{source_id}")
    revision_export = client.get(f"/api/export/{revision_id}")
    assert run_export.status_code == revision_export.status_code == 200
    assert run_export.mimetype == revision_export.mimetype == "application/json"
    assert revision_export.json["更正清单"]["修订批次"] == revision_id

    # 失败请求不落库
    before = len(client.get(f"/api/corrections/{source_id}").json)
    bad = client.post(
        "/api/corrections",
        json={"source": source_id, "changes": [{"shop": "001", "version": "N-A"}]},
    )
    after = len(client.get(f"/api/corrections/{source_id}").json)
    assert bad.status_code == 422 and before == after

    missing = client.post(
        "/api/corrections",
        json={"source": "unknown", "changes": [{"shop": "001", "version": "N-A", "minimum": "1"}]},
    )
    assert missing.status_code == 404 and missing.json["code"] == "BAD_SOURCE"


def test_reason_and_default_effective_month(tmp_path):
    runs, run = _clean_run(tmp_path)
    revisions = RevisionStore(tmp_path / "v.sqlite")
    revision, _ = revise_once(
        runs,
        revisions,
        {
            "source": run["运行清单"]["批次"],
            "reason": "  十一月补签费率调整  ",
            "changes": [{"shop": "001", "version": "N-A", "minimum": "90"}],
        },
    )
    manifest = revision["更正清单"]
    assert manifest["更正说明"] == "十一月补签费率调整"
    assert manifest["生效账期"] == "2026-10"  # 合同 N-A 起始月
    assert manifest["源批次"] == run["运行清单"]["批次"]
    assert manifest["源输入摘要"] == run["运行清单"]["输入摘要"]
