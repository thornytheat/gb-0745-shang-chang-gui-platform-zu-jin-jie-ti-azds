def test_workbench_and_independent_module_api(client):
    plan = {
        "intake": "隔离",
        "contracts": "合同版本",
        "calendar": "日历例外",
        "tiers": "分段核算",
        "refunds": "旧期回冲",
        "reconcile": "柜台对账",
        "publish": "运行清单",
    }
    run = client.post("/api/runs", json={"sample": "clean"}).json
    assert run["totals"]["应缴分"] == 16000
    for stage, field in plan.items():
        api = client.get(f"/api/{stage}/{run['id']}")
        assert api.status_code == 200 and field in api.json
        assert client.get(f"/work/{stage}?run={run['id']}").status_code == 200
    # M8 租金更正：页面、修订列表与一次完整更正结算
    assert client.get(f"/work/correction?run={run['id']}").status_code == 200
    assert client.get(f"/api/corrections/{run['id']}").status_code == 200
    revision = client.post(
        "/api/corrections",
        json={
            "source": run["id"],
            "changes": [
                {"shop": "001", "version": "N-A", "tiers": [["1000", 1200], [None, 2400]]}
            ],
        },
    )
    assert revision.status_code == 201
    revision_id = revision.json["id"]
    assert client.get(f"/api/correction/{revision_id}").status_code == 200
    assert (
        client.get(f"/work/correction?run={run['id']}&revision={revision_id}").status_code
        == 200
    )
    assert client.get(f"/api/export/{revision_id}").status_code == 200


def test_bulk_sources_have_different_totals(client):
    clean = client.post("/api/runs", json={"sample": "clean"}).json
    dirty = client.post("/api/runs", json={"sample": "mall"}).json
    assert dirty["totals"]["应缴分"] > clean["totals"]["应缴分"]
    assert dirty["balance"]["差额行"] == 0
    assert clean["balance"]["隔离"] == 0 < dirty["balance"]["隔离"]
