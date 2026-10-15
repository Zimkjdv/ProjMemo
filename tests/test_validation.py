import pytest

from app.errors import FieldValidationError
from app.validation import RULES, normalize_fields, normalize_tokens, valid_web_url
from app.vault import VaultError, validate_master_password
from app import vault


@pytest.mark.parametrize("url", ["https://example.invalid/path?q=1#test", "http://localhost:8001/", "https://[::1]:443/a", "HTTPS://example.com", "https://xn--fiq228c.com/a"])
def test_valid_urls(url):
    assert valid_web_url(url)


@pytest.mark.parametrize("url", ["https://", "http:///path", "ftp://example.com", "https://foo bar/a", "https://example.com:99999", "https://example.com:abc", "https://example.com:0", "https://user:pass@example.com", "https://example.com\\evil", "https://a\n.b", "https://-bad.com", "https://a..b", "https://999.1.2.3"])
def test_invalid_urls(url):
    assert not valid_web_url(url)


@pytest.mark.parametrize("kind,field,limit", [(kind, field, limit) for kind, fields in RULES.items()
                                            for field, limit in fields.items() if isinstance(limit, int)])
def test_every_length_is_enforced_without_returning_the_input(kind, field, limit):
    values = {name: rule[0][0] if isinstance(rule, list) else "https://example.invalid" if name == "url" else "x"
              for name, rule in RULES[kind].items()}
    values[field] = "Z" * (limit + 1)
    with pytest.raises(FieldValidationError) as caught:
        normalize_fields(kind, values)
    assert field in caught.value.fields
    assert values[field] not in str(caught.value)


@pytest.mark.parametrize("kind,field", [(kind, field) for kind, fields in RULES.items()
                                      for field, rule in fields.items() if isinstance(rule, list)])
def test_enums_do_not_silently_change_invalid_input(kind, field):
    values = {name: rule[0][0] if isinstance(rule, list) else "https://example.invalid" if name == "url" else "x"
              for name, rule in RULES[kind].items()}
    values[field] = "unexpected"
    with pytest.raises(FieldValidationError) as caught:
        normalize_fields(kind, values)
    assert field in caught.value.fields


def test_tokens_are_normalized_and_passwords_are_not_trimmed():
    assert normalize_tokens(" Ryan， Team、ryan;API\n api ") == "Ryan, Team, API"
    values = {name: rule[0][0] if isinstance(rule, list) else "x" for name, rule in RULES["account"].items()}
    values["secret_value"] = "  exact password \n"
    result = dict(zip(RULES["account"], normalize_fields("account", values)))
    assert result["secret_value"] == values["secret_value"]


def test_master_password_limit_precedes_kdf_and_database(monkeypatch):
    monkeypatch.setattr(vault, "_derive_key", lambda *_args, **_kwargs: pytest.fail("KDF must not run"))
    for operation in [lambda: validate_master_password("x" * 1025), lambda: vault.unlock_vault(None, "x" * 1025), lambda: vault.create_vault(None, "x" * 1025)]:
        with pytest.raises(VaultError, match="1024"):
            operation()
