from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class Job:
    job_id: str
    parser_type: str
    input_data: dict[str, Any]
    settings: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def create(
        cls,
        parser_type: str,
        input_data: dict[str, Any],
        settings: dict[str, Any] | None = None,
    ) -> "Job":
        return cls(
            job_id=str(uuid4()),
            parser_type=parser_type,
            input_data=input_data,
            settings=settings or {},
        )

    def to_queue_message(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "parser_type": self.parser_type,
            "input_data": self.input_data,
            "settings": self.settings,
            "status": self.status,
            "created_at": self.created_at,
        }

    def to_record(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "parser_type": self.parser_type,
            "input_data_json": json.dumps(self.input_data),
            "settings_json": json.dumps(self.settings),
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Job":
        return cls(
            job_id=str(record["job_id"]),
            parser_type=str(record["parser_type"]),
            input_data=json.loads(str(record["input_data_json"])),
            settings=json.loads(str(record["settings_json"])),
            status=str(record["status"]),
            created_at=str(record["created_at"]),
        )
