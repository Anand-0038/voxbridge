from app import main


def test_rate_limit_pruning_removes_expired_clients_and_enforces_bound():
    now = 1_000.0
    original_max_clients = main.RATE_LIMIT_MAX_CLIENTS
    try:
        main.upload_requests.clear()
        main.RATE_LIMIT_MAX_CLIENTS = 2
        main.upload_requests["expired"] = [now - main.RATE_LIMIT_WINDOW - 1]
        main.upload_requests["active-a"] = [now - 1]
        main.upload_requests["active-b"] = [now - 1]
        main.upload_requests["active-c"] = [now - 1]

        main._prune_rate_limit_entries(now)

        assert "expired" not in main.upload_requests
        assert len(main.upload_requests) == 2
        assert list(main.upload_requests) == ["active-b", "active-c"]
    finally:
        main.RATE_LIMIT_MAX_CLIENTS = original_max_clients
        main.upload_requests.clear()
