from __future__ import annotations

from switchtime.providers.ixl_extract import candidate_to_lesson, extract_lessons, slugify, walk

TODAY = "2026-09-07"


class TestWalk:
    def test_finds_dicts_at_every_depth(self):
        blob = {"a": {"b": [{"c": 1}, {"d": 2}]}}
        assert len(list(walk(blob))) == 4  # root, a, c-dict, d-dict

    def test_handles_scalars(self):
        assert list(walk(5)) == []


class TestCandidate:
    def test_name_plus_score_qualifies(self):
        lesson = candidate_to_lesson(
            {"skillName": "Add fractions", "smartScore": 100}, today=TODAY
        )
        assert lesson is not None
        assert lesson.title == "Add fractions"
        assert lesson.smartscore == 100

    def test_name_alone_is_rejected(self):
        # Page furniture is full of bare names; without a score or a date there
        # is nothing to say work was done.
        assert candidate_to_lesson({"name": "Maths"}, today=TODAY) is None

    def test_navigation_words_are_ignored(self):
        assert candidate_to_lesson({"name": "Sign in", "score": 100}, today=TODAY) is None

    def test_score_outside_smartscore_range_is_not_a_score(self):
        # An id that happened to sit under a "score"-ish key must not qualify.
        assert candidate_to_lesson({"title": "Whatever", "level": 99999}, today=TODAY) is None

    def test_date_alone_is_enough(self):
        lesson = candidate_to_lesson(
            {"skillName": "Long division", "completedAt": "2026-09-05T10:00:00Z"}, today=TODAY
        )
        assert lesson is not None and lesson.day == "2026-09-05"

    def test_ref_includes_the_day_so_tomorrow_earns_again(self):
        today_lesson = candidate_to_lesson({"skillId": "D7", "name": "X", "smartScore": 90}, today=TODAY)
        other = candidate_to_lesson(
            {"skillId": "D7", "name": "X", "smartScore": 90, "date": "2026-09-08"}, today=TODAY
        )
        assert today_lesson.ref != other.ref

    def test_same_skill_twice_in_a_day_shares_a_ref(self):
        first = candidate_to_lesson({"skillId": "D7", "name": "X", "smartScore": 85}, today=TODAY)
        second = candidate_to_lesson({"skillId": "D7", "name": "X", "smartScore": 100}, today=TODAY)
        assert first.ref == second.ref

    def test_epoch_millis_are_understood(self):
        lesson = candidate_to_lesson(
            {"name": "Shapes", "smartScore": 100, "timestamp": 1757246400000}, today=TODAY
        )
        assert lesson is not None and lesson.day.startswith("2025-")

    def test_us_date_format(self):
        lesson = candidate_to_lesson(
            {"name": "Shapes", "smartScore": 100, "date": "09/05/2026"}, today=TODAY
        )
        assert lesson.day == "2026-09-05"


class TestExtract:
    def test_pulls_lessons_out_of_a_realistic_nested_payload(self):
        payload = {
            "data": {
                "student": {"id": 42},
                "practice": [
                    {"skillId": "7ab", "skillName": "Add fractions", "smartScore": 100,
                     "date": TODAY, "subject": "Maths"},
                    {"skillId": "9cd", "skillName": "Commas", "smartScore": 60, "date": TODAY},
                ],
            },
            "nav": [{"name": "Sign out"}],
        }
        lessons = extract_lessons([payload], today=TODAY, min_smartscore=80)
        assert [l.title for l in lessons] == ["Add fractions"]
        assert lessons[0].subject == "Maths"

    def test_min_smartscore_zero_accepts_anything_practised(self):
        payload = [{"skillName": "Commas", "smartScore": 40, "date": TODAY}]
        assert len(extract_lessons([payload], today=TODAY, min_smartscore=0)) == 1

    def test_deduplicates_across_payloads_keeping_the_best_score(self):
        a = [{"skillId": "x", "skillName": "Add", "smartScore": 85, "date": TODAY}]
        b = [{"skillId": "x", "skillName": "Add", "smartScore": 100, "date": TODAY}]
        lessons = extract_lessons([a, b], today=TODAY, min_smartscore=80)
        assert len(lessons) == 1 and lessons[0].smartscore == 100

    def test_since_day_filters_out_old_work(self):
        payload = [{"skillName": "Old", "smartScore": 100, "date": "2026-01-01"}]
        assert extract_lessons([payload], today=TODAY, since_day="2026-09-01") == []

    def test_empty_input(self):
        assert extract_lessons([], today=TODAY) == []

    def test_survives_a_key_rename(self):
        # The point of the heuristic: IXL renaming skillName to title must not
        # break credit.
        payload = [{"title": "Add fractions", "currentScore": 100, "when": TODAY}]
        assert len(extract_lessons([payload], today=TODAY, min_smartscore=80)) == 1


def test_slugify():
    assert slugify("Add & subtract fractions!") == "add-subtract-fractions"
