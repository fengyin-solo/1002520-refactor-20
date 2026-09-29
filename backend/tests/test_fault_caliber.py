"""信号故障统一取值口径的测试：字段映射、状态判断、恢复时间与三入口一致性。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import fault_caliber as caliber
from app.services.fault import MODULE, FaultService
from app.store import store

client = TestClient(app)


def _reset_fault_rows(rows):
    table = store.rows(MODULE)
    table.clear()
    table.extend(rows)


def test_status_prefers_canonical_status() -> None:
    row = {"status": "处理中", "故障状态": "已恢复", "恢复时间": "2026-09-01"}
    assert caliber.resolve_status(row) == "处理中"


def test_status_falls_back_to_legacy_text_then_recovery() -> None:
    legacy = {"故障状态": "已恢复", "恢复时间": "2026-09-01"}
    assert caliber.resolve_status(legacy) == "已恢复"

    recovered_by_time = {"恢复时间": "2026-09-01"}
    assert caliber.resolve_status(recovered_by_time) == "已恢复"

    assert caliber.resolve_status({}) == "待确认"


def test_recovery_time_only_for_recovered() -> None:
    pending = {"status": "待确认", "恢复时间": "2026-09-01"}
    assert caliber.resolve_recovery_time(pending) == ""

    recovered = {"status": "已恢复", "恢复时间": "2026-09-01"}
    assert caliber.resolve_recovery_time(recovered) == "2026-09-01"


def test_impact_uses_single_default_for_missing() -> None:
    assert caliber.resolve_impact({}) == caliber.DEFAULT_IMPACT
    assert caliber.resolve_impact({"影响范围": None}) == caliber.DEFAULT_IMPACT
    assert caliber.resolve_impact({"影响范围": "  "}) == caliber.DEFAULT_IMPACT
    assert caliber.resolve_impact({"影响范围": "3G 道岔"}) == "3G 道岔"


def test_field_aliases_and_null_defaults() -> None:
    row = {
        "故障编码": "FAUL-0101",
        "故障时间": "2026-08-01",
        "设备名称": "老设备",
        "影响区段": "3G",
        "销记时间": "2026-08-02",
        "维修人员": "张三",
    }
    presented = caliber.present_row(row)
    assert presented["故障编号"] == "FAUL-0101"
    assert presented["发生时间"] == "2026-08-01"
    assert presented["故障设备"] == "老设备"
    assert presented["恢复时间"] == "2026-08-02"
    assert presented["处理人员"] == "张三"
    # 缺失/空值字段统一补空串，三个入口读出来结构一致。
    assert presented["故障现象"] == ""


def test_present_row_does_not_mutate_history() -> None:
    row = {"id": 1, "故障状态": "已恢复", "恢复时间": "2026-08-02"}
    snapshot = dict(row)
    caliber.present_row(row)
    assert row == snapshot


def test_three_entrances_share_identical_rows() -> None:
    rows = [
        {"id": 1, "status": "待确认", "故障编号": "FAUL-1", "恢复时间": "2026-09-01"},
        {"id": 2, "故障编号": "FAUL-2", "故障状态": "已恢复", "恢复时间": "2026-09-02",
         "影响范围": None},
    ]
    _reset_fault_rows(rows)
    service = FaultService()

    listed, total = service.list_entries(page=1, size=100)
    exported, export_total = service.list_entries(page=1, size=10000)
    assert total == export_total == 2

    list_by_id = {row["id"]: row for row in listed}
    export_by_id = {row["id"]: row for row in exported}
    for entry_id in (1, 2):
        detail = service.get_entry(entry_id)
        assert detail == list_by_id[entry_id] == export_by_id[entry_id]


def test_status_filter_matches_inferred_history() -> None:
    rows = [
        {"id": 1, "status": "待确认", "故障编号": "FAUL-1"},
        {"id": 2, "故障编号": "FAUL-2", "故障状态": "已恢复", "恢复时间": "2026-09-02"},
        {"id": 3, "故障编号": "FAUL-3"},
    ]
    _reset_fault_rows(rows)
    service = FaultService()

    pending, pending_total = service.list_entries(status="待确认", page=1, size=100)
    assert pending_total == 2
    assert {row["故障编号"] for row in pending} == {"FAUL-1", "FAUL-3"}

    recovered, recovered_total = service.list_entries(status="已恢复", page=1, size=100)
    assert recovered_total == 1
    assert recovered[0]["恢复时间"] == "2026-09-02"


def test_export_route_is_not_shadowed_by_detail() -> None:
    response = client.get("/api/fault/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["module"] == "fault"
    assert payload["items"]


def test_http_three_entrances_render_identical_rows() -> None:
    listed = client.get("/api/fault", params={"page": 1, "size": 200}).json()["items"]
    exported = client.get("/api/fault/export").json()["items"]
    list_by_id = {row["id"]: row for row in listed}
    export_by_id = {row["id"]: row for row in exported}

    for entry_id in list_by_id:
        detail = client.get(f"/api/fault/{entry_id}").json()
        assert detail == list_by_id[entry_id] == export_by_id[entry_id]
