"""Luật phân mức + playbook ứng phó + SLA (có version, tái lập được; KHÔNG do LLM quyết).

Mọi giá trị là tham số MÔ PHỎNG cho prototype — sẽ được nhà vận hành hiệu chỉnh khi pilot.
"""
RULE_VERSION = "sev-v1"
PLAYBOOK_VERSION = "pb-v1"

CATEGORIES = ("ETA_CHANGED", "DELAY_RISK", "BREAKDOWN", "TRAFFIC_INCIDENT", "DOCK_CONGESTION", "NO_SHOW", "CARGO_DAMAGE", "DATA_STALE")
SEVERITIES = ("low", "medium", "high", "critical")
SLA_MINUTES = {"critical": 15, "high": 30, "medium": 60, "low": 120}  # hạn xử lý theo mức; quá hạn → leo thang

DELAY_THRESHOLDS = ((90, "critical"), (45, "high"), (15, "medium"))  # (phút trễ ≥, mức)


def severity_for(category: str, detail: dict) -> str:
    """Mức độ theo luật. Trễ dựa trên số phút; nguy cơ lỡ cut-off luôn critical; hỏng xe critical; hàng hư high."""
    if category in ("ETA_CHANGED", "TRAFFIC_INCIDENT", "DELAY_RISK", "DOCK_CONGESTION"):
        if detail.get("cutoff_risk"):
            return "critical"
        d = int(detail.get("delay_minutes") or 0)
        for limit, sev in DELAY_THRESHOLDS:
            if d >= limit:
                return sev
        return "medium" if category in ("DELAY_RISK", "TRAFFIC_INCIDENT") else "low"
    return {"BREAKDOWN": "critical", "CARGO_DAMAGE": "high", "NO_SHOW": "high", "DATA_STALE": "medium"}.get(category, "medium")


# Playbook: danh sách bước (key, loại auto|human, chủ trách nhiệm). Bước auto chạy ngay khi mở ngoại lệ;
# bước human do bên có quyền hoàn tất — hệ thống KHÔNG tự đổi xe/chuyến đã cam kết.
PLAYBOOKS: dict[str, list[tuple[str, str, str]]] = {
    "ETA_CHANGED": [("notify_parties", "auto", "system"), ("confirm_new_eta", "human", "carrier"), ("decide_delay_or_replan", "human", "shipper")],
    "DELAY_RISK": [("notify_parties", "auto", "system"), ("expedite_or_confirm", "human", "carrier"), ("decide_delay_or_replan", "human", "shipper")],
    "BREAKDOWN": [("notify_parties", "auto", "system"), ("dispatch_replacement", "human", "carrier"), ("decide_delay_or_replan", "human", "shipper"),
                  ("coordinate", "human", "dispatcher")],
    "TRAFFIC_INCIDENT": [("notify_parties", "auto", "system"), ("confirm_reroute", "human", "carrier"), ("monitor", "human", "dispatcher")],
    "DOCK_CONGESTION": [("notify_parties", "auto", "system"), ("reschedule_dock", "human", "node"), ("confirm_new_window", "human", "carrier")],
    "NO_SHOW": [("notify_parties", "auto", "system"), ("reschedule_dock", "human", "node"), ("decide_delay_or_replan", "human", "shipper")],
    "CARGO_DAMAGE": [("notify_parties", "auto", "system"), ("record_damage_report", "human", "node"), ("provide_statement", "human", "carrier"),
                     ("claim_decision", "human", "shipper")],
    "DATA_STALE": [("notify_parties", "auto", "system"), ("send_position", "human", "carrier")],
}

# Kênh cảnh báo theo mức (sms_sim/email_sim chỉ là nhật ký giả lập)
CHANNELS = {"critical": ("in_app", "sms_sim", "email_sim"), "high": ("in_app", "email_sim"), "medium": ("in_app",), "low": ("in_app",)}
