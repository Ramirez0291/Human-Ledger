"""测试夹具：每个测试用独立的临时 SQLite 库，互不干扰。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app 之前设置，否则 settings 会先以默认值实例化
_TMP = Path(tempfile.mkdtemp(prefix="renlei-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_client(client: TestClient):
    """已完成初始化并登录的客户端（含预置类目）。"""
    res = client.post(
        "/api/setup",
        json={"username": "tester", "password": "password123", "locale": "zh-CN"},
    )
    assert res.status_code == 201, res.text
    return client


@pytest.fixture()
def accounts(auth_client: TestClient):
    """一组典型的在日账户：银行 / 现金 / 信用卡 / 电子钱包。"""
    made = {}
    for key, name, type_ in [
        ("bank", "三井住友銀行", "bank"),
        ("cash", "現金", "cash"),
        ("card", "楽天カード", "credit_card"),
        ("paypay", "PayPay", "emoney"),
    ]:
        res = auth_client.post(
            "/api/accounts",
            json={"name": name, "type": type_, "opening_balance": 0},
        )
        assert res.status_code == 201, res.text
        made[key] = res.json()["id"]
    return made
