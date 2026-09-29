"""信号故障业务规则：状态流转、字段校验与筛选口径都收在这里。

列表、详情、导出的取值统一走 ``fault_caliber``，三个入口不再各写一遍。
"""
from __future__ import annotations

from typing import Any

from app.store import store

from app.services.fault_caliber import (
    STATUS_ORDER,
    normalize_entry,
    normalize_status,
)

MODULE = "fault"
REQUIRED_FIELDS = ["故障编号", "发生时间", "故障设备"]
ACTION_RULES = {"确认故障": "已确认", "开始处理": "处理中", "确认恢复": "已恢复"}
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
        # 先按统一口径归一化，再过滤/分页：旧字段名、旧状态写法的历史行
        # 也能按新口径被检索与筛选，且三个入口的影响范围等字段完全一致。
        rows = [normalize_entry(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("故障编号") or "")]
        if status:
            target = normalize_status(status) or status
            rows = [row for row in rows if row.get("status") == target]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return normalize_entry(row) if row is not None else None

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
