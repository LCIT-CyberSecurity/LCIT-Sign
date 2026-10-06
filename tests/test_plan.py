"""The recipients and planning of a draft are kept as the operator goes, so a reload (or coming
back the next day) finds them, like the signers, the documents and the elements."""
from __future__ import annotations

from test_campaign_changes import prepared_doc
from test_campaigns import get_user_id, setup_campaign_fixture
from test_signer_roles import new_campaign


def test_what_was_chosen_so_far_is_found_again(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    assert operator.get(base).json()["plan"] is None

    plan = {
        "user_ids": [get_user_id(signer1)],
        "deadline": "2099-01-31T22:59:59Z",
        "reminder_first_days": 7,
        "reminder_interval_days": 7,
        "renewal_every": 12,
        "renewal_unit": "MONTHS",
    }
    saved = operator.put(f"{base}/plan", json=plan)
    assert saved.status_code == 200, saved.text
    found = operator.get(base).json()["plan"]
    assert found["user_ids"] == plan["user_ids"] and found["renewal_every"] == 12
    assert found["reminder_first_days"] == 7 and found["deadline"].startswith("2099-01-31")

    # Replaced, not merged: what is cleared stays cleared.
    operator.put(f"{base}/plan", json={"all_users": True})
    cleared = operator.get(base).json()["plan"]
    assert cleared["all_users"] is True and cleared["user_ids"] == []
    assert cleared["reminder_first_days"] is None


def test_it_is_only_a_note_nothing_is_started_or_asked(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    operator.put(f"{base}/plan", json={"user_ids": [get_user_id(signer1)]})
    assert operator.get(base).json()["status"] == "DRAFT"
    assert operator.get(f"{base}/assignments").json() == []


def test_the_note_is_checked_for_shape_and_for_who_may_write_it(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    # A reminder rhythm needs both numbers; signers are set elsewhere; a signer cannot write it.
    assert operator.put(f"{base}/plan", json={"reminder_first_days": 3}).status_code == 422
    with_roles = {"roles": [{"role": 1, "mode": "EACH"}]}
    assert operator.put(f"{base}/plan", json=with_roles).status_code == 422
    assert signer1.put(f"{base}/plan", json={}).status_code == 403


def test_once_sent_there_is_no_note_and_it_cannot_be_written(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    operator.put(f"{base}/plan", json={"user_ids": [get_user_id(signer1)]})
    launched = operator.post(f"{base}/launch", json={"user_ids": [get_user_id(signer1)]})
    assert launched.status_code == 200
    assert operator.get(base).json()["plan"] is None
    assert operator.put(f"{base}/plan", json={}).status_code == 409
