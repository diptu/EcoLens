from __future__ import annotations


def test_lists_all_6_regions(client):
    response = client.get("/v1/regions")

    assert response.status_code == 200
    body = response.json()
    ids = {r["id"] for r in body["data"]}
    assert ids == {"NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"}
    wem = next(r for r in body["data"] if r["id"] == "WEM")
    assert wem["network"] == "WEM"
    nsw = next(r for r in body["data"] if r["id"] == "NSW1")
    assert nsw["network"] == "NEM"
