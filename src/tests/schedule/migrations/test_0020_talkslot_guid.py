# SPDX-FileCopyrightText: 2026-present Tobias Kunze
# SPDX-License-Identifier: AGPL-3.0-only WITH LicenseRef-Pretalx-AGPL-3.0-Terms

import importlib

import pytest
from django_scopes import scopes_disabled

from pretalx.schedule.domain.release import freeze_schedule
from pretalx.schedule.models import TalkSlot
from tests.factories import RoomFactory, ScheduleFactory, TalkSlotFactory

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

_migration = importlib.import_module(
    "pretalx.schedule.migrations.0020_talkslot_guid_alter_talkslot_unique_together"
)


class _LiveApps:
    """Stands in for the historical ``apps`` registry RunPython migrations
    receive, resolving to the real (current) model instead, since the
    backfill function only uses generic ORM/field access."""

    @staticmethod
    def get_model(app_label, model_name):
        assert (app_label, model_name) == ("schedule", "TalkSlot")
        return TalkSlot


def test_backfill_break_guids_is_noop_without_candidates():
    TalkSlotFactory()  # has a submission, never touched

    _migration.backfill_break_guids(_LiveApps(), None)

    assert (
        not TalkSlot.objects.exclude(submission=None)
        .filter(guid__isnull=False)
        .exists()
    )


def test_backfill_break_guids_assigns_fresh_guids_per_distinct_break():
    with scopes_disabled():
        schedule = ScheduleFactory()
        room = RoomFactory(event=schedule.event)
        a = TalkSlotFactory(submission=None, schedule=schedule, room=room)
        b = TalkSlotFactory(submission=None, schedule=schedule, room=room)
        # Bypass the save() override to simulate pre-migration (guid-less) data.
        TalkSlot.objects.filter(pk__in=[a.pk, b.pk]).update(guid=None)

    _migration.backfill_break_guids(_LiveApps(), None)

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.guid is not None
    assert b.guid is not None
    assert a.guid != b.guid


def test_backfill_break_guids_unifies_exact_duplicate_across_schedule_releases():
    with scopes_disabled():
        event = ScheduleFactory().event
        room = RoomFactory(event=event)
        original = TalkSlotFactory(
            submission=None,
            schedule=event.wip_schedule,
            room=room,
            slot_type="break",
            description="Lunch",
        )
        with_scope = original.start, original.end
        freeze_schedule(event.wip_schedule, "v1", notify_speakers=False)
        released = event.schedules.get(version="v1").talks.get(submission=None)
        copied = event.wip_schedule.talks.get(submission=None)
        # Bypass the save() override to simulate pre-migration (guid-less) data,
        # for both historical copies of the same, never-edited break.
        TalkSlot.objects.filter(pk__in=[released.pk, copied.pk]).update(guid=None)

    _migration.backfill_break_guids(_LiveApps(), None)

    released.refresh_from_db()
    copied.refresh_from_db()
    assert released.guid is not None
    assert released.guid == copied.guid
    assert with_scope == (original.start, original.end)


def test_backfill_break_guids_does_not_touch_existing_guids():
    with scopes_disabled():
        slot = TalkSlotFactory(submission=None, schedule=ScheduleFactory(), room=None)
        existing_guid = slot.guid
        assert existing_guid is not None

    _migration.backfill_break_guids(_LiveApps(), None)

    slot.refresh_from_db()
    assert slot.guid == existing_guid
