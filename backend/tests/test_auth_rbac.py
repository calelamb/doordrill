
def _create_assignment(client, manager_id: str, rep_id: str, scenario_id: str, headers: dict[str, str] | None = None):
    return client.post(
        "/manager/assignments",
        json={
            "scenario_id": scenario_id,
            "rep_id": rep_id,
            "assigned_by": manager_id,
            "retry_policy": {},
        },
        headers=headers or {},
    )


def test_rep_cannot_access_other_rep_assignments(client, seed_org):
    resp = _create_assignment(client, seed_org["manager_id"], seed_org["rep_id"], seed_org["scenario_id"])
    assert resp.status_code == 200

    denied = client.get(
        "/rep/assignments",
        params={"rep_id": "someone-else"},
        headers={"x-user-id": seed_org["rep_id"], "x-user-role": "rep"},
    )
    assert denied.status_code == 403


def test_manager_cannot_assign_as_different_manager(client, seed_org):
    denied = _create_assignment(
        client,
        manager_id="not-this-manager",
        rep_id=seed_org["rep_id"],
        scenario_id=seed_org["scenario_id"],
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert denied.status_code == 403


def test_rep_cannot_hit_manager_feed(client, seed_org):
    denied = client.get(
        "/manager/feed",
        params={"manager_id": seed_org["manager_id"]},
        headers={"x-user-id": seed_org["rep_id"], "x-user-role": "rep"},
    )
    assert denied.status_code == 403
