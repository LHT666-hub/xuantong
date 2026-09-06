"""健康记录与体征测量持久化服务（数据库实现）。

提供健康记录 CRUD、按记录追加测量数据、以及患者测量历史查询。
遵循现有 db service 模式。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_record import HealthRecord
from app.models.measurement import Measurement


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


class DbHealthRecordService:
    """基于数据库的健康记录 / 测量服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── health records ─────────────────────────────────────────────
    async def create_record(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建健康记录。"""
        record = HealthRecord(
            id=uuid4(),
            patient_id=_parse_uuid(data.get("patient_id")) or uuid4(),
            record_type=data.get("record_type") or "visit",
            title=data.get("title") or "",
            content=data.get("content") or {},
            source=data.get("source"),
            recorded_at=_parse_dt(data.get("recorded_at")) or _now(),
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return self._record_to_dict(record)

    async def get_record(self, record_id: str) -> dict[str, Any] | None:
        """获取单条健康记录。"""
        record_uuid = _parse_uuid(record_id)
        if record_uuid is None:
            return None

        result = await self.db.execute(
            select(HealthRecord).where(HealthRecord.id == record_uuid)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._record_to_dict(record)

    async def list_records(
        self,
        patient_id: str | None = None,
        record_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出健康记录（可按患者 / 类型过滤，记录时间倒序）。"""
        page = max(1, page)
        size = max(1, min(size, 200))

        conditions = []
        if patient_id:
            patient_uuid = _parse_uuid(patient_id)
            if patient_uuid is not None:
                conditions.append(HealthRecord.patient_id == patient_uuid)
        if record_type:
            conditions.append(HealthRecord.record_type == record_type)

        count_query = select(func.count()).select_from(HealthRecord)
        if conditions:
            count_query = count_query.where(*conditions)
        total = (await self.db.execute(count_query)).scalar() or 0

        query = select(HealthRecord).order_by(HealthRecord.recorded_at.desc())
        if conditions:
            query = query.where(*conditions)
        query = query.offset((page - 1) * size).limit(size)

        records = (await self.db.execute(query)).scalars().all()
        return [self._record_to_dict(r) for r in records], int(total)

    # ── measurements ───────────────────────────────────────────────
    async def add_measurement_to_record(
        self, record_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """为某条健康记录追加测量数据。

        Measurement 仅通过 patient_id 关联，故取记录所属患者写入测量。
        记录不存在返回 None。
        """
        record_uuid = _parse_uuid(record_id)
        if record_uuid is None:
            return None

        record = (
            await self.db.execute(
                select(HealthRecord).where(HealthRecord.id == record_uuid)
            )
        ).scalar_one_or_none()
        if record is None:
            return None

        payload = dict(data)
        if not payload.get("patient_id"):
            payload["patient_id"] = str(record.patient_id)
        return await self.create_measurement(payload)

    async def create_measurement(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建体征测量。"""
        measurement = Measurement(
            id=uuid4(),
            patient_id=_parse_uuid(data.get("patient_id")) or uuid4(),
            measurement_type=data.get("measurement_type") or "",
            value=float(data.get("value")),
            secondary_value=(
                float(data["secondary_value"])
                if data.get("secondary_value") is not None
                else None
            ),
            unit=data.get("unit") or "",
            measured_at=_parse_dt(data.get("measured_at")) or _now(),
        )
        self.db.add(measurement)
        await self.db.flush()
        await self.db.refresh(measurement)
        return self._measurement_to_dict(measurement)

    async def list_patient_measurements(
        self,
        patient_id: str,
        measurement_type: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """列出患者测量历史（可按类型过滤，测量时间倒序）。"""
        page = max(1, page)
        size = max(1, min(size, 200))

        patient_uuid = _parse_uuid(patient_id)
        if patient_uuid is None:
            return [], 0

        conditions = [Measurement.patient_id == patient_uuid]
        if measurement_type:
            conditions.append(Measurement.measurement_type == measurement_type)

        total = (
            await self.db.execute(
                select(func.count()).select_from(Measurement).where(*conditions)
            )
        ).scalar() or 0

        rows = (
            await self.db.execute(
                select(Measurement)
                .where(*conditions)
                .order_by(Measurement.measured_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars().all()
        return [self._measurement_to_dict(m) for m in rows], int(total)

    # ── serializers ────────────────────────────────────────────────
    def _record_to_dict(self, record: HealthRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "patient_id": str(record.patient_id) if record.patient_id else None,
            "record_type": record.record_type,
            "title": record.title,
            "content": record.content or {},
            "source": record.source,
            "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _measurement_to_dict(self, m: Measurement) -> dict[str, Any]:
        return {
            "id": str(m.id),
            "patient_id": str(m.patient_id) if m.patient_id else None,
            "measurement_type": m.measurement_type,
            "value": m.value,
            "secondary_value": m.secondary_value,
            "unit": m.unit,
            "measured_at": m.measured_at.isoformat() if m.measured_at else None,
        }


__all__ = ["DbHealthRecordService"]
