"""患者主数据 CRUD 端点测试。

覆盖路由（prefix=/api）：
- POST   /patients                创建（201）
- GET    /patients                列表 + 分页 + 搜索
- GET    /patients/{id}           详情（404 if 不存在）
- PUT    /patients/{id}           更新（404 if 不存在）
- DELETE /patients/{id}           软删除（404 if 不存在）

使用 conftest 注入的内存 SQLite（app.state.session_factory）。
"""

import uuid

import pytest

PATIENTS_URL = "/api/patients"


def _payload(**overrides) -> dict:
    data = {
        "name": "张阿姨",
        "age": 68,
        "gender": "女",
        "chronic_diseases": ["高血压", "2型糖尿病"],
        "allergies": ["青霉素"],
        "risk_level": "yellow",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_create_patient(client):
    resp = await client.post(PATIENTS_URL, json=_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert uuid.UUID(body["id"])  # 合法 UUID
    assert body["name"] == "张阿姨"
    assert body["age"] == 68
    assert body["gender"] == "女"
    assert body["chronic_diseases"] == ["高血压", "2型糖尿病"]
    assert body["risk_level"] == "yellow"
    assert body["created_at"]


@pytest.mark.asyncio
async def test_create_patient_requires_name(client):
    resp = await client.post(PATIENTS_URL, json={"age": 50})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_get_patient(client):
    created = (await client.post(PATIENTS_URL, json=_payload())).json()
    resp = await client.get(f"{PATIENTS_URL}/{created['id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["name"] == "张阿姨"


@pytest.mark.asyncio
async def test_get_patient_not_found(client):
    resp = await client.get(f"{PATIENTS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_patients(client):
    await client.post(PATIENTS_URL, json=_payload(name="患者A"))
    await client.post(PATIENTS_URL, json=_payload(name="患者B"))

    resp = await client.get(PATIENTS_URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert len(body["patients"]) == 2
    assert body["page"] == 1 and body["size"] == 20


@pytest.mark.asyncio
async def test_list_patients_pagination(client):
    for i in range(5):
        await client.post(PATIENTS_URL, json=_payload(name=f"患者{i}"))

    resp = await client.get(PATIENTS_URL, params={"page": 1, "size": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert len(body["patients"]) == 2
    assert body["size"] == 2


@pytest.mark.asyncio
async def test_patient_search(client):
    await client.post(PATIENTS_URL, json=_payload(name="张阿姨"))
    await client.post(PATIENTS_URL, json=_payload(name="李叔叔"))

    resp = await client.get(PATIENTS_URL, params={"search": "张"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["patients"][0]["name"] == "张阿姨"


@pytest.mark.asyncio
async def test_update_patient(client):
    created = (await client.post(PATIENTS_URL, json=_payload())).json()
    resp = await client.put(
        f"{PATIENTS_URL}/{created['id']}",
        json={"age": 69, "risk_level": "red"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["age"] == 69
    assert body["risk_level"] == "red"
    # 未提供字段保持不变
    assert body["name"] == "张阿姨"


@pytest.mark.asyncio
async def test_update_patient_not_found(client):
    resp = await client.put(f"{PATIENTS_URL}/{uuid.uuid4()}", json={"age": 70})
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_patient(client):
    created = (await client.post(PATIENTS_URL, json=_payload())).json()
    pid = created["id"]

    resp = await client.delete(f"{PATIENTS_URL}/{pid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True, "patient_id": pid}

    # 软删除后不可再获取
    assert (await client.get(f"{PATIENTS_URL}/{pid}")).status_code == 404
    # 列表中也不再出现
    listing = (await client.get(PATIENTS_URL)).json()
    assert listing["total"] == 0


@pytest.mark.asyncio
async def test_delete_patient_not_found(client):
    resp = await client.delete(f"{PATIENTS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text
