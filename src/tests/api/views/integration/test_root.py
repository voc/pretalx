# SPDX-FileCopyrightText: 2026-present Tobias Kunze
# SPDX-License-Identifier: AGPL-3.0-only WITH LicenseRef-Pretalx-AGPL-3.0-Terms
import uuid

import pytest
from django.conf import settings

from pretalx.api.versions import CURRENT_VERSION
from pretalx.common.models.settings import GlobalSettings

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_root_returns_api_metadata(client):
    response = client.get("/api/")

    assert response.status_code == 200
    data = response.json()
    instance_identifier = data.pop("instance_identifier")
    assert uuid.UUID(instance_identifier) == GlobalSettings().get_instance_identifier()
    assert data == {
        "name": "pretalx",
        "version": settings.PRETALX_VERSION,
        "api_version": CURRENT_VERSION,
        "urls": {"events": settings.SITE_URL + "/api/events/"},
    }


def test_root_instance_identifier_is_stable(client):
    first = client.get("/api/").json()["instance_identifier"]
    second = client.get("/api/").json()["instance_identifier"]

    assert first == second
