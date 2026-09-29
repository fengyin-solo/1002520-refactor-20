"""信号故障统一取值口径。

列表（GET /api/fault）、详情（GET /api/fault/{id}）、导出（GET /api/fault/export）
三个入口共用本模块的同一份逻辑：

- 字段映射：历史数据里的中文字段名与规范字段在这里集中映射；
- 状态判断：规范 status 缺失时，按历史字段与恢复时间兜底推断；
- 恢复时间：只有判定为「已恢复」的故障才认定恢复时间，其余一律按未恢复处理；
- 空值默认：缺失字段统一补空串，三个入口不会再各写一套默认值。

本模块只做「读口径」，不会改写仓储里的历史数据；历史记录经 present_row 读出来
即可得到与新数据一致的结构。
"""
from __future__ import annotations

from typing import Any

# 故障状态流转序列，同时是状态判断的唯一取值表。
STATUS_ORDER = ["待确认", "已确认", "处理中", "已恢复"]
RECOVERED_STATUS = STATUS_ORDER[-1]

# 动作到目标状态的映射，与 STATUS_ORDER 保持同一份口径。
ACTION_RULES = {"确认故障": "已确认", "开始处理": "处理中", "确认恢复": "已恢复"}

# 列表/详情/导出统一对外的业务字段（不含 id、status 等系统字段）。
DISPLAY_FIELDS = ["故障编号", "发生时间", "故障设备", "故障现象", "影响范围", "恢复时间", "处理人员", "故障状态"]

# 历史数据字段别名：老记录里可能用这些名字落库，读取时统一映射到规范字段。
FIELD_ALIASES: dict[str, list[str]] = {
    "故障编号": ["故障编号", "故障编码", "编号"],
    "发生时间": ["发生时间", "故障时间", "发生时刻"],
    "故障设备": ["故障设备", "设备名称", "设备"],
    "故障现象": ["故障现象", "现象", "故障描述"],
    "影响范围": ["影响范围", "影响区段", "影响"],
    "恢复时间": ["恢复时间", "恢复时刻", "销记时间"],
    "处理人员": ["处理人员", "处理人", "维修人员"],
    "故障状态": ["故障状态", "状态文本", "状态"],
}

# 空值/缺失字段统一按空串对外，三个入口保持一致。
DEFAULT_TEXT = ""
DEFAULT_IMPACT = "暂无影响范围记录"
DEFAULT_RECOVERY = ""


def _text(row: dict[str, Any], field: str) -> Any:
    """按别名顺序取字段值；null、空串、纯空白都视为缺失。"""
    for name in FIELD_ALIASES[field]:
        if name in row:
            value = row.get(name)
            if value is None:
                return DEFAULT_TEXT
            text = str(value).strip()
            return text if text else DEFAULT_TEXT
    return DEFAULT_TEXT


def resolve_status(row: dict[str, Any]) -> str:
    """推断故障状态：规范 status 优先，历史「故障状态」字段与恢复时间兜底。

    推断只发生在读的时候，仓储里的原始字段保持不变。
    """
    status = row.get("status")
    if isinstance(status, str) and status.strip() in STATUS_ORDER:
        return status.strip()

    legacy = _text(row, "故障状态")
    if legacy in STATUS_ORDER:
        return legacy

    # 历史记录没有可用状态时：登记了恢复时间视为已恢复，否则按最初的待确认处理。
    if _text(row, "恢复时间"):
        return RECOVERED_STATUS
    return STATUS_ORDER[0]


def resolve_recovery_time(row: dict[str, Any]) -> Any:
    """恢复时间口径：只有已恢复故障才输出恢复时间，未恢复一律为空串。"""
    if resolve_status(row) != RECOVERED_STATUS:
        return DEFAULT_RECOVERY
    return _text(row, "恢复时间")


def resolve_impact(row: dict[str, Any]) -> Any:
    """影响范围口径：缺失或留空时给统一占位说明，三个入口保持同一结果。"""
    value = _text(row, "影响范围")
    return value if value else DEFAULT_IMPACT


def present_row(row: dict[str, Any]) -> dict[str, Any]:
    """把仓储原始记录按统一口径投影成对外记录。

    系统字段（id/status/pending/abnormal）原样保留；业务字段统一按
    DISPLAY_FIELDS 的顺序补齐，历史缺字段的老记录也能读出完整结构。
    """
    presented: dict[str, Any] = {}
    for key, value in row.items():
        if key not in DISPLAY_FIELDS:
            presented[key] = value
    presented["status"] = resolve_status(row)

    for field in DISPLAY_FIELDS:
        if field == "影响范围":
            presented[field] = resolve_impact(row)
        elif field == "恢复时间":
            presented[field] = resolve_recovery_time(row)
        elif field == "故障状态":
            # 「故障状态」是历史遗留的展示列；缺失时与规范 status 保持同步，
            # 已有的历史文本（如样例数据）原样保留，保证导出逐行对得上。
            presented[field] = _text(row, field) or presented["status"]
        else:
            presented[field] = _text(row, field)
    return presented
