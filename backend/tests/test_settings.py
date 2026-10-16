"""Production storage settings fail closed."""

import pytest

from databox.settings import load_databox_settings


def test_production_gcs_requires_an_explicit_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABOX_STORAGE", "gcs")
    monkeypatch.setenv("DATABOX_TOKEN_PEPPER", "p" * 32)
    monkeypatch.setenv("DATABOX_VIEW_TOKEN_SECRET", "v" * 32)
    monkeypatch.delenv("DATABOX_GCS_BUCKET", raising=False)
    monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)

    with pytest.raises(RuntimeError, match="DATABOX_GCS_BUCKET"):
        load_databox_settings()


def test_bucket_name_rejects_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABOX_GCS_BUCKET", "gs://sanctum-vm433848-data")

    with pytest.raises(RuntimeError, match="bucket name"):
        load_databox_settings()


def test_explicit_bucket_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABOX_GCS_BUCKET", "sanctum-vm433848-data")

    assert load_databox_settings().bucket_name == "sanctum-vm433848-data"
