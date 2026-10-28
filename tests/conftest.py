import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """De integratie hangt van de recorder af; recorder_mock moet vóór `hass` worden aangemaakt."""
    yield
