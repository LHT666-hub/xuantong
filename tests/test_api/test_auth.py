"""认证体系测试 —— 注册 / 登录 / 当前用户 / 角色门控。

使用独立的内存 SQLite（StaticPool 共享同一连接）作为测试数据库，
仅创建 users 表，避免依赖完整数据模型。通过 app.state.session_factory
注入到与生产一致的 get_db_session 依赖中。
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 —— 确保模型注册到 Base.metadata
from app.api.deps import require_role
from app.database.base import Base
from app.main import app
from app.models.user import User

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
ME_URL = "/api/auth/me"


@pytest.fixture
async def db_factory():
    """创建内存数据库并注入 app.state.session_factory。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # 仅创建 users 表即可满足认证测试
        await conn.run_sync(
            Base.metadata.create_all, tables=[User.__table__]
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    original = getattr(app.state, "session_factory", None)
    app.state.session_factory = factory
    try:
        yield factory
    finally:
        app.state.session_factory = original
        await engine.dispose()


@pytest.fixture
async def client(db_factory):
    """绑定到主 app 的异步测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _register_payload(**overrides) -> dict:
    data = {
        "username": "zhang_doctor",
        "email": "zhang@example.com",
        "password": "secret-pass-123",
        "role": "doctor",
    }
    data.update(overrides)
    return data


async def _register(client: AsyncClient, **overrides) -> dict:
    resp = await client.post(REGISTER_URL, json=_register_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, username: str, password: str):
    # OAuth2PasswordRequestForm 需要 form-encoded 数据
    return await client.post(
        LOGIN_URL, data={"username": username, "password": password}
    )


# ── 注册 ────────────────────────────────────────────────────────────────────
async def test_register_user(client):
    resp = await client.post(REGISTER_URL, json=_register_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "zhang_doctor"
    assert body["email"] == "zhang@example.com"
    assert body["role"] == "doctor"
    assert body["is_active"] is True
    assert "id" in body
    # 绝不泄露密码哈希
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_duplicate(client):
    await _register(client)
    # 相同 username
    resp = await client.post(REGISTER_URL, json=_register_payload())
    assert resp.status_code == 409, resp.text
    # 相同 email、不同 username 同样冲突
    resp2 = await client.post(
        REGISTER_URL,
        json=_register_payload(username="another_name"),
    )
    assert resp2.status_code == 409, resp2.text


# ── 登录 ────────────────────────────────────────────────────────────────────
async def test_login_success(client):
    await _register(client)
    resp = await _login(client, "zhang_doctor", "secret-pass-123")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]

    # 也支持用邮箱登录
    resp_email = await _login(client, "zhang@example.com", "secret-pass-123")
    assert resp_email.status_code == 200, resp_email.text


async def test_login_wrong_password(client):
    await _register(client)
    resp = await _login(client, "zhang_doctor", "wrong-password")
    assert resp.status_code == 401, resp.text


async def test_login_unknown_user(client):
    resp = await _login(client, "ghost", "whatever-pass")
    assert resp.status_code == 401, resp.text


# ── 当前用户 ────────────────────────────────────────────────────────────────
async def test_get_me_authenticated(client):
    await _register(client)
    login = await _login(client, "zhang_doctor", "secret-pass-123")
    token = login.json()["access_token"]

    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "zhang_doctor"
    assert body["email"] == "zhang@example.com"
    assert body["role"] == "doctor"


async def test_get_me_unauthenticated(client):
    # 无 token
    resp = await client.get(ME_URL)
    assert resp.status_code == 401, resp.text

    # 无效 token
    resp_bad = await client.get(
        ME_URL, headers={"Authorization": "Bearer not-a-valid-token"}
    )
    assert resp_bad.status_code == 401, resp_bad.text


# ── 角色门控 ────────────────────────────────────────────────────────────────
async def test_role_based_access(client, db_factory):
    """验证 require_role 依赖工厂：授权角色放行，其他角色 403，未认证 401。"""
    # 构建一个挂载了角色保护路由的临时 app，复用同一 session_factory
    guard_app = FastAPI()
    guard_app.state.session_factory = db_factory

    @guard_app.get("/admin-only")
    async def admin_only(current_user: User = Depends(require_role("admin"))):
        return {"username": current_user.username, "role": current_user.role}

    # 注册一名 admin 与一名 doctor
    await _register(client, username="admin_user", email="admin@example.com", role="admin")
    await _register(client, username="doctor_user", email="doctor@example.com", role="doctor")

    admin_token = (
        await _login(client, "admin_user", "secret-pass-123")
    ).json()["access_token"]
    doctor_token = (
        await _login(client, "doctor_user", "secret-pass-123")
    ).json()["access_token"]

    transport = ASGITransport(app=guard_app)
    async with AsyncClient(transport=transport, base_url="http://test") as gc:
        # admin → 放行
        ok = await gc.get(
            "/admin-only", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["role"] == "admin"

        # doctor → 403 权限不足
        forbidden = await gc.get(
            "/admin-only", headers={"Authorization": f"Bearer {doctor_token}"}
        )
        assert forbidden.status_code == 403, forbidden.text

        # 无 token → 401
        unauth = await gc.get("/admin-only")
        assert unauth.status_code == 401, unauth.text
