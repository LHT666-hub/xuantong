"""家庭医生团队持久化服务（数据库实现）。

提供团队 CRUD、成员管理与团队签约患者查询。遵循现有 db service 模式。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.care_team import (
    CareTeam,
    CareTeamMember,
    PatientTeamAssignment,
)
from app.models.patient import Patient


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class DbCareTeamService:
    """基于数据库的家庭医生团队服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_team(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建团队。org_id 为非空外键，缺省时生成占位 UUID。"""
        team = CareTeam(
            id=uuid4(),
            org_id=_parse_uuid(data.get("org_id")) or uuid4(),
            name=data.get("name") or "",
            description=data.get("description"),
        )
        self.db.add(team)
        await self.db.flush()
        await self.db.refresh(team)
        return await self.get_team(str(team.id))  # type: ignore[return-value]

    async def get_team(self, team_id: str) -> dict[str, Any] | None:
        """获取团队详情（含成员）。"""
        team_uuid = _parse_uuid(team_id)
        if team_uuid is None:
            return None

        result = await self.db.execute(
            select(CareTeam).where(CareTeam.id == team_uuid)
        )
        team = result.scalar_one_or_none()
        if team is None:
            return None

        members = (
            await self.db.execute(
                select(CareTeamMember)
                .where(CareTeamMember.care_team_id == team_uuid)
                .order_by(CareTeamMember.created_at.asc())
            )
        ).scalars().all()

        data = self._team_to_dict(team)
        data["members"] = [self._member_to_dict(m) for m in members]
        return data

    async def list_teams(
        self, page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出团队（创建时间倒序）。"""
        page = max(1, page)
        size = max(1, min(size, 200))

        total = (
            await self.db.execute(select(func.count()).select_from(CareTeam))
        ).scalar() or 0

        teams = (
            await self.db.execute(
                select(CareTeam)
                .order_by(CareTeam.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars().all()
        return [self._team_to_dict(t) for t in teams], int(total)

    async def add_member(
        self, team_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """向团队添加成员。团队不存在返回 None。"""
        team_uuid = _parse_uuid(team_id)
        if team_uuid is None:
            return None

        exists = (
            await self.db.execute(
                select(CareTeam.id).where(CareTeam.id == team_uuid)
            )
        ).scalar_one_or_none()
        if exists is None:
            return None

        member = CareTeamMember(
            id=uuid4(),
            care_team_id=team_uuid,
            user_id=_parse_uuid(data.get("user_id")) or uuid4(),
            role=data.get("role") or "doctor",
            display_name=data.get("display_name") or "",
        )
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return self._member_to_dict(member)

    async def list_team_patients(self, team_id: str) -> list[dict[str, Any]] | None:
        """列出团队签约的患者。团队不存在返回 None。"""
        team_uuid = _parse_uuid(team_id)
        if team_uuid is None:
            return None

        exists = (
            await self.db.execute(
                select(CareTeam.id).where(CareTeam.id == team_uuid)
            )
        ).scalar_one_or_none()
        if exists is None:
            return None

        rows = (
            await self.db.execute(
                select(Patient)
                .join(
                    PatientTeamAssignment,
                    PatientTeamAssignment.patient_id == Patient.id,
                )
                .where(PatientTeamAssignment.care_team_id == team_uuid)
                .order_by(PatientTeamAssignment.assigned_at.desc())
            )
        ).scalars().all()

        return [self._patient_brief(p) for p in rows]

    async def assign_patient(
        self, team_id: str, patient_id: str
    ) -> dict[str, Any] | None:
        """将患者签约到团队（内部辅助 / 供扩展使用）。"""
        team_uuid = _parse_uuid(team_id)
        patient_uuid = _parse_uuid(patient_id)
        if team_uuid is None or patient_uuid is None:
            return None

        assignment = PatientTeamAssignment(
            id=uuid4(),
            patient_id=patient_uuid,
            care_team_id=team_uuid,
        )
        self.db.add(assignment)
        await self.db.flush()
        await self.db.refresh(assignment)
        return {
            "id": str(assignment.id),
            "patient_id": str(assignment.patient_id),
            "care_team_id": str(assignment.care_team_id),
            "assigned_at": (
                assignment.assigned_at.isoformat() if assignment.assigned_at else None
            ),
        }

    # ── serializers ────────────────────────────────────────────────
    def _team_to_dict(self, team: CareTeam) -> dict[str, Any]:
        return {
            "id": str(team.id),
            "org_id": str(team.org_id) if team.org_id else None,
            "name": team.name,
            "description": team.description,
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }

    def _member_to_dict(self, member: CareTeamMember) -> dict[str, Any]:
        return {
            "id": str(member.id),
            "care_team_id": str(member.care_team_id),
            "user_id": str(member.user_id) if member.user_id else None,
            "role": member.role,
            "display_name": member.display_name,
        }

    def _patient_brief(self, patient: Patient) -> dict[str, Any]:
        return {
            "id": str(patient.id),
            "name": patient.name,
            "age": patient.age,
            "gender": patient.gender,
            "risk_level": patient.risk_level,
        }


__all__ = ["DbCareTeamService"]
