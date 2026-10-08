"""A master key that no longer matches the active signing key must never produce a proof: the
signature would be made with a key other than the one announced."""

from __future__ import annotations

from sqlalchemy import func, select
from test_campaigns import get_user_id, setup_campaign_fixture
from test_signature_campaign_isolation import ask, publish, statuses

from lcit_sign.models.signature import Signature

WRONG = "another-master-key-set-by-mistake-0123456789"  # noqa: S105


def count_signatures(app) -> int:
    with app.state.session_factory() as db:
        return db.execute(select(func.count()).select_from(Signature)).scalar_one()


def use_master_key(app, master_key: str) -> None:
    app.state.settings = app.state.settings.model_copy(update={"master_key": master_key})


def test_a_wrong_master_key_signs_nothing_and_exposes_nothing(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    right = app.state.settings.master_key
    # Two requests: the first is signed under the right key (which creates the signing key).
    first_version = publish(operator)
    first = ask(operator, first_version, get_user_id(signer), "Première")
    signed = signer.post(f"/api/documents/versions/{first_version}/sign", json={"consent": True})
    assert signed.status_code == 201, signed.text
    signature_id = signed.json()["id"]
    second_version = publish(operator)
    second = ask(operator, second_version, get_user_id(signer), "Seconde")

    use_master_key(app, WRONG)
    refused = signer.post(f"/api/documents/versions/{second_version}/sign", json={"consent": True})
    assert refused.status_code == 503
    assert "ne correspond pas" in refused.json()["detail"]
    assert WRONG not in refused.text and right not in refused.text
    # Nothing was created and nothing was closed.
    assert count_signatures(app) == 1
    assert statuses(app)[second] == "PENDING" and statuses(app)[first] == "SIGNED"
    # What was signed before stays verifiable: it relies on the recorded public key.
    assert signer.get(f"/api/signatures/{signature_id}/verify").json()["valid"] is True

    # With the right key again, everything works as before.
    use_master_key(app, right)
    again = signer.post(f"/api/documents/versions/{second_version}/sign", json={"consent": True})
    assert again.status_code == 201, again.text
    assert count_signatures(app) == 2


def test_an_administrator_can_still_rotate_to_recover_from_a_changed_master_key(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    ask(operator, version_id, get_user_id(signer), "A")
    # A signing key exists under the old master key.
    assert admin.post("/api/admin/signing-keys/rotate").status_code == 201

    use_master_key(app, WRONG)
    assert signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 503
    # Rotating replaces the key by one the new master key derives: signing works again.
    assert admin.post("/api/admin/signing-keys/rotate").status_code == 201
    recovered = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert recovered.status_code == 201, recovered.text
