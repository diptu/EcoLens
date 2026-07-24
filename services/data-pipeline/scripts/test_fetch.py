import pytest
import respx
import httpx
from ecolens.ingestion.sources.openelectricity import OpenElectricityFetcher
from ecolens.config import get_settings

# Fixed value per real API metric name (as sent in the `metrics` query
# param — see METRIC_API_NAME for the internal-name -> real-name map).
METRIC_VALUES = {
    "power": 100.0,
    "price": 85.0,
    "demand": 25000.0,
    "emissions": 1200.0,
    "curtailment_solar_utility": 0.0,
    "curtailment_wind": 0.0,
    "renewable_proportion": 25.0,
    "flow_imports": 500.0,
    "flow_exports": 500.0,
    "market_value": 2000.0,
}


def _mock_oe_response(request: httpx.Request) -> httpx.Response:
    metric = httpx.QueryParams(request.url.query).get("metrics")
    value = METRIC_VALUES.get(metric, 0.0)
    columns = {"fueltech": "wind"} if metric == "power" else {}
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "network_code": "NEM",
                    "metric": metric,
                    "results": [
                        {
                            "name": f"{metric}_total",
                            "columns": columns,
                            "data": [["2026-07-20T10:00:00+10:00", value]],
                        }
                    ],
                }
            ]
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_success():
    respx.get(
        url__regex=r"https://api\.openelectricity\.org\.au/v4/(data|market)/network/.*"
    ).mock(side_effect=_mock_oe_response)

    fetcher = OpenElectricityFetcher(api_key=get_settings().oe_api_key, use_sdk=False)
    async with httpx.AsyncClient() as client:
        results = await fetcher.fetch(client)

    assert len(results) > 0
    assert results[0]["wind_mw"] == 100.0
    assert results[0]["price_mwh"] == 85.0
    assert results[0]["demand_mw"] == 25000.0
    assert results[0]["source"] == "openelectricity"
    assert results[0]["schema_version"] == "1.0"
