from importlib.util import find_spec

from apps.fiscal import tasks


def test_national_transport_and_services_are_removed():
    for module in ["sefaz", "distribution", "sync", "execution", "recovery"]:
        assert find_spec(f"apps.fiscal.services.{module}") is None


def test_only_atf_download_tasks_remain():
    for name in [
        "process_sync_request",
        "reprocess_distribution_batch_task",
        "schedule_eligible_synchronizations",
    ]:
        assert not hasattr(tasks, name)
