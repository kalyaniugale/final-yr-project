"""Preserved response projection field lists."""
ALLOCATION_REQUEST_RESPONSE_FIELDS = [
    "request_id",
    "vendor_id",
    "zone_id",
    "request_type",
    "status",
    "business_category",
    "preferred_division",
    "created_at",
    "updated_at",
    "reviewed_at",
    "reviewed_by",
    "rejection_reason",
]

ALLOCATION_RESPONSE_FIELDS = [
    "allocation_id",
    "vendor_id",
    "zone_id",
    "request_id",
    "status",
    "allocated_at",
    "released_at",
    "approved_by",
    "created_at",
    "updated_at",
]

ZONE_LIVE_STATUS_RESPONSE_FIELDS = [
    "zone_id",
    "official_capacity",
    "current_vendor_count",
    "available_capacity",
    "status",
    "verified_at",
    "verified_by",
    "updated_at",
]

