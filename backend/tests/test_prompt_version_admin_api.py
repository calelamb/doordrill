from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.prompt_version import PromptVersion


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def test_prompt_version_admin_create_get_and_patch(client, seed_org):
    headers = _manager_headers(seed_org)

    create_response = client.post(
        "/admin/prompt-versions",
        headers=headers,
        json={
            "prompt_type": "conversation",
            "version": "conversation_v9",
            "content": "Custom conversation prompt.",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["prompt_type"] == "conversation"
    assert created["version"] == "conversation_v9"
    assert created["content"] == "Custom conversation prompt."
    assert created["active"] is False

    get_response = client.get(
        f"/admin/prompt-versions/{created['id']}",
        headers=headers,
    )
    assert get_response.status_code == 200
    assert get_response.json() == created

    patch_response = client.patch(
        f"/admin/prompt-versions/{created['id']}",
        headers=headers,
        json={
            "version": "conversation_v9_revised",
            "content": "Revised custom conversation prompt.",
        },
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["id"] == created["id"]
    assert patched["version"] == "conversation_v9_revised"
    assert patched["content"] == "Revised custom conversation prompt."
    assert patched["active"] is False


def test_prompt_version_admin_list_and_filter_are_ordered_by_created_at_desc(client, seed_org):
    db = SessionLocal()
    base_time = datetime(2030, 1, 1, tzinfo=timezone.utc)
    try:
        oldest = PromptVersion(
            prompt_type="admin_list_test",
            version="conversation_oldest",
            content="oldest",
            active=False,
            created_at=base_time,
            updated_at=base_time,
        )
        middle = PromptVersion(
            prompt_type="admin_list_other",
            version="coaching_middle",
            content="middle",
            active=True,
            created_at=base_time + timedelta(minutes=1),
            updated_at=base_time + timedelta(minutes=1),
        )
        newest = PromptVersion(
            prompt_type="admin_list_test",
            version="conversation_newest",
            content="newest",
            active=True,
            created_at=base_time + timedelta(minutes=2),
            updated_at=base_time + timedelta(minutes=2),
        )
        db.add_all([oldest, middle, newest])
        db.commit()
        db.refresh(oldest)
        db.refresh(middle)
        db.refresh(newest)
    finally:
        db.close()

    headers = _manager_headers(seed_org)
    list_response = client.get("/admin/prompt-versions", headers=headers)
    assert list_response.status_code == 200
    listed = list_response.json()
    assert [item["id"] for item in listed[:3]] == [newest.id, middle.id, oldest.id]

    filtered_response = client.get(
        "/admin/prompt-versions",
        headers=headers,
        params={"prompt_type": "admin_list_test"},
    )
    assert filtered_response.status_code == 200
    filtered = filtered_response.json()
    assert [item["id"] for item in filtered] == [newest.id, oldest.id]


def test_prompt_version_admin_activate_switches_only_same_type_siblings(client, seed_org):
    db = SessionLocal()
    try:
        current = PromptVersion(
            prompt_type="conversation",
            version="conversation_current",
            content="current",
            active=True,
        )
        target = PromptVersion(
            prompt_type="conversation",
            version="conversation_target",
            content="target",
            active=False,
        )
        other_type = PromptVersion(
            prompt_type="coaching",
            version="coaching_current",
            content="coaching",
            active=True,
        )
        db.add_all([current, target, other_type])
        db.commit()
        db.refresh(current)
        db.refresh(target)
        db.refresh(other_type)
        current_id = current.id
        target_id = target.id
        other_type_id = other_type.id
    finally:
        db.close()

    headers = _manager_headers(seed_org)
    activate_response = client.post(
        f"/admin/prompt-versions/{target_id}/activate",
        headers=headers,
    )
    assert activate_response.status_code == 200
    activated = activate_response.json()
    assert activated["id"] == target_id
    assert activated["active"] is True

    db = SessionLocal()
    try:
        refreshed_current = db.get(PromptVersion, current_id)
        refreshed_target = db.get(PromptVersion, target_id)
        refreshed_other_type = db.get(PromptVersion, other_type_id)
        assert refreshed_current is not None
        assert refreshed_target is not None
        assert refreshed_other_type is not None
        assert refreshed_current.active is False
        assert refreshed_target.active is True
        assert refreshed_other_type.active is True
    finally:
        db.close()


def test_prompt_version_admin_duplicate_create_returns_409(client, seed_org):
    headers = _manager_headers(seed_org)
    payload = {
        "prompt_type": "conversation",
        "version": "conversation_duplicate",
        "content": "duplicate content",
    }

    first_response = client.post("/admin/prompt-versions", headers=headers, json=payload)
    assert first_response.status_code == 200

    duplicate_response = client.post("/admin/prompt-versions", headers=headers, json=payload)
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "prompt version already exists"


def test_prompt_version_admin_filters_org_scoped_rows(client, seed_org):
    db = SessionLocal()
    try:
        global_row = PromptVersion(
            prompt_type="conversation",
            version="conversation_global",
            org_id=None,
            content="global",
            active=True,
        )
        own_org_row = PromptVersion(
            prompt_type="conversation",
            version="conversation_org",
            org_id=seed_org["org_id"],
            content="own org",
            active=True,
        )
        other_org_row = PromptVersion(
            prompt_type="conversation",
            version="conversation_other_org",
            org_id="other-org",
            content="other org",
            active=True,
        )
        db.add_all([global_row, own_org_row, other_org_row])
        db.commit()
    finally:
        db.close()

    headers = _manager_headers(seed_org)
    response = client.get("/admin/prompt-versions", headers=headers, params={"prompt_type": "conversation"})
    assert response.status_code == 200
    versions = {item["version"] for item in response.json()}
    assert "conversation_global" in versions
    assert "conversation_org" in versions
    assert "conversation_other_org" not in versions

    scoped_response = client.get(
        "/admin/prompt-versions",
        headers=headers,
        params={"prompt_type": "conversation", "org_id": seed_org["org_id"]},
    )
    assert scoped_response.status_code == 200
    assert [item["version"] for item in scoped_response.json()] == ["conversation_org"]


def test_prompt_version_admin_missing_rows_return_404(client, seed_org):
    headers = _manager_headers(seed_org)
    missing_id = "missing-prompt-version"

    get_response = client.get(f"/admin/prompt-versions/{missing_id}", headers=headers)
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "prompt version not found"

    patch_response = client.patch(
        f"/admin/prompt-versions/{missing_id}",
        headers=headers,
        json={"content": "updated"},
    )
    assert patch_response.status_code == 404
    assert patch_response.json()["detail"] == "prompt version not found"

    activate_response = client.post(
        f"/admin/prompt-versions/{missing_id}/activate",
        headers=headers,
    )
    assert activate_response.status_code == 404
    assert activate_response.json()["detail"] == "prompt version not found"
