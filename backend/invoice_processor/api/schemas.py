"""API 请求与响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.job import JobTrigger


class StartJobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    source_dir: str = Field(min_length=1)
    trigger: JobTrigger = JobTrigger.MANUAL


class RuntimeJobStartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    kind: str = 'invoice_processing'
    input: dict[str, Any] = Field(default_factory=dict)


class RuntimeJobResponse(BaseModel):
    id: str
    kind: str
    status: str
    progress: float
    message: str
    created_at: str
    updated_at: str


class DirectoryScanResponse(BaseModel):
    source_dir: str
    pdf_count: int


class OpenDirectoryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    path: str = Field(min_length=1)


class OpenDirectoryResponse(BaseModel):
    opened: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    devbase_version: str
    mode: str


class UpdateResponse(BaseModel):
    current_version: str
    checked: bool
    available: bool
    latest_version: str | None = None
    release_url: str | None = None


class LogEntry(BaseModel):
    event_id: int
    occurred_at: str
    level: str
    message: str


class LogListResponse(BaseModel):
    items: list[LogEntry]
    next_event_id: int | None = None


class ToolDescriptorResponse(BaseModel):
    kind: str
    title: str
    subtitle: str | None = None
    group: str
    glyph: str
    access_key: str | None = None
    supports_input: bool = False
    mode: str = 'oneshot'


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptorResponse]


class BusinessSettings(BaseModel):
    target_tax_id: str
    max_workers: int


class EmailSettings(BaseModel):
    imap_host: str
    imap_port: int
    username: str
    inbox_dir: str
    days_back: int
    senders: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    auth_code_configured: bool


class AiSettings(BaseModel):
    enabled: bool
    api_base: str
    model: str
    timeout: int
    api_key_configured: bool


class SettingsResponse(BaseModel):
    business: BusinessSettings
    email: EmailSettings
    ai: AiSettings


class BusinessSettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    target_tax_id: str | None = Field(default=None, min_length=1)
    max_workers: int | None = Field(default=None, ge=2, le=16)


class EmailSettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    imap_host: str | None = Field(default=None, min_length=1)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    auth_code: str | None = None
    inbox_dir: str | None = Field(default=None, min_length=1)
    days_back: int | None = Field(default=None, ge=1, le=365)
    senders: list[str] | None = None
    keywords: list[str] | None = None


class AiSettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool | None = None
    api_key: str | None = None
    api_base: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    timeout: int | None = Field(default=None, ge=10, le=600)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    business: BusinessSettingsPatch
    email: EmailSettingsPatch
    ai: AiSettingsPatch


class EmailTestResponse(BaseModel):
    ok: bool
    message: str


class AiTestResponse(BaseModel):
    ok: bool
    message: str


class EmailPullResponse(BaseModel):
    pull: dict[str, Any]
    job: dict[str, Any] | None = None
