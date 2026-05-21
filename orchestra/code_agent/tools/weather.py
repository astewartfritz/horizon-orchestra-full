from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


async def _geocode(location: str) -> tuple[float, float, str] | None:
    """Return (lat, lon, display_name) for a city name, or None."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )
        data = r.json().get("results", [])
        if not data:
            return None
        hit = data[0]
        name = f"{hit.get('name', location)}, {hit.get('country', '')}"
        return hit["latitude"], hit["longitude"], name.strip(", ")


_WMO: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 80: "Rain showers",
    81: "Moderate showers", 82: "Violent showers", 95: "Thunderstorm",
    96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}


class WeatherTool(Tool):
    spec = ToolSpec(
        name="weather",
        description=(
            "Get current weather and a 3-day forecast for any city. "
            "Uses the free Open-Meteo API — no API key required."
        ),
        parameters={
            "location": {
                "type": "string",
                "description": "City name, e.g. 'London', 'New York', 'Tokyo'",
            },
            "units": {
                "type": "string",
                "description": "Temperature units: 'celsius' (default) or 'fahrenheit'",
                "default": "celsius",
            },
        },
    )

    async def __call__(self, location: str, units: str = "celsius") -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed. Run: pip install httpx")
        try:
            geo = await _geocode(location)
            if geo is None:
                return ToolResult(error=f"Location not found: {location!r}")
            lat, lon, display = geo
            temp_unit = "fahrenheit" if units.lower().startswith("f") else "celsius"
            wind_unit = "mph" if temp_unit == "fahrenheit" else "kmh"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": True,
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                        "temperature_unit": temp_unit,
                        "windspeed_unit": wind_unit,
                        "timezone": "auto",
                        "forecast_days": 4,
                    },
                )
                d = r.json()
            cur = d.get("current_weather", {})
            u = "°F" if temp_unit == "fahrenheit" else "°C"
            wu = "mph" if wind_unit == "mph" else "km/h"
            code = cur.get("weathercode", 0)
            lines = [
                f"Weather for {display}",
                f"  Now: {cur.get('temperature', '?')}{u}, {_WMO.get(code, 'Unknown')}",
                f"  Wind: {cur.get('windspeed', '?')} {wu}",
                "",
                "3-Day Forecast:",
            ]
            daily = d.get("daily", {})
            dates = daily.get("time", [])
            maxes = daily.get("temperature_2m_max", [])
            mins = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])
            codes = daily.get("weathercode", [])
            for i in range(1, min(4, len(dates))):
                desc = _WMO.get(codes[i] if i < len(codes) else 0, "")
                rain = f", rain {precip[i]:.1f}mm" if i < len(precip) and precip[i] else ""
                lines.append(
                    f"  {dates[i]}: {mins[i] if i < len(mins) else '?'}{u}–{maxes[i] if i < len(maxes) else '?'}{u}, {desc}{rain}"
                )
            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"Weather fetch failed: {e}")
