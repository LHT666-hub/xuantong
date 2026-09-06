"""患者主数据路由（真实数据库 CRUD）。

Phase 2+：从"事件派生只读 stub"升级为基于 Patient 模型的完整 CRUD，
使用 ``get_db_session`` 依赖获取 AsyncSession，服务层负责持久化。

- POST   /api/patients                 创建患者（201）
- GET    /api/patients                 分页列表（page/size/search）
- GET    /api/patients/{patient_id}    患者详情
- PUT    /api/patients/{patient_id}    更新患者
- DELETE /api/patients/{patient_id}    软删除（标记 deleted_at）

注：``GET /api/patients/{patient_id}/timeline`` 由 timeline 路由提供，保持不变。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.db import DbPatientService

router = APIRouter(prefix="/patients", tags=["patients"])


# ── Pydantic 模型 ────────────────────────────────────────────────────────────
class PatientCreate(BaseModel):
    name: str
    age: int | None = None
    gender: str | None = None
    chronic_diseases: list[str] | None = None
    allergies: list[str] | None = None
    current_medications: list[dict] | None = None
    risk_level: str | None = None
    user_id: str | None = None
    org_id: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    age: int | None = None
    gender: str | None = None
    chronic_diseases: list[str] | None = None
    allergies: list[str] | None = None
    current_medications: list[dict] | None = None
    risk_level: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    org_id: str | None = None
    name: str
    age: int | None = None
    gender: str | None = None
    chronic_diseases: list = []
    allergies: list = []
    current_medications: list = []
    risk_level: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None


# ── 路由 ─────────────────────────────────────────────────────────────────────
@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(
    payload: PatientCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """创建患者主数据。"""
    service = DbPatientService(db)
    patient = await service.create_patient(payload.model_dump())
    await db.commit()
    return PatientOut.model_validate(patient)


@router.get("")
async def list_patients(
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """分页列出患者（支持按姓名模糊搜索）。"""
    service = DbPatientService(db)
    patients, total = await service.list_patients(page=page, size=size, search=search)
    return {
        "patients": [PatientOut.model_validate(p).model_dump() for p in patients],
        "total": total,
        "page": max(1, page),
        "size": max(1, size),
    }


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取患者详情。不存在返回 404。"""
    service = DbPatientService(db)
    patient = await service.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return PatientOut.model_validate(patient)


@router.put("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: str,
    payload: PatientUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    """更新患者字段。不存在返回 404。"""
    service = DbPatientService(db)
    patient = await service.update_patient(
        patient_id, payload.model_dump(exclude_unset=True)
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    await db.commit()
    return PatientOut.model_validate(patient)


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """软删除患者（标记 deleted_at）。不存在返回 404。"""
    service = DbPatientService(db)
    deleted = await service.delete_patient(patient_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Patient not found")
    await db.commit()
    return {"deleted": True, "patient_id": patient_id}
