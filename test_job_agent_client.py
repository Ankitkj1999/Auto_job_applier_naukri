"""
test_job_agent_client.py - Unit tests for Naukri Job Apply Agent (Neo) client
"""

import pytest
from unittest.mock import MagicMock, patch
from job_agent_client import (
    in_browser_fetch,
    get_agent_response,
    post_agent_action,
    confirm_preferences_if_needed,
    apply_to_eligible_agent_jobs,
    handle_custom_questions_if_needed,
    run_job_apply_agent_stage,
)


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    driver.current_url = "https://www.naukri.com/job-apply-agent"
    return driver


@pytest.fixture
def sample_config():
    return {
        "personals": {
            "full_name": "Ankit Kumar",
            "notice_period_days": 30,
            "current_ctc_lpa": 20,
            "expected_ctc_lpa": 24,
            "total_experience_years": 3.5,
        },
        "search": {
            "search_terms": ["Data Engineer", "PySpark Developer"],
            "locations": ["Gurgaon", "Noida"],
            "bad_words": ["intern", "lead", "manager", "qa", "tester"],
            "mandatory_keywords": ["data", "spark", "python"],
        },
        "settings": {
            "daily_application_ceiling": 40,
        },
    }


def test_in_browser_fetch_success(mock_driver):
    mock_driver.execute_async_script.return_value = {
        "status": 200,
        "ok": True,
        "data": {"nodeType": "jobListing", "conversationId": "conv_123"},
    }
    result = in_browser_fetch(mock_driver, "https://www.naukri.com/test", method="GET")
    assert result["status"] == 200
    assert result["ok"] is True
    assert result["data"]["nodeType"] == "jobListing"
    mock_driver.execute_async_script.assert_called_once()


def test_in_browser_fetch_failure(mock_driver):
    mock_driver.execute_async_script.side_effect = Exception("Browser script failed")
    result = in_browser_fetch(mock_driver, "https://www.naukri.com/test")
    assert result["ok"] is False
    assert "Browser script failed" in result["error"]


def test_confirm_preferences_if_needed(mock_driver, sample_config):
    agent_data = {
        "nodeType": "userPreference",
        "conversationId": "conv_999",
    }
    with patch("job_agent_client.post_agent_action") as mock_post:
        mock_post.return_value = {"status": "ok"}
        handled = confirm_preferences_if_needed(mock_driver, sample_config, agent_data)
        assert handled is True
        assert mock_post.call_count == 2
        # First call saves preferences, second call acknowledges consent
        actions = [call.kwargs["action"] for call in mock_post.call_args_list]
        assert "savePreferences" in actions
        assert "confirmConsent" in actions


def test_confirm_preferences_not_needed(mock_driver, sample_config):
    agent_data = {
        "nodeType": "jobListing",
        "conversationId": "conv_999",
    }
    handled = confirm_preferences_if_needed(mock_driver, sample_config, agent_data)
    assert handled is False


def test_apply_to_eligible_agent_jobs_filters_correctly(mock_driver, sample_config):
    agent_data = {
        "nodeType": "jobListing",
        "conversationId": "conv_abc",
        "jobs": [
            {
                "jobId": "1001",
                "title": "Data Engineer - PySpark",
                "companyName": "TechCorp",
                "location": "Gurgaon",
                "jobUrl": "https://www.naukri.com/job-1001",
            },
            {
                "jobId": "1002",
                "title": "Senior QA Tester",
                "companyName": "BugFree",
                "location": "Noida",
                "jobUrl": "https://www.naukri.com/job-1002",
            },
            {
                "jobId": "1003",
                "title": "AWS Data Platform Engineer",
                "companyName": "CloudScale",
                "location": "Gurgaon",
                "jobUrl": "https://www.naukri.com/job-1003",
            },
        ],
    }

    with patch("job_agent_client.load_applied_job_ids", return_value=set()), \
         patch("job_agent_client.post_agent_action", return_value={"ok": True}), \
         patch("job_agent_client.record_applied_job") as mock_record, \
         patch("time.sleep"):  # Speed up tests
        count = apply_to_eligible_agent_jobs(mock_driver, sample_config, agent_data)
        assert count == 2  # QA Tester should be skipped
        assert mock_record.call_count == 2
        recorded_titles = [call.kwargs["title"] for call in mock_record.call_args_list]
        assert "Data Engineer - PySpark" in recorded_titles
        assert "AWS Data Platform Engineer" in recorded_titles
        assert "Senior QA Tester" not in recorded_titles


def test_handle_custom_questions_if_needed(mock_driver, sample_config):
    agent_data = {
        "nodeType": "CQJobNode",
        "questions": [
            {"id": "q1", "question": "What is your official notice period?"},
            {"id": "q2", "question": "Total relevant experience in years?"},
            {"id": "q3", "question": "Current CTC in LPA?"},
        ],
    }

    with patch("job_agent_client.in_browser_fetch") as mock_fetch, \
         patch("time.sleep"):
        mock_fetch.return_value = {"ok": True}
        handled = handle_custom_questions_if_needed(mock_driver, sample_config, agent_data)
        assert handled is True
        mock_fetch.assert_called_once()
        body = mock_fetch.call_args.kwargs["body"]
        answers = {a["questionId"]: a["answer"] for a in body["answers"]}
        assert answers["q1"] == "30"
        assert answers["q2"] == "3.5"
        assert answers["q3"] == "20"


def test_run_job_apply_agent_stage_paywall_fallback(mock_driver, sample_config):
    mock_driver.current_url = "https://www.naukri.com/naukri360-pro"
    applied = run_job_apply_agent_stage(mock_driver, sample_config)
    assert applied == 0


def test_get_agent_response_logs_warning_on_failure(mock_driver, caplog):
    import logging
    with patch("job_agent_client.in_browser_fetch", return_value={"status": 404, "ok": False, "error": "Not Found"}):
        with caplog.at_level(logging.WARNING):
            res = get_agent_response(mock_driver)
            assert res == {}
            assert "Failed to fetch agent response: HTTP 404" in caplog.text


def test_main_dedicated_agent_mode_does_not_unwantedly_fallback():
    from main import main
    with patch("sys.argv", ["main.py", "agent"]), \
         patch("main.load_config", return_value={"settings": {"chrome_profile_dir": "/tmp/dummy", "headless": True, "daily_application_ceiling": 45}}), \
         patch("main.get_chrome_driver") as mock_driver, \
         patch("main.ensure_login"), \
         patch("main.run_job_apply_agent_stage", return_value=0) as mock_agent_stage, \
         patch("main.apply_to_naukri_jobs") as mock_apply:

        main()
        mock_agent_stage.assert_called_once()
        # In dedicated agent mode, do not trigger standard search-apply fallback
        mock_apply.assert_not_called()


def test_main_full_automation_runs_both_agent_and_search():
    from main import main
    with patch("sys.argv", ["main.py", "all"]), \
         patch("main.load_config", return_value={"settings": {"chrome_profile_dir": "/tmp/dummy", "headless": True, "daily_application_ceiling": 45}}), \
         patch("main.get_chrome_driver") as mock_driver, \
         patch("main.ensure_login"), \
         patch("main.boost_profile"), \
         patch("main.run_job_apply_agent_stage", return_value=5) as mock_agent_stage, \
         patch("main.apply_to_naukri_jobs") as mock_apply:

        main()
        mock_agent_stage.assert_called_once()
        mock_apply.assert_called_once()


def test_handle_preferences_confirmation_dom_success(mock_driver):
    from job_agent_client import handle_preferences_confirmation_dom
    mock_driver.execute_script.return_value = {"clicked": True, "text": "These are correct!"}
    with patch("time.sleep"):
        result = handle_preferences_confirmation_dom(mock_driver)
        assert result is True


def test_handle_preferences_confirmation_dom_none_found(mock_driver):
    from job_agent_client import handle_preferences_confirmation_dom
    mock_driver.execute_script.return_value = {"clicked": False}
    result = handle_preferences_confirmation_dom(mock_driver)
    assert result is False


def test_extract_agent_job_cards_dom(mock_driver):
    from job_agent_client import extract_agent_job_cards_dom
    mock_driver.execute_script.return_value = [
        {
            "jobId": "12345",
            "title": "Data Engineer",
            "company": "TechCorp",
            "location": "Gurugram",
            "jobUrl": "https://www.naukri.com/job-listings-12345",
            "checked": False,
        }
    ]
    cards = extract_agent_job_cards_dom(mock_driver)
    assert len(cards) == 1
    assert cards[0]["jobId"] == "12345"
    assert cards[0]["title"] == "Data Engineer"


def test_sync_card_selection_dom(mock_driver):
    from job_agent_client import sync_card_selection_dom
    mock_driver.execute_script.return_value = {"selectedCount": 2, "unselectedCount": 1}
    res = sync_card_selection_dom(mock_driver, {"101", "102"})
    assert res["selectedCount"] == 2
    assert res["unselectedCount"] == 1


def test_click_apply_action_pill_dom(mock_driver):
    from job_agent_client import click_apply_action_pill_dom
    mock_driver.execute_script.return_value = {"clicked": True, "text": "Apply to selected ones"}
    clicked, text = click_apply_action_pill_dom(mock_driver)
    assert clicked is True
    assert text == "Apply to selected ones"


def test_handle_today_recommendations_pill_dom(mock_driver):
    from job_agent_client import handle_today_recommendations_pill_dom
    mock_driver.execute_script.return_value = True
    with patch("time.sleep"):
        res = handle_today_recommendations_pill_dom(mock_driver)
        assert res is True


def test_handle_neo_interactive_flow(mock_driver, sample_config):
    from job_agent_client import handle_neo_interactive_flow
    eligible = [
        {"jobId": "9001", "title": "Data Engineer", "company": "Acme", "location": "Noida", "jobUrl": "https://naukri.com/9001"},
        {"jobId": "9002", "title": "Cloud Data Eng", "company": "Beta", "location": "Delhi", "jobUrl": "https://naukri.com/9002"},
    ]
    # First iteration: no drawer, action: finish. Then remaining cards: only 9002 (so 9001 was submitted)
    mock_driver.execute_script.side_effect = [
        {"action": "finish", "text": "Finish"},  # action pill check
        [{"jobId": "9002", "title": "Cloud Data Eng"}],  # remaining cards extraction
    ]

    with patch("job_agent_client.find_drawer", return_value=None), \
         patch("job_agent_client.load_applied_job_ids", return_value=set()), \
         patch("job_agent_client.record_applied_job") as mock_record, \
         patch("time.sleep"):

        applied = handle_neo_interactive_flow(mock_driver, sample_config, eligible, max_wait_sec=5)
        assert applied == 1
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["job_id"] == "9001"


def test_handle_neo_interactive_flow_with_drawer(mock_driver, sample_config):
    from job_agent_client import handle_neo_interactive_flow
    eligible = [
        {"jobId": "9001", "title": "Data Engineer", "company": "Capgemini", "location": "Noida", "jobUrl": "https://naukri.com/9001"},
    ]
    mock_drawer = MagicMock()
    # Iteration 1: drawer found; Iteration 2: drawer closed, action finish
    mock_driver.execute_script.side_effect = [
        {"action": "finish", "text": "Finish"},
        [],  # remaining cards: empty, meaning 9001 was applied
    ]

    with patch("job_agent_client.find_drawer", side_effect=[mock_drawer, None]), \
         patch("job_agent_client.handle_naukri_chatbot_drawer", return_value=True) as mock_handle_drawer, \
         patch("job_agent_client.load_applied_job_ids", return_value=set()), \
         patch("job_agent_client.record_applied_job") as mock_record, \
         patch("time.sleep"):

        applied = handle_neo_interactive_flow(mock_driver, sample_config, eligible, max_wait_sec=10)
        assert applied == 1
        mock_handle_drawer.assert_called_once()
        mock_record.assert_called_once()
        assert mock_record.call_args.kwargs["job_id"] == "9001"
        assert mock_record.call_args.kwargs["company"] == "Capgemini"


def test_apply_to_eligible_agent_jobs_filters_title_bad_words_devops(mock_driver):
    custom_config = {
        "search": {
            "title_bad_words": ["DevOps", "Devops", "QA", "SRE"],
            "title_mandatory_words": ["Data Engineer", "PySpark"],
        },
    }
    agent_data = {
        "nodeType": "jobListing",
        "jobs": [
            {
                "jobId": "2001",
                "title": "Data Engineer",
                "companyName": "Alpha",
                "location": "Gurgaon",
            },
            {
                "jobId": "2002",
                "title": "AWS DevOps Engineer",
                "companyName": "Beta",
                "location": "Noida",
            },
            {
                "jobId": "2003",
                "title": "Platform Engineer (Data / DevOps)",
                "companyName": "Gamma",
                "location": "Gurgaon",
            },
        ],
    }
    with patch("job_agent_client.load_applied_job_ids", return_value=set()), \
         patch("job_agent_client.post_agent_action", return_value={"ok": True}), \
         patch("job_agent_client.record_applied_job") as mock_record, \
         patch("time.sleep"):
        count = apply_to_eligible_agent_jobs(mock_driver, custom_config, agent_data)
        assert count == 1
        assert mock_record.call_count == 1
        assert mock_record.call_args.kwargs["title"] == "Data Engineer"


def test_run_job_apply_agent_stage_skips_devops_cards(mock_driver):
    custom_config = {
        "search": {
            "title_bad_words": ["DevOps", "Devops", "SRE"],
            "title_mandatory_words": ["Data Engineer"],
        },
        "settings": {
            "daily_application_ceiling": 45,
        },
    }
    mock_cards = [
        {"jobId": "3001", "title": "Data Engineer", "company": "Alpha Corp", "location": "Noida", "jobUrl": "https://naukri.com/3001"},
        {"jobId": "3002", "title": "DevOps Engineer", "company": "Beta Corp", "location": "Gurgaon", "jobUrl": "https://naukri.com/3002"},
    ]
    with patch("job_agent_client.load_applied_job_ids", return_value=set()), \
         patch("job_agent_client.count_applied_in_last_24_hours", return_value=0), \
         patch("job_agent_client.handle_preferences_confirmation_dom", return_value=False), \
         patch("job_agent_client.handle_today_recommendations_pill_dom", return_value=False), \
         patch("job_agent_client.extract_agent_job_cards_dom", return_value=mock_cards), \
         patch("job_agent_client.sync_card_selection_dom", return_value={"selectedCount": 1}), \
         patch("job_agent_client.click_apply_action_pill_dom", return_value=(True, "Apply to selected ones")), \
         patch("job_agent_client.handle_neo_interactive_flow", return_value=1) as mock_handle_flow, \
         patch("time.sleep"):
        applied = run_job_apply_agent_stage(mock_driver, custom_config, max_cycles=1)
        assert applied == 1
        # Check that only 3001 (Data Engineer) was passed as eligible to handle_neo_interactive_flow
        eligible_arg = mock_handle_flow.call_args[0][2]
        assert len(eligible_arg) == 1
        assert eligible_arg[0]["jobId"] == "3001"
        assert eligible_arg[0]["title"] == "Data Engineer"



