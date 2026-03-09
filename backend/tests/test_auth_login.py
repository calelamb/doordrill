from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth_service import AuthService


def test_login_accepts_legacy_non_email_identifier(client, seed_org):
    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep.email = "calejlamb"
        rep.password_hash = AuthService().hash_password("SecretPass123")
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/auth/login",
        json={"email": "calejlamb", "password": "SecretPass123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["user"]["email"] == "calejlamb"
