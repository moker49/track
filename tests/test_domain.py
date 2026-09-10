import sqlite3
import unittest

from domain import (
    TRACKING_ACTIVE,
    TRACKING_ARCHIVED,
    effective_diary_date_sql,
    move_presentation,
    progress_presentation,
)


class DomainRulesTest(unittest.TestCase):
    def test_progress_vocabulary_is_consistent(self):
        self.assertEqual(progress_presentation(TRACKING_ACTIVE, 0, 10, "Ended").label, "New")
        self.assertEqual(progress_presentation(TRACKING_ACTIVE, 3, 10, "Ended").label, "Watching")
        self.assertEqual(progress_presentation(TRACKING_ARCHIVED, 3, 10, "Ended").label, "Stopped")
        self.assertEqual(progress_presentation(TRACKING_ACTIVE, 10, 10, "Returning Series").label, "Caught up")
        self.assertEqual(progress_presentation(TRACKING_ARCHIVED, 10, 10, "Ended").label, "Finished")
        self.assertEqual(progress_presentation(TRACKING_ACTIVE, 10, 10, "Canceled").label, "Finished")

    def test_move_actions_describe_the_destination(self):
        self.assertEqual(move_presentation(TRACKING_ACTIVE).label, "Archive")
        self.assertEqual(move_presentation(TRACKING_ARCHIVED).label, "Resume")
        self.assertEqual(move_presentation(TRACKING_ARCHIVED).target_state, TRACKING_ACTIVE)

    def test_effective_date_is_the_explicit_diary_date(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE watches (diary_date TEXT)")
        db.executemany(
            "INSERT INTO watches VALUES (?)",
            [
                (None,),
                ("2008-01-20",),
            ],
        )
        dates = [
            row[0]
            for row in db.execute(
                f"SELECT {effective_diary_date_sql()} FROM watches ORDER BY rowid"
            )
        ]
        self.assertEqual(dates, [None, "2008-01-20"])
        self.assertEqual(effective_diary_date_sql("history"), "history.diary_date")
        db.close()


if __name__ == "__main__":
    unittest.main()
