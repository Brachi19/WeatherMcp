import ssl

import httpx
import truststore
from mcp.server.mcpserver import MCPServer  # ב-v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("weather")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 15
MAX_FORECAST_DAYS = 16  # המגבלה של Open-Meteo

ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class WeatherError(Exception):
    """שגיאה עם הודעה קריאה שמוחזרת למשתמש."""


async def fetch_weather(city: str, extra_params: dict) -> tuple[dict, dict]:
    """ממיר עיר לקואורדינטות ושולף נתונים. מחזיר (place, data)."""
    city = city.strip()
    if not city:
        raise WeatherError("city name is empty.")

    try:
        async with httpx.AsyncClient(verify=ssl_context) as client:
            r = await client.get(
                GEOCODING_URL,
                params={"name": city, "count": 1, "language": "en", "format": "json"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            results = r.json().get("results")  # המפתח חסר כשאין תוצאות
            if not results:
                raise WeatherError(f"city '{city}' was not found.")
            place = results[0]

            r = await client.get(
                FORECAST_URL,
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "timezone": "auto",
                    **extra_params,
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return place, r.json()
    except httpx.TimeoutException:
        raise WeatherError("the weather service did not respond in time.")
    except httpx.HTTPError as e:
        raise WeatherError(f"failed to reach the weather service ({e}).")


def format_location(place: dict) -> str:
    return f"{place['name']}, {place.get('country', '')}".strip(", ")


@mcp.tool()
async def get_current_weather(city: str) -> str:
    """מחזיר מזג אוויר נוכחי לפי שם עיר (עדיף באנגלית, למשל "Tel Aviv")."""
    try:
        place, data = await fetch_weather(
            city, {"current": "temperature_2m,relative_humidity_2m,wind_speed_10m"}
        )
    except WeatherError as e:
        return f"Error: {e}"

    current = data.get("current")
    units = data.get("current_units", {})
    if not current:
        return "Error: the weather service returned no data."

    return (
        f"Current weather in {format_location(place)}:\n"
        f"Temperature: {current['temperature_2m']}{units.get('temperature_2m', '')}\n"
        f"Humidity: {current['relative_humidity_2m']}{units.get('relative_humidity_2m', '')}\n"
        f"Wind speed: {current['wind_speed_10m']}{units.get('wind_speed_10m', '')}"
    )


@mcp.tool()
async def get_forecast(city: str, days: int = 3) -> str:
    """מחזיר תחזית יומית לפי שם עיר (עדיף באנגלית). days = מספר ימים, בין 1 ל-16."""
    if not 1 <= days <= MAX_FORECAST_DAYS:
        return f"Error: days must be between 1 and {MAX_FORECAST_DAYS}."

    try:
        place, data = await fetch_weather(
            city,
            {
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "forecast_days": days,
            },
        )
    except WeatherError as e:
        return f"Error: {e}"

    daily = data.get("daily")
    units = data.get("daily_units", {})
    if not daily or not daily.get("time"):
        return "Error: the weather service returned no forecast data."

    t_unit = units.get("temperature_2m_max", "")
    p_unit = units.get("precipitation_sum", "")
    lines = [f"{days}-day forecast for {format_location(place)}:"]
    for i, date in enumerate(daily["time"]):
        lines.append(
            f"{date}: {daily['temperature_2m_min'][i]}{t_unit} to "
            f"{daily['temperature_2m_max'][i]}{t_unit}, "
            f"precipitation {daily['precipitation_sum'][i]}{p_unit}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")