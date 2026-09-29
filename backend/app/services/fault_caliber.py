"""信号故障统一取值口径。

字段映射、状态判断与恢复时间的处理只在此定义一次，列表、详情、导出三个入口
（以及登记/动作接口的回显）都通过 ``normalize_entry`` 读数据，保证三处口径一致。

历史数据不改写：本模块只在读取时把旧字段名、旧状态写法归一化到现行口径，
``store`` 里的原始行保持原样。
"""
from __future__ import annotations

from typing import Any

# 现行字段顺序与列表/导出列保持一致。
CANONICAL_FIELDS = [
    "故障编号",
    "发生时间",
    "故障设备",
    "故障现象",
    "影响范围",
    "恢复时间",
    "处理人员",
    "故障状态",
]

# 字段映射：现行字段名 -> 历史上出现过的别名（含早期英文/下划线写法）。
# 取值时按「现行字段名优先、别名按声明顺序兜底」取第一个非空值，全都没有则为空。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "故障编号": ("fault_no", "fault_code", "故障单号", "编号", "faultId"),
    "发生时间": ("occur_time", "occurred_at", "故障时间", "发生时刻"),
    "故障设备": ("device", "device_name", "故障器材", "设备名称"),
    "故障现象": ("phenomenon", "symptom", "故障表现", "现象描述"),
    "影响范围": ("impact_scope", "affected_area", "影响区段", "波及范围"),
    "恢复时间": ("recover_time", "recovered_at", "恢复时刻", "修复时间"),
    "处理人员": ("handler", "assignee", "维修人员", "处理人"),
    "故障状态": ("fault_status", "state_text", "状态描述"),
}

# 状态机四档，顺序即允许的流转顺序。
STATUS_ORDER = ["待确认", "已确认", "处理中", "已恢复"]
RECOVERED_STATUS = STATUS_ORDER[-1]

# 旧状态写法 -> 现行四档；归一化不了的自由文本原样保留，不强行归类。
STATUS_ALIASES: dict[str, frozenset[str]] = {
    "待确认": frozenset({"未确认", "新建", "待派单", "待处理", "pending", "todo", "0"}),
    "已确认": frozenset({"确认", "已受理", "confirmed", "1"}),
    "处理中": frozenset({"处置中", "抢修中", "正在处理", "处理", "processing", "2"}),
    "已恢复": frozenset({
        "恢复", "已解决", "已闭环", "已完成", "处理完成", "已处理完成",
        "resolved", "recovered", "closed", "done", "3",
    }),
}

# 空值口径：以下写法一律视为缺失，三个入口统一输出空值（None）。
EMPTY_TOKENS = frozenset({
    "", "-", "--", "—", "–", "－", "/", "／",
    "null", "none", "n/a", "na", "暂无", "无数据", "未填写",
})


def clean(value: Any) -> Any:
    """按统一口径清洗一个字段值：去空白、识别空值占位符；非字符串原样返回。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in EMPTY_TOKENS:
            return None
        return text
    return value


def _pick(row: dict[str, Any], field: str) -> Any:
    """现行字段名优先，其次按别名顺序取第一个非空值；缺失返回 None。"""
    value = clean(row.get(field))
    if value is not None:
        return value
    for alias in FIELD_ALIASES.get(field, ()):  # pragma: no branch - 映射表全覆盖
        value = clean(row.get(alias))
        if value is not None:
            return value
    return None


def normalize_status(raw: Any) -> str | None:
    """把内部 status 的各种写法归一化到四档状态；无法识别时保留原文；空值返回 None。"""
    text = clean(raw)
    if text is None:
        return None
    if text in STATUS_ORDER:
        return text
    for canonical, aliases in STATUS_ALIASES.items():
        if text in aliases:
            return canonical
    return text


def resolve_recovery(raw_recovery: Any) -> Any:
    """恢复时间算法（唯一一份）。

    - 有值：清洗后原样采用，不做截断或改写；
    - 空值/占位符/字段缺失：统一输出 None，不拿发生时间顶替，也不臆造时间。
    """
    return clean(raw_recovery)


def is_recovered(status: str | None, recovery: Any) -> bool:
    """状态判断（唯一一份）：只认状态机的「已恢复」档。

    恢复时间只用于展示，不参与是否恢复的判断——历史数据里未恢复的记录也可能
    预填了计划恢复时间。
    """
    return status == RECOVERED_STATUS


def normalize_entry(row: dict[str, Any]) -> dict[str, Any]:
    """把一条原始故障行按统一口径投影成对外结构。

    输出为新 dict，不改写入参；键顺序固定，与列表/导出列一致。
    """
    fields = {field: _pick(row, field) for field in CANONICAL_FIELDS}

    # 内部流转状态：旧写法归一化；缺失时回看展示用故障状态，再兜底「待确认」。
    status = normalize_status(row.get("status"))
    if status is None:
        status = normalize_status(fields["故障状态"]) or STATUS_ORDER[0]

    # 展示用故障状态：记录里已有值（含无法识别的历史文本）保持原值，缺失才取状态机结果。
    fields["故障状态"] = fields["故障状态"] or status

    recovery = resolve_recovery(fields["恢复时间"])
    fields["恢复时间"] = recovery

    recovered = is_recovered(status, recovery)

    # pending/abnormal 为历史行既有标记时保留；缺失按状态机补齐。
    pending = row.get("pending")
    if not isinstance(pending, bool):
        pending = not recovered
    abnormal = row.get("abnormal")
    if not isinstance(abnormal, bool):
        abnormal = False

    projected: dict[str, Any] = {"id": row.get("id")}
    projected["status"] = status
    projected["pending"] = pending
    projected["abnormal"] = abnormal
    projected.update(fields)
    return projected
