from vc_agent.feedback.long_connection import RecentMessageDeduper


def test_recent_message_deduper_skips_duplicate_message_ids():
    deduper = RecentMessageDeduper(ttl_seconds=60)

    assert deduper.should_process("om_test_message") is True
    assert deduper.should_process("om_test_message") is False
    assert deduper.should_process("om_other_message") is True
