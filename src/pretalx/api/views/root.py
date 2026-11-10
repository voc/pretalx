# SPDX-FileCopyrightText: 2025-present Tobias Kunze
# SPDX-License-Identifier: AGPL-3.0-only WITH LicenseRef-Pretalx-AGPL-3.0-Terms

from django.conf import settings
from django.urls import reverse
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from pretalx.api.documentation import extend_schema
from pretalx.api.versions import CURRENT_VERSION
from pretalx.common.models.settings import GlobalSettings


class RootUrlsSerializer(serializers.Serializer):
    events = serializers.URLField()


class RootSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.CharField()
    api_version = serializers.CharField()
    instance_identifier = serializers.UUIDField(
        help_text="A UUID that is unique to, and stable for, this pretalx "
        "instance. It is used, together with a proposal's code, to calculate "
        "the stable UUIDs (``uuid``/``guid``) of proposals and talk slots, "
        "both in the API and in schedule exports. It is not a secret: it is "
        "already embedded in every public schedule export."
    )
    urls = RootUrlsSerializer()


class RootView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="API Root",
        description="Returns a link to the REST API, as well as the pretalx and API versions.",
        tags=["root"],
        responses={200: RootSerializer},
    )
    def get(self, request):
        return Response(
            {
                "name": "pretalx",
                "version": settings.PRETALX_VERSION,
                "api_version": CURRENT_VERSION,
                "instance_identifier": GlobalSettings().get_instance_identifier(),
                "urls": {"events": settings.SITE_URL + reverse("api:event-list")},
            }
        )
