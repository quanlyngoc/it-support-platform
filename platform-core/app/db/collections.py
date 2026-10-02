"""Danh mục collection theo đặc tả V3 chương 4A (đã bổ sung audit_log, machine_events, computers_archive)."""

# Platform-owned: không mang tenant_id (catalog dùng chung toàn nền tảng)
PLATFORM_OWNED = ("tenants", "permissions")

# Tenant-owned: BẮT BUỘC có tenant_id; chỉ truy cập qua TenantRepo
TENANT_OWNED = (
    "users", "ad_user_policies", "policies", "rooms", "computers", "agents", "agent_enrollments",
    "incidents", "usage_stats", "online_state", "client_logs", "sessions", "active_sessions", "settings",
    "chat_messages", "chat_reads", "chat_reactions", "audit_log", "pushed_files", "file_metadata",
    "machine_events", "computers_archive", "command_results",
)

ALL = PLATFORM_OWNED + TENANT_OWNED
