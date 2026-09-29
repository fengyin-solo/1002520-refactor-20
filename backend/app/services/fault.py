"""信号故障业务规则：状态流转、字段校验与筛选口径都收在这里。

列表、详情、导出三个入口的字段映射、状态判断与恢复时间统一走
``app.services.fault_caliber``，不再各自维护一套取值逻辑。
"""
from __future__ import annotations

from typing import Any

from app.services import fault_caliber as caliber
from app.store import store

MODULE = "fault"
REQUIRED_FIELDS = ["故障编号", "发生时间", "故障设备"]
STATUS_ORDER = caliber.STATUS_ORDER
ACTION_RULES = caliber.ACTION_RULES
NEGATIVE_ACTIONS = []


class FaultService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("故障编号", ""))]
        if status:
            # 状态判断走统一口径，历史缺 status 的老记录也能按推断状态被筛中。
            rows = [row for row in rows if caliber.resolve_status(row) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [caliber.present_row(row) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return caliber.present_row(row)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"故障记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于信号故障可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"故障记录已{action}"
