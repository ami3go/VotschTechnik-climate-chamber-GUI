"""H02 permit signing tool and Settings integration (no hardware, no network)."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.hil.chamber_settings import (
    ChamberSettings, effective_hil_environment, save_settings,
)
from chamber_web.hil.profile_admission import AdmissionDenied, verify_signed_permit
from chamber_web.hil.supervised_profile import load_supervised_permit
from chamber_web.security.auth import SecurityStore
from scripts import h02_sign_permit as tool

GUI = "a" * 40
DRIVER = "b" * 40
PASSWORD = "StrongAdminPassword#1"


def _utc(delta):
    moment = datetime.now(timezone.utc).replace(microsecond=0) + delta
    return moment.isoformat().replace("+00:00", "Z")


def _spec(**overrides):
    spec = {
        "schema_version": 1, "scope": "H02_SUPERVISED_PHYSICAL_PROFILE",
        "site_method": "SM-1", "approval_reference": "AR-1",
        "chamber_id": "lab-1", "serial_number": "ABC123", "profile_id": "p1",
        "profile_revision_sha256": "c" * 64, "gui_commit": GUI, "driver_commit": DRIVER,
        "operator": "operator_user", "witness": "Witness One",
        "specimen_restrictions": "none", "temperature_min_c": 20, "temperature_max_c": 30,
        "valid_from_utc": _utc(timedelta(hours=-1)),
        "valid_until_utc": _utc(timedelta(hours=8)),
        "watchdog": dict(tool.PROPOSED_WATCHDOG),
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def keys(tmp_path, capsys):
    private = tmp_path / "site.key"
    assert tool.main(["keygen", "--private-key", str(private),
                      "--public-key-out", str(tmp_path / "site.pub")]) == 0
    return private, (tmp_path / "site.pub").read_text().strip()


def _sign(tmp_path, private, spec, answer="SIGN", monkeypatch=None, tty=True):
    # Patched at call time: pytest swaps sys.stdout between setup and call.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: tty, raising=False)
    spec_file, out = tmp_path / "spec.json", tmp_path / "permit.json"
    spec_file.write_text(json.dumps(spec))
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    code = tool.main(["sign", "--spec", str(spec_file), "--private-key", str(private),
                      "--out", str(out)])
    return code, out


def test_signed_permit_is_accepted_by_the_server_verifier(
        tmp_path, keys, monkeypatch):
    private, public = keys
    code, out = _sign(tmp_path, private, _spec(), monkeypatch=monkeypatch)
    assert code == 0
    permit = load_supervised_permit({
        "CHAMBER_H02_PERMIT_FILE": str(out), "CHAMBER_H02_TRUSTED_KEY": public})
    assert permit.data["serial_number"] == "ABC123"
    envelope = json.loads(out.read_text())
    envelope["permit"]["temperature_max_c"] = 90
    from base64 import b64decode
    with pytest.raises(AdmissionDenied):
        verify_signed_permit(envelope, trusted_site_public_key=b64decode(public))


def test_signing_refuses_automation_placeholders_and_no_confirmation(
        tmp_path, keys, monkeypatch, capsys):
    private, _ = keys
    code, out = _sign(tmp_path, private, _spec(), monkeypatch=monkeypatch, tty=False)
    assert code == 2 and not out.exists()
    code, out = _sign(tmp_path, private, _spec(witness="REPLACE_ME"), monkeypatch=monkeypatch)
    assert code == 2 and not out.exists()
    code, out = _sign(tmp_path, private, _spec(), answer="yes", monkeypatch=monkeypatch)
    assert code == 1 and not out.exists()
    code, out = _sign(tmp_path, private, _spec(temperature_min_c=40, temperature_max_c=30),
                      monkeypatch=monkeypatch)
    assert code == 2 and not out.exists()
    code, out = _sign(tmp_path, private, _spec(valid_until_utc=_utc(timedelta(days=30))),
                      monkeypatch=monkeypatch)
    assert code == 2 and not out.exists()


def test_keygen_never_overwrites_an_existing_key(tmp_path, keys):
    private, _ = keys
    with pytest.raises(FileExistsError):
        tool.main(["keygen", "--private-key", str(private)])


def test_template_has_only_placeholders_for_human_decisions(tmp_path):
    out = tmp_path / "spec.json"
    assert tool.main(["template", "--out", str(out), "--chamber-id", "lab-1",
                      "--serial", "ABC123"]) == 0
    spec = json.loads(out.read_text())
    for field in ("site_method", "approval_reference", "operator", "witness",
                  "specimen_restrictions", "temperature_min_c", "temperature_max_c"):
        assert spec[field] == "REPLACE_ME"


class TestSettingsIntegration:
    @pytest.fixture
    def setup(self, tmp_path, keys, monkeypatch):
        private, public = keys
        code, permit = _sign(tmp_path, private, _spec(), monkeypatch=monkeypatch)
        assert code == 0
        store = SecurityStore(tmp_path / "security")
        store.bootstrap_admin("admin_user", PASSWORD)
        admin = store.login("admin_user", PASSWORD)
        base = ChamberSettings(
            chamber_type="votsch", chamber_id="lab-1", address="192.168.10.20",
            expected_serial="ABC123", temperature_min_c=15.0, temperature_max_c=35.0,
            person_present_acknowledged=True, h02_permit_file=str(permit),
            h02_trusted_key=public, h02_witness="Witness One",
            gui_commit=GUI, driver_commit=DRIVER)
        path = tmp_path / "chamber_settings.json"

        def save(settings):
            return save_settings(store, admin.session, admin.csrf, PASSWORD, settings,
                                 path=path)
        return base, save, path

    def test_valid_permit_is_saved_and_exported_to_environment(self, setup):
        base, save, path = setup
        save(base)
        env, source = effective_hil_environment({}, path)
        assert source == "chamber settings"
        assert env["CHAMBER_H02_PERMIT_FILE"] == base.h02_permit_file
        assert env["CHAMBER_H02_WITNESS"] == "Witness One"
        assert env["CHAMBER_GUI_COMMIT"] == GUI
        env, _ = effective_hil_environment({"CHAMBER_H02_WITNESS": "Other"}, path)
        assert env["CHAMBER_H02_WITNESS"] == "Other"

    @pytest.mark.parametrize("change", [
        {"expected_serial": "ZZZ999"}, {"chamber_id": "other"},
        {"temperature_min_c": 25.0, "temperature_max_c": 35.0},
        {"temperature_max_c": 25.0},
        {"gui_commit": "d" * 40}, {"driver_commit": "e" * 40},
        {"h02_witness": ""}, {"h02_trusted_key": ""},
        {"h02_permit_file": "/nonexistent/permit.json"},
    ])
    def test_mismatched_or_incomplete_permit_is_refused_at_save(self, setup, change):
        base, save, path = setup
        with pytest.raises(ChamberSafetyError):
            save(replace(base, **change))
        assert not path.exists()

    def test_wrong_site_key_is_refused(self, setup, tmp_path):
        base, save, path = setup
        other = tmp_path / "other.key"
        tool.main(["keygen", "--private-key", str(other),
                   "--public-key-out", str(tmp_path / "other.pub")])
        wrong = (tmp_path / "other.pub").read_text().strip()
        with pytest.raises(ChamberSafetyError):
            save(replace(base, h02_trusted_key=wrong))

    def test_no_permit_leaves_profile_runs_disabled(self, setup):
        base, save, path = setup
        save(replace(base, h02_permit_file="", h02_trusted_key="", h02_witness=""))
        env, _ = effective_hil_environment({}, path)
        assert "CHAMBER_H02_PERMIT_FILE" not in env
