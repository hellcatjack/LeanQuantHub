from app.services import ib_settings


def test_derive_client_id_paper():
    assert ib_settings.derive_client_id(project_id=16, mode="paper") == 1016


def test_derive_client_id_live_offset():
    assert ib_settings.derive_client_id(project_id=16, mode="live") == 6016
