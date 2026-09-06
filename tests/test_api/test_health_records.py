"""健康记录与体征测量端点测试。

覆盖路由（prefix=/api）：
- POST /health-records                            创建记录（201）
- GET  /health-records                            列表（按 patient_id 过滤）
- GET  /health-records/{id}                       详情（404 if 不存在）
- POST /health-records/{id}/measurements          追加测量（201，404 if 记录不存在）
- GET  /patients/{id}/measurements                患者测量历史
"""

import uuid

import pytest

RECORDS_URL = "/api/health-records"
PATIENTS_URL = "/api/patients"


async def _new_patient(client) -> str:
    resp = await client.post(PATIENTS_URL, json={"name": "张阿姨"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _record_payload(patient_id: str, **overrides) -> dict:
    data = {
        "patient_id": patient_id,
        "record_type": "visit",
        "title": "高血压随访",
        "content": {"bp": "168/103"},
        "source": "home_monitor",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_create_health_record(client):
    pid = await _new_patient(client)
    resp = await client.post(RECORDS_URL, json=_record_payload(pid))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["title"] == "高血压随访"
    assert body["record_type"] == "visit"
    assert body["content"] == {"bp": "168/103"}
    assert body["recorded_at"]


@pytest.mark.asyncio
async def test_list_health_records_by_patient(client):
    pid = await _new_patient(client)
    other = await _new_patient(client)
    await client.post(RECORDS_URL, json=_record_payload(pid, title="记录1"))
    await client.post(RECORDS_URL, json=_record_payload(pid, title="记录2"))
    await client.post(RECORDS_URL, json=_record_payload(other, title="他人记录"))

    resp = await client.get(RECORDS_URL, params={"patient_id": pid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert all(r["patient_id"] == pid for r in body["records"])


@pytest.mark.asyncio
async def test_get_health_record(client):
    pid = await _new_patient(client)
    created = (await client.post(RECORDS_URL, json=_record_payload(pid))).json()
    resp = await client.get(f"{RECORDS_URL}/{created['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_health_record_not_found(client):
    resp = await client.get(f"{RECORDS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_add_measurement_to_record(client):
    pid = await _new_patient(client)
    record = (await client.post(RECORDS_URL, json=_record_payload(pid))).json()

    resp = await client.post(
        f"{RECORDS_URL}/{record['id']}/measurements",
        json={
            "measurement_type": "blood_pressure",
            "value": 168,
            "secondary_value": 103,
            "unit": "mmHg",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["measurement_type"] == "blood_pressure"
    assert body["value"] == 168
    assert body["secondary_value"] == 103
    assert body["patient_id"] == pid


@pytest.mark.asyncio
async def test_add_measurement_record_not_found(client):
    resp = await client.post(
        f"{RECORDS_URL}/{uuid.uuid4()}/measurements",
        json={"measurement_type": "heart_rate", "value": 80, "unit": "bpm"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_patient_measurements(client):
    pid = await _new_patient(client)
    record = (await client.post(RECORDS_URL, json=_record_payload(pid))).json()

    await client.post(
        f"{RECORDS_URL}/{record['id']}/measurements",
        json={"measurement_type": "blood_pressure", "value": 160, "unit": "mmHg"},
    )
    await client.post(
        f"{RECORDS_URL}/{record['id']}/measurements",
        json={"measurement_type": "heart_rate", "value": 88, "unit": "bpm"},
    )

    resp = await client.get(f"/api/patients/{pid}/measurements")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["patient_id"] == pid

    # 按类型过滤
    filtered = await client.get(
        f"/api/patients/{pid}/measurements", params={"measurement_type": "heart_rate"}
    )
    assert filtered.status_code == 200, filtered.text
    fbody = filtered.json()
    assert fbody["total"] == 1
    assert fbody["measurements"][0]["measurement_type"] == "heart_rate"
