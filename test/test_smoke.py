import pytest

@pytest.mark.asyncio
async def test_docs_and_root(client):
    root = await client.get("/")
    assert root.status_code == 200

    docs = await client.get("/docs")
    assert docs.status_code == 200
