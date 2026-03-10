from app.core.config import get_settings


def _rep_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}


def test_lookup_rep_hidden_outside_dev(client):
    settings = get_settings()
    original_environment = settings.environment
    try:
        settings.environment = "staging"
        response = client.get("/rep/lookup", params={"email": "hidden@example.com"})
        assert response.status_code == 404
    finally:
        settings.environment = original_environment


def test_lookup_rep_still_auto_creates_in_dev(client):
    settings = get_settings()
    original_environment = settings.environment
    try:
        settings.environment = "dev"
        response = client.get("/rep/lookup", params={"email": "lookup-hardening@example.com"})
        assert response.status_code == 200
        assert response.json()["rep_id"]
    finally:
        settings.environment = original_environment


def test_avatar_upload_rejects_non_image_files(client, seed_org):
    response = client.post(
        "/rep/profile/avatar",
        headers=_rep_headers(seed_org),
        files={"file": ("avatar.svg", b"<svg></svg>", "image/svg+xml")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "file must be an image (JPEG, PNG, GIF, or WebP)"
