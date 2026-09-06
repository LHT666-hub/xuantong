"""健康记录与体征测量路由（真实数据库实现）。

- GET  /api/health-records                            列表（按 patient_id 过滤 + 分页）
- POST /api/health-records                            创建健康记录（201）
- GET  /api/health-records/{record_id}                记录详情
- POST /api/health-records/{record_id}/measurements   为记录追加测量数据（201）
- GET  /api/patients/{patient_id}/measurements        患者测量历史

本路由不使用统一 prefix，以便同时挂载 /health-records 与
/patients/{patient_id}/measurements 两组路径（main.py 以 /api 前缀注册）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.db import DbHealthRecordService
from app.utils import normalize_patient_id

router = APIRouter(tags=["health-records"])


# ── Pydantic 模型 ────────────────────────────────────────────────────────────
class HealthRecordCreate(BaseModel):
    patient_id: str
    record_type: str
    title: str
    content: dict | None = None
    source: str | None = None
    recorded_at: str | None = None


class HealthRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str | None = None
    record_type: str
    title: str
    content: dict = {}
    source: str | None = None
    recorded_at: str | None = None
    created_at: str | None = None


class MeasurementCreate(BaseModel):
    measurement_type: str
    value: float
    secondary_value: float | None = None
    unit: str
    measured_at: str | None = None
    patient_id: str | None = None


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str | None = None
    measurement_type: str
    value: float
    secondary_value: float | None = None
    unit: str
    measured_at: str | None = None


# ── 健康记录路由 ──────────────────────────────────────────────────────────────
@router.get("/health-records")
async def list_health_records(
    patient_id: str | None = None,
    record_type: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_session),
):
    """分页列出健康记录（可按患者 / 类型过滤）。"""
    service = DbHealthRecordService(db)
    pid = normalize_patient_id(patient_id) if patient_id else None
    records, total = await service.list_records(
        patient_id=pid, record_type=record_type, page=page, size=size
    )
    return {
        "records": [HealthRecordOut.model_validate(r).model_dump() for r in records],
        "total": total,
        "page": max(1, page),
        "size": max(1, size),
    }


@router.post(
    "/health-records",
    response_model=HealthRecordOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_health_record(
    payload: HealthRecordCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """创建健康记录。"""
    service = DbHealthRecordService(db)
    data = payload.model_dump()
    data["patient_id"] = normalize_patient_id(data["patient_id"])
    record = await service.create_record(data)
    await db.commit()
    return HealthRecordOut.model_validate(record)


@router.get("/health-records/{record_id}", response_model=HealthRecordOut)
async def get_health_record(
    record_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取健康记录详情。不存在返回 404。"""
    service = DbHealthRecordService(db)
    record = await service.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Health record not found")
    return HealthRecordOut.model_validate(record)


@router.post(
    "/health-records/{record_id}/measurements",
    response_model=MeasurementOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_record_measurement(
    record_id: str,
    payload: MeasurementCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """为健康记录追加测量数据。记录不存在返回 404。"""
    service = DbHealthRecordService(db)
    measurement = await service.add_measurement_to_record(
        record_id, payload.model_dump()
    )
    if measurement is None:
        raise HTTPException(status_code=404, detail="Health record not found")
    await db.commit()
    return MeasurementOut.model_validate(measurement)


# ── 患者测量历史路由 ──────────────────────────────────────────────────────────
@router.get("/patients/{patient_id}/measurements")
async def list_patient_measurements(
    patient_id: str,
    measurement_type: str | None = None,
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    """列出患者测量历史（可按类型过滤，测量时间倒序）。"""
    service = DbHealthRecordService(db)
    pid = normalize_patient_id(patient_id)
    measurements, total = await service.list_patient_measurements(
        patient_id=pid, measurement_type=measurement_type, page=page, size=size
    )
    return {
        "patient_id": pid,
        "measurements": [
            MeasurementOut.model_validate(m).model_dump() for m in measurements
        ],
        "total": total,
        "page": max(1, page),
        "size": max(1, size),
    }
