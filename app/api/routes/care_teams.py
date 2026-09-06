"""家庭医生团队路由（真实数据库实现）。

- GET  /api/care-teams                        团队列表（分页）
- POST /api/care-teams                        创建团队（201）
- GET  /api/care-teams/{team_id}              团队详情（含成员）
- POST /api/care-teams/{team_id}/members      添加成员（201）
- GET  /api/care-teams/{team_id}/patients     团队签约患者
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.db import DbCareTeamService

router = APIRouter(prefix="/care-teams", tags=["care-teams"])


# ── Pydantic 模型 ────────────────────────────────────────────────────────────
class CareTeamCreate(BaseModel):
    name: str
    description: str | None = None
    org_id: str | None = None


class CareTeamMemberCreate(BaseModel):
    role: str
    display_name: str
    user_id: str | None = None


class CareTeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    care_team_id: str
    user_id: str | None = None
    role: str
    display_name: str


class CareTeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str | None = None
    name: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    members: list[CareTeamMemberOut] = []


# ── 路由 ─────────────────────────────────────────────────────────────────────
@router.get("")
async def list_care_teams(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_session),
):
    """分页列出家庭医生团队。"""
    service = DbCareTeamService(db)
    teams, total = await service.list_teams(page=page, size=size)
    return {
        "care_teams": [CareTeamOut.model_validate(t).model_dump() for t in teams],
        "total": total,
        "page": max(1, page),
        "size": max(1, size),
    }


@router.post("", response_model=CareTeamOut, status_code=status.HTTP_201_CREATED)
async def create_care_team(
    payload: CareTeamCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """创建家庭医生团队。"""
    service = DbCareTeamService(db)
    team = await service.create_team(payload.model_dump())
    await db.commit()
    return CareTeamOut.model_validate(team)


@router.get("/{team_id}", response_model=CareTeamOut)
async def get_care_team(
    team_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取团队详情（含成员）。不存在返回 404。"""
    service = DbCareTeamService(db)
    team = await service.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Care team not found")
    return CareTeamOut.model_validate(team)


@router.post(
    "/{team_id}/members",
    response_model=CareTeamMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_care_team_member(
    team_id: str,
    payload: CareTeamMemberCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """向团队添加成员。团队不存在返回 404。"""
    service = DbCareTeamService(db)
    member = await service.add_member(team_id, payload.model_dump())
    if member is None:
        raise HTTPException(status_code=404, detail="Care team not found")
    await db.commit()
    return CareTeamMemberOut.model_validate(member)


@router.get("/{team_id}/patients")
async def list_care_team_patients(
    team_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """列出团队签约的患者。团队不存在返回 404。"""
    service = DbCareTeamService(db)
    patients = await service.list_team_patients(team_id)
    if patients is None:
        raise HTTPException(status_code=404, detail="Care team not found")
    return {"team_id": team_id, "patients": patients, "total": len(patients)}
