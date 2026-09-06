"""家庭医生团队端点测试。

覆盖路由（prefix=/api）：
- POST /care-teams                     创建团队（201）
- GET  /care-teams                     团队列表
- GET  /care-teams/{id}                团队详情（含成员，404 if 不存在）
- POST /care-teams/{id}/members        添加成员（201，404 if 团队不存在）
- GET  /care-teams/{id}/patients       团队签约患者（404 if 团队不存在）
"""

import uuid

import pytest

TEAMS_URL = "/api/care-teams"
PATIENTS_URL = "/api/patients"


@pytest.mark.asyncio
async def test_create_care_team(client):
    resp = await client.post(TEAMS_URL, json={"name": "徐汇家医一队", "description": "示范团队"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["name"] == "徐汇家医一队"
    assert body["description"] == "示范团队"
    assert body["members"] == []


@pytest.mark.asyncio
async def test_list_care_teams(client):
    await client.post(TEAMS_URL, json={"name": "团队A"})
    await client.post(TEAMS_URL, json={"name": "团队B"})

    resp = await client.get(TEAMS_URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert len(body["care_teams"]) == 2


@pytest.mark.asyncio
async def test_get_care_team(client):
    created = (await client.post(TEAMS_URL, json={"name": "团队C"})).json()
    resp = await client.get(f"{TEAMS_URL}/{created['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "团队C"


@pytest.mark.asyncio
async def test_get_care_team_not_found(client):
    resp = await client.get(f"{TEAMS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_add_member(client):
    team = (await client.post(TEAMS_URL, json={"name": "团队D"})).json()
    resp = await client.post(
        f"{TEAMS_URL}/{team['id']}/members",
        json={"role": "doctor", "display_name": "王医生"},
    )
    assert resp.status_code == 201, resp.text
    member = resp.json()
    assert member["role"] == "doctor"
    assert member["display_name"] == "王医生"
    assert member["care_team_id"] == team["id"]

    # 详情中包含该成员
    detail = (await client.get(f"{TEAMS_URL}/{team['id']}")).json()
    assert len(detail["members"]) == 1
    assert detail["members"][0]["display_name"] == "王医生"


@pytest.mark.asyncio
async def test_add_member_team_not_found(client):
    resp = await client.post(
        f"{TEAMS_URL}/{uuid.uuid4()}/members",
        json={"role": "nurse", "display_name": "李护士"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_team_patients_empty(client):
    team = (await client.post(TEAMS_URL, json={"name": "团队E"})).json()
    resp = await client.get(f"{TEAMS_URL}/{team['id']}/patients")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["patients"] == []


@pytest.mark.asyncio
async def test_list_team_patients_not_found(client):
    resp = await client.get(f"{TEAMS_URL}/{uuid.uuid4()}/patients")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_team_patients_with_assignment(client, db_factory):
    from app.models.care_team import PatientTeamAssignment

    team = (await client.post(TEAMS_URL, json={"name": "团队F"})).json()
    patient = (await client.post(PATIENTS_URL, json={"name": "张阿姨"})).json()

    # 直接落库一条签约关系（无对外端点）
    async with db_factory() as session:
        session.add(
            PatientTeamAssignment(
                id=uuid.uuid4(),
                patient_id=uuid.UUID(patient["id"]),
                care_team_id=uuid.UUID(team["id"]),
            )
        )
        await session.commit()

    resp = await client.get(f"{TEAMS_URL}/{team['id']}/patients")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["patients"][0]["name"] == "张阿姨"
