from __future__ import annotations

from debrid_hub.models import DebridLink, decode_id


def make_link(**overrides):
    defaults = dict(
        provider="mock",
        name="Show.S01E01.mkv",
        size=123,
        host="mock",
        kind="torrent",
        added="2026-01-01T00:00:00Z",
        direct_url=None,
        resolve_hint={"k": "direct", "u": "https://example.com/x"},
    )
    defaults.update(overrides)
    return DebridLink(**defaults)


def test_compute_id_is_deterministic_for_same_provider_and_hint():
    a = make_link()
    b = make_link(name="different name, same hint")
    assert a.compute_id() == b.compute_id(), "id must depend on provider+hint, not name"


def test_compute_id_differs_for_different_hint():
    a = make_link(resolve_hint={"k": "direct", "u": "https://example.com/x"})
    b = make_link(resolve_hint={"k": "direct", "u": "https://example.com/y"})
    assert a.compute_id() != b.compute_id()


def test_decode_id_round_trips():
    link = make_link()
    token = link.compute_id()
    decoded = decode_id(token)
    assert decoded == {"p": "mock", "h": {"k": "direct", "u": "https://example.com/x"}}


def test_decode_id_handles_missing_base64_padding():
    # base64url tokens have their '=' padding stripped in compute_id(); decode_id
    # must tolerate any padding length, not just the one case that happened to
    # come up first.
    for name in ["a", "ab", "abc", "abcd", "abcde"]:
        link = make_link(name=name, resolve_hint={"k": "direct", "u": name})
        token = link.compute_id()
        assert "=" not in token
        assert decode_id(token)["h"]["u"] == name


def test_to_dict_never_leaks_resolve_hint():
    link = make_link(resolve_hint={"k": "direct", "u": "https://secret.example/token123"})
    d = link.to_dict()
    assert "resolve_hint" not in d
    assert "secret.example" not in str(d)


def test_to_dict_resolvable_true_when_no_direct_url():
    link = make_link(direct_url=None)
    assert link.to_dict()["resolvable"] is True


def test_to_dict_resolvable_false_when_direct_url_present():
    link = make_link(direct_url="https://example.com/direct.mkv")
    assert link.to_dict()["resolvable"] is False


def test_to_dict_id_is_computed_if_not_already_set():
    link = make_link()
    assert link.id == ""
    d = link.to_dict()
    assert d["id"] == link.compute_id()


def test_to_dict_uses_preset_id_if_already_set():
    link = make_link()
    link.id = "preset-id"
    assert link.to_dict()["id"] == "preset-id"
