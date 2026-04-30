from redmine import compute_subject_prefix_counters


def test_compute_subject_prefix_counters_finds_max_by_prefix():
    subjects = [
        "[E1] First epic",
        "[E12] Later epic",
        "[S3] First story",
        "[S10] Later story",
        "[T7] A task",
        "No prefix here",
        "[X99] Unknown prefix",
        "   [E2] Leading whitespace should be ignored",
        "[T2] Earlier task",
    ]

    assert compute_subject_prefix_counters(subjects) == {"E": 12, "S": 10, "T": 7}

