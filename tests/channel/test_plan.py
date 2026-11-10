from datetime import date

from shorts.channel.plan import CHECKPOINTS, PLAN_START, next_checkpoint, plan_week


def test_the_plan_starts_on_monday_9_november_2026():
    assert PLAN_START == date(2026, 11, 9)


def test_week_one_covers_its_first_seven_days():
    assert plan_week(date(2026, 11, 9)).number == 1
    assert plan_week(date(2026, 11, 15)).number == 1
    assert plan_week(date(2026, 11, 16)).number == 2


def test_each_week_has_a_title_and_things_to_do():
    week = plan_week(date(2026, 11, 17))
    assert "long" in week.title.lower()
    assert week.todo


def test_outside_the_90_days_there_is_no_week():
    assert plan_week(date(2026, 11, 8)) is None
    assert plan_week(date(2027, 2, 8)) is None


def test_the_next_checkpoint_is_the_first_still_ahead():
    assert next_checkpoint(date(2026, 11, 10)).day == 30
    assert next_checkpoint(date(2026, 12, 20)).day == 60
    assert next_checkpoint(date(2027, 3, 1)) is None


def test_checkpoints_follow_the_plans_targets():
    day30 = CHECKPOINTS[0]
    assert (day30.subscribers, day30.shorts_over_5k, day30.watch_hours) == (100, 1, 50)
    assert day30.date == date(2026, 12, 9)
