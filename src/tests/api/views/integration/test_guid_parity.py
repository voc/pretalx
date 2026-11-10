# SPDX-FileCopyrightText: 2026-present Tobias Kunze
# SPDX-License-Identifier: AGPL-3.0-only WITH LicenseRef-Pretalx-AGPL-3.0-Terms

import datetime as dt
import json
import re

import pytest
from django_scopes import scope, scopes_disabled

from pretalx.schedule.domain.release import freeze_schedule
from pretalx.schedule.interfaces.exporters import FrabJsonExporter, FrabXmlExporter
from pretalx.schedule.models import TalkSlot
from pretalx.submission.models import SubmissionStates
from tests.factories import RoomFactory, SubmissionFactory, TalkSlotFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _frab_json_guids_by_date(schedule, event):
    with scope(event=event):
        data = json.loads(FrabJsonExporter(schedule).get_data())
    return {
        (talk["code"], talk["date"]): talk["guid"]
        for day in data["schedule"]["conference"]["days"]
        for room_talks in day["rooms"].values()
        for talk in room_talks
    }


def _frab_xml_guids_by_code(schedule, event):
    with scope(event=event):
        xml = FrabXmlExporter(schedule).get_data()
    # Extract `guid='...'` / `code='...'` pairs without a full XML parser.
    return {
        match.group(2): match.group(1)
        for match in re.finditer(r"<event guid='([^']+)' id='\d+' code='([^']+)'", xml)
    }


def test_api_submission_and_slot_uuid_match_frab_export_guid(
    client, published_talk_slot
):
    slot = published_talk_slot
    submission = slot.submission
    event = submission.event
    with scopes_disabled():
        schedule = event.current_schedule

    json_guids = _frab_json_guids_by_date(schedule, event)
    xml_guids = _frab_xml_guids_by_code(schedule, event)
    expected_guid = json_guids[(submission.code, slot.local_start.isoformat())]
    assert xml_guids[submission.code] == expected_guid

    slot_response = client.get(event.api_urls.slots + f"{slot.pk}/")
    submission_response = client.get(event.api_urls.submissions + f"{submission.code}/")

    assert slot_response.status_code == 200
    assert submission_response.status_code == 200
    assert slot_response.json()["uuid"] == expected_guid
    assert submission_response.json()["uuid"] == expected_guid


def test_api_slot_uuid_matches_frab_guid_with_present_multiple_times(client, event):
    event.feature_flags["present_multiple_times"] = True
    event.save()
    with scopes_disabled():
        submission = SubmissionFactory(event=event, state=SubmissionStates.CONFIRMED)
        early = TalkSlotFactory(submission=submission, is_visible=True)
        TalkSlotFactory(
            submission=submission,
            schedule=early.schedule,
            is_visible=True,
            start=early.start + dt.timedelta(hours=2),
            end=early.end + dt.timedelta(hours=2),
        )
        with scope(event=event):
            freeze_schedule(event.wip_schedule, "v1", notify_speakers=False)
        schedule = event.current_schedule
        early, late = (
            schedule.talks.select_related("submission", "submission__event")
            .filter(submission=submission)
            .order_by("start")
        )

    json_guids = _frab_json_guids_by_date(schedule, event)

    early_response = client.get(event.api_urls.slots + f"{early.pk}/")
    late_response = client.get(event.api_urls.slots + f"{late.pk}/")
    submission_response = client.get(event.api_urls.submissions + f"{submission.code}/")

    assert early_response.status_code == 200
    assert late_response.status_code == 200
    assert early_response.json()["uuid"] != late_response.json()["uuid"]
    assert (
        early_response.json()["uuid"]
        == json_guids[(submission.code, early.local_start.isoformat())]
    )
    assert (
        late_response.json()["uuid"]
        == json_guids[(submission.code, late.local_start.isoformat())]
    )
    # The bare submission uuid (no slot suffix) differs from both slot uuids,
    # since the talk is presented more than once.
    assert submission_response.json()["uuid"] not in {
        early_response.json()["uuid"],
        late_response.json()["uuid"],
    }


def test_api_break_slot_uuid_is_its_persistent_guid(client, published_talk_slot):
    event = published_talk_slot.submission.event
    with scopes_disabled():
        room = RoomFactory(event=event)
        break_slot = TalkSlotFactory(
            submission=None,
            room=room,
            schedule=event.current_schedule,
            is_visible=True,
            start=event.datetime_from,
            end=event.datetime_from,
        )

    response = client.get(event.api_urls.slots + f"{break_slot.pk}/")

    assert response.status_code == 200
    assert response.json()["uuid"] == str(break_slot.guid)


def test_api_break_slot_uuid_survives_schedule_release_and_move(client, event):
    with scopes_disabled():
        room = RoomFactory(event=event)
        break_slot = TalkSlotFactory(
            submission=None,
            room=room,
            schedule=event.wip_schedule,
            is_visible=True,
            slot_type="break",
            start=event.datetime_from,
            end=event.datetime_from + dt.timedelta(minutes=30),
        )
        original_guid = break_slot.guid
        with scope(event=event):
            freeze_schedule(event.wip_schedule, "v1", notify_speakers=False)
        released_break = event.current_schedule.talks.get(submission=None)
        assert released_break.pk == break_slot.pk
        assert released_break.guid == original_guid

        # The next WIP schedule holds a copied row with a new pk, but the same guid.
        wip_break = event.wip_schedule.talks.get(submission=None)
        assert wip_break.pk != released_break.pk
        assert wip_break.guid == original_guid

        # Moving the break (new room, new time) in that WIP schedule...
        other_room = RoomFactory(event=event)
        wip_break.room = other_room
        wip_break.start = event.datetime_from + dt.timedelta(hours=3)
        wip_break.end = wip_break.start + dt.timedelta(hours=1)
        wip_break.save()

    response = client.get(event.api_urls.slots + f"{released_break.pk}/")

    # ...does not change the guid of the already-released slot.
    assert response.status_code == 200
    assert response.json()["uuid"] == str(original_guid)
    assert wip_break.guid == original_guid


def test_api_blocker_uuid_not_exposed_publicly(client, orga_read_token, event):
    with scopes_disabled():
        room = RoomFactory(event=event)
        blocker = TalkSlotFactory(
            submission=None,
            room=room,
            schedule=event.wip_schedule,
            is_visible=True,
            slot_type="blocker",
            start=event.datetime_from,
            end=event.datetime_from,
        )

    anonymous = client.get(event.api_urls.slots + f"{blocker.pk}/")
    orga = client.get(
        f"{event.api_urls.slots}?schedule={event.wip_schedule.pk}",
        headers={"Authorization": f"Token {orga_read_token.token}"},
    )

    assert anonymous.status_code == 404
    assert orga.status_code == 200
    (result,) = orga.json()["results"]
    assert result["uuid"] == str(blocker.guid)


def test_api_slot_uuid_not_leaked_for_invisible_slot_to_anonymous(
    client, orga_read_token, published_talk_slot
):
    event = published_talk_slot.submission.event
    with scopes_disabled():
        hidden_sub = SubmissionFactory(event=event, state=SubmissionStates.CONFIRMED)
        TalkSlotFactory(submission=hidden_sub, is_visible=True)
        with scope(event=event):
            freeze_schedule(event.wip_schedule, "v2", notify_speakers=False)
        slot = event.current_schedule.talks.get(submission=hidden_sub)
        slot.is_visible = False
        slot.save()
        slot = TalkSlot.objects.select_related("submission", "submission__event").get(
            pk=slot.pk
        )

    anonymous = client.get(event.api_urls.slots + f"{slot.pk}/")
    orga = client.get(
        event.api_urls.slots + f"{slot.pk}/",
        headers={"Authorization": f"Token {orga_read_token.token}"},
    )

    assert anonymous.status_code == 404
    assert orga.status_code == 200
    assert orga.json()["uuid"] == str(slot.uuid)
