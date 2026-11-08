"""בדיקות ל-server.py. הקריאות לרשת מוחלפות ב-respx, כך שהבדיקות לא תלויות באינטרנט."""
import asyncio

import httpx
import pytest
import respx

import server

GEO_URL = server.GEOCODING_URL
FORECAST_URL = server.FORECAST_URL

TEL_AVIV = {
    "results": [
        {"name": "Tel Aviv", "country": "Israel", "latitude": 32.08, "longitude": 34.78}
    ]
}

CURRENT = {
    "current": {"temperature_2m": 18.5, "relative_humidity_2m": 60, "wind_speed_10m": 7.2},
    "current_units": {"temperature_2m": "°C", "relative_humidity_2m": "%", "wind_speed_10m": "km/h"},
}

DAILY = {
    "daily": {
        "time": ["2026-11-09", "2026-11-10"],
        "temperature_2m_max": [22.0, 21.0],
        "temperature_2m_min": [16.0, 14.0],
        "precipitation_sum": [1.2, 0.0],
    },
    "daily_units": {"temperature_2m_max": "°C", "precipitation_sum": "mm"},
}


def run(coro):
    return asyncio.run(coro)


# ---------- format_location ----------

def test_format_location_with_country():
    assert server.format_location({"name": "Haifa", "country": "Israel"}) == "Haifa, Israel"


def test_format_location_without_country():
    assert server.format_location({"name": "Haifa"}) == "Haifa"


# ---------- fetch_weather ----------

def test_fetch_weather_empty_city():
    with pytest.raises(server.WeatherError, match="empty"):
        run(server.fetch_weather("   ", {}))


@respx.mock
def test_fetch_weather_city_not_found():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json={}))  # אין מפתח results
    with pytest.raises(server.WeatherError, match="not found"):
        run(server.fetch_weather("Xyzabc", {}))


@respx.mock
def test_fetch_weather_success():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json=TEL_AVIV))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=CURRENT))
    place, data = run(server.fetch_weather("Tel Aviv", {"current": "temperature_2m"}))
    assert place["name"] == "Tel Aviv"
    assert data["current"]["temperature_2m"] == 18.5


@respx.mock
def test_fetch_weather_timeout():
    respx.get(GEO_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
    with pytest.raises(server.WeatherError, match="in time"):
        run(server.fetch_weather("Tel Aviv", {}))


@respx.mock
def test_fetch_weather_http_error():
    respx.get(GEO_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(server.WeatherError, match="failed to reach"):
        run(server.fetch_weather("Tel Aviv", {}))


# ---------- get_current_weather ----------

@respx.mock
def test_get_current_weather_output():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json=TEL_AVIV))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=CURRENT))
    result = run(server.get_current_weather("Tel Aviv"))
    assert "Tel Aviv, Israel" in result
    assert "18.5°C" in result
    assert "60%" in result
    assert "7.2km/h" in result


@respx.mock
def test_get_current_weather_unknown_city_returns_error_text():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json={}))
    result = run(server.get_current_weather("Xyzabc"))
    assert result.startswith("Error:")
    assert "Xyzabc" in result


# ---------- get_forecast ----------

@pytest.mark.parametrize("days", [0, -1, 17])
def test_get_forecast_invalid_days(days):
    # אין mock לרשת: אם הכלי היה פונה לרשת, הבדיקה הייתה נכשלת
    result = run(server.get_forecast("Tel Aviv", days))
    assert result.startswith("Error:")
    assert "between 1 and 16" in result


@respx.mock
def test_get_forecast_output():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json=TEL_AVIV))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=DAILY))
    result = run(server.get_forecast("Tel Aviv", 2))
    lines = result.splitlines()
    assert len(lines) == 3  # כותרת + יומיים
    assert "2026-11-09" in lines[1]
    assert "16.0°C to 22.0°C" in lines[1]
    assert "precipitation 1.2mm" in lines[1]


@respx.mock
def test_get_forecast_no_data():
    respx.get(GEO_URL).mock(return_value=httpx.Response(200, json=TEL_AVIV))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json={}))
    result = run(server.get_forecast("Tel Aviv", 3))
    assert result.startswith("Error:")