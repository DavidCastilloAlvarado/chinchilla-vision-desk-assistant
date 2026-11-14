import pytest

from chinchilla.core import permission


def test_app_id_reads_the_systemd_scope():
    cgroup = (
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
        "app-com.microsoft.VSCode-4242.scope\n"
    )

    assert permission.app_id(cgroup) == "com.microsoft.VSCode"


def test_app_id_is_empty_without_a_scope():
    assert permission.app_id("0::/user.slice/user-1000.slice/session-2.scope") == ""


def test_app_id_unescapes_systemd_units():
    cgroup = "app-org\\x2dgnome\\x2dCalculator-91.scope"

    assert permission.app_id(cgroup) == "org-gnome-Calculator"


def test_app_id_uses_the_live_cgroup_when_not_given():
    assert isinstance(permission.app_id(), str)


def test_is_granted_checks_the_lookup_result(monkeypatch):
    monkeypatch.setattr(permission, "permissions", lambda target=None: ["yes"])
    assert permission.is_granted() is True

    monkeypatch.setattr(permission, "permissions", lambda target=None: ["no"])
    assert permission.is_granted() is False


def test_is_granted_is_false_when_the_store_is_missing(monkeypatch):
    def boom(target=None):
        raise permission.PermissionError_("no store")

    monkeypatch.setattr(permission, "permissions", boom)

    assert permission.is_granted() is False


def test_ensure_grants_once(monkeypatch):
    stored: list[str] = []

    monkeypatch.setattr(permission, "app_id", lambda cgroup=None: "some.app")
    monkeypatch.setattr(permission, "permissions", lambda target=None: list(stored))

    def grant(target=None):
        stored.append(permission.GRANTED)
        return True

    monkeypatch.setattr(permission, "grant", grant)

    ok, detail = permission.ensure()

    assert ok is True
    assert "some.app" in detail
    assert stored == [permission.GRANTED]

    ok, _detail = permission.ensure()

    assert ok is True
    assert stored == [permission.GRANTED]


def test_ensure_reports_a_missing_store(monkeypatch):
    def boom(target=None):
        raise permission.PermissionError_("no store")

    monkeypatch.setattr(permission, "permissions", boom)

    ok, detail = permission.ensure()

    assert ok is False
    assert "no store" in detail


def test_describe_mentions_the_state_and_app_id(monkeypatch):
    monkeypatch.setattr(permission, "app_id", lambda cgroup=None: "some.app")
    monkeypatch.setattr(permission, "permissions", lambda target=None: ["yes"])

    assert permission.describe() == "granted (app id 'some.app')"

    monkeypatch.setattr(permission, "permissions", lambda target=None: [])

    assert permission.describe() == "missing (app id 'some.app')"


def test_grant_and_revoke_fail_softly(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bus is gone")

    monkeypatch.setattr(permission, "_call", boom)

    assert permission.grant() is False
    assert permission.revoke() is False


def test_permissions_unpack_the_lookup_reply(monkeypatch):
    class Reply:
        def unpack(self):
            return ({"some.app": ["yes"]}, None)

    monkeypatch.setattr(permission, "app_id", lambda cgroup=None: "some.app")
    monkeypatch.setattr(permission, "_call", lambda *args, **kwargs: Reply())

    assert permission.permissions() == ["yes"]


def test_unreadable_store_raises_a_permission_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no bus")

    monkeypatch.setattr(permission, "_call", boom)

    with pytest.raises(permission.PermissionError_):
        permission.permissions()