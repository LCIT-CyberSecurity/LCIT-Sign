from __future__ import annotations

import pytest

from lcit_sign.auth.oidc import OidcError, identity_from_claims

ISSUER = "https://login.microsoftonline.com/tenant-id/v2.0"


def test_keycloak_style_claims_are_used_as_is():
    who = identity_from_claims(
        {"sub": "abc", "iss": ISSUER, "email": "alice@lcit.fr", "given_name": "Alice",
         "family_name": "Martin", "name": "Alice Martin"},
        default_issuer=ISSUER,
    )
    assert (who.email, who.given_name, who.family_name) == ("alice@lcit.fr", "Alice", "Martin")


def test_entra_token_without_email_claim_uses_the_sign_in_name_and_splits_the_name():
    # What a default Microsoft Entra ID v2.0 ID token carries.
    who = identity_from_claims(
        {"sub": "pairwise-sub", "iss": ISSUER, "name": "Cédric Di Cesare",
         "preferred_username": "cedric.dicesare@lcit.fr", "oid": "x", "tid": "y"},
        default_issuer=ISSUER,
    )
    assert who.email == "cedric.dicesare@lcit.fr"
    assert (who.given_name, who.family_name) == ("Cédric", "Di Cesare")
    assert who.name == "Cédric Di Cesare"


def test_explicit_email_claim_wins_over_the_sign_in_name():
    who = identity_from_claims(
        {"sub": "s", "email": "real.mailbox@lcit.fr", "preferred_username": "upn@lcit.fr"},
        default_issuer=ISSUER,
    )
    assert who.email == "real.mailbox@lcit.fr"


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "s", "name": "No Address"},
        {"sub": "s", "preferred_username": "not-an-address"},
        {"sub": "s", "email": ""},
    ],
)
def test_a_login_without_a_usable_address_is_refused(claims):
    with pytest.raises(OidcError, match="e-mail"):
        identity_from_claims(claims, default_issuer=ISSUER)


def test_a_token_without_subject_is_refused():
    with pytest.raises(OidcError, match="subject"):
        identity_from_claims({"email": "a@lcit.fr"}, default_issuer=ISSUER)
