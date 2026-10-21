from datetime import datetime, timezone, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


Name = Annotated[str, Field(min_length=1, max_length=255)]
Count = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]


class Identity(StrictModel):
    account_type: Literal['domain_shared', 'domain', 'local']
    principal: Name
    realm: Annotated[str, Field(max_length=255)]
    local_user: Name
    uid: Count
    shift_id: Annotated[str, Field(max_length=128)]
    desktop_session: Name
    domain_uid: Count | None = None

    @model_validator(mode='after')
    def account_consistency(self):
        if self.account_type != 'local' and not self.realm:
            raise ValueError('domain identity requires realm')
        if self.account_type == 'local' and (self.realm or self.domain_uid is not None):
            raise ValueError('local identity cannot claim a domain')
        if self.account_type == 'domain_shared' and not self.shift_id:
            raise ValueError('shared identity requires shift_id')
        return self


class Event(StrictModel):
    schema_version: Literal[1]
    event_id: UUID
    device_id: UUID
    boot_id: UUID
    start: AwareDatetime
    end: AwareDatetime
    duration_ms: Annotated[int, Field(strict=True, ge=0, le=31_536_000_000)]
    identity: Identity | None
    state: Literal['active', 'afk', 'locked', 'unknown']
    reason: Annotated[str, Field(max_length=128)]
    key_presses: Count
    boundary_key_drops: Count

    @model_validator(mode='after')
    def interval_consistency(self):
        if self.end < self.start:
            raise ValueError('negative interval')
        if abs((self.end - self.start).total_seconds() * 1000 - self.duration_ms) > 10:
            raise ValueError('duration does not match timestamps')
        if self.end > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('future timestamp')
        if self.identity is None and self.state != 'unknown':
            raise ValueError('observed state requires identity')
        if (self.key_presses or self.boundary_key_drops) and self.state != 'active':
            raise ValueError('input requires active state')
        return self


class Batch(StrictModel):
    schema_version: Literal[1]
    device_id: UUID
    hostname: Name
    agent_version: Annotated[str, Field(min_length=1, max_length=64)]
    events: Annotated[list[Event], Field(min_length=1, max_length=200)]

    @model_validator(mode='after')
    def devices_match(self):
        if any(e.device_id != self.device_id for e in self.events):
            raise ValueError('event device does not match batch')
        ids = [e.event_id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate event IDs in batch')
        return self
