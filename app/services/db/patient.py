"""患者主数据持久化服务（数据库实现）。

提供真实 CRUD：创建 / 查询 / 分页搜索 / 更新 / 软删除。
遵循现有 db service 模式（构造时注入 AsyncSession，方法内 flush，
由路由层负责 commit）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(value: Any) -> UUID | None:
    """尽力将输入解析为 UUID，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


# PatientCreate/Update 中允许写入的字段白名单
_MUTABLE_FIELDS = (
    "name",
    "age",
    "gender",
    "chronic_diseases",
    "allergies",
    "current_medications",
    "risk_level",
)


class DbPatientService:
    """基于数据库的患者主数据服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_patient(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建患者。

        Patient.user_id / org_id 为非空外键，若调用方未提供则生成占位 UUID，
        以便主数据可独立于用户体系先行落库（SQLite 默认不强制外键约束）。
        """
        patient = Patient(
            id=uuid4(),
            user_id=_parse_uuid(data.get("user_id")) or uuid4(),
            org_id=_parse_uuid(data.get("org_id")) or uuid4(),
            name=data.get("name") or "",
            age=data.get("age"),
            gender=data.get("gender"),
            chronic_diseases=data.get("chronic_diseases") or [],
            allergies=data.get("allergies") or [],
            current_medications=data.get("current_medications") or [],
            risk_level=data.get("risk_level") or "green",
        )
        self.db.add(patient)
        await self.db.flush()
        await self.db.refresh(patient)
        return self._to_dict(patient)

    async def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        """获取单个未删除患者。"""
        patient_uuid = _parse_uuid(patient_id)
        if patient_uuid is None:
            return None

        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_uuid, Patient.deleted_at.is_(None)
            )
        )
        patient = result.scalar_one_or_none()
        if patient is None:
            return None
        return self._to_dict(patient)

    async def list_patients(
        self,
        page: int = 1,
        size: int = 20,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出患者（排除软删除，支持按姓名模糊搜索，创建时间倒序）。"""
        page = max(1, page)
        size = max(1, min(size, 200))

        conditions = [Patient.deleted_at.is_(None)]
        if search:
            like = f"%{search}%"
            conditions.append(or_(Patient.name.ilike(like)))

        count_query = select(func.count()).select_from(Patient).where(*conditions)
        total = (await self.db.execute(count_query)).scalar() or 0

        query = (
            select(Patient)
            .where(*conditions)
            .order_by(Patient.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        patients = (await self.db.execute(query)).scalars().all()
        return [self._to_dict(p) for p in patients], int(total)

    async def update_patient(
        self, patient_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """更新患者字段（仅更新显式提供的白名单字段）。"""
        patient_uuid = _parse_uuid(patient_id)
        if patient_uuid is None:
            return None

        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_uuid, Patient.deleted_at.is_(None)
            )
        )
        patient = result.scalar_one_or_none()
        if patient is None:
            return None

        for field in _MUTABLE_FIELDS:
            if field in data and data[field] is not None:
                setattr(patient, field, data[field])

        await self.db.flush()
        await self.db.refresh(patient)
        return self._to_dict(patient)

    async def delete_patient(self, patient_id: str) -> bool:
        """软删除患者（标记 deleted_at）。返回是否命中记录。"""
        patient_uuid = _parse_uuid(patient_id)
        if patient_uuid is None:
            return False

        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_uuid, Patient.deleted_at.is_(None)
            )
        )
        patient = result.scalar_one_or_none()
        if patient is None:
            return False

        patient.deleted_at = _now()
        await self.db.flush()
        return True

    def _to_dict(self, patient: Patient) -> dict[str, Any]:
        """将 ORM 对象转换为 dict。"""
        return {
            "id": str(patient.id),
            "user_id": str(patient.user_id) if patient.user_id else None,
            "org_id": str(patient.org_id) if patient.org_id else None,
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "chronic_diseases": patient.chronic_diseases or [],
            "allergies": patient.allergies or [],
            "current_medications": patient.current_medications or [],
            "risk_level": patient.risk_level,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
            "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
            "deleted_at": patient.deleted_at.isoformat() if patient.deleted_at else None,
        }


__all__ = ["DbPatientService"]
