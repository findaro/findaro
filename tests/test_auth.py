import httpx

from zerch.auth import _key_cache
from zerch.main import create_app

from .conftest import make_settings, new_project


async def test_missing_and_invalid_keys(client, project):
    r = await client.post("/v1/search", json={"query": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    r = await client.post("/v1/search", json={"query": "x"}, headers={"authorization": "Bearer zk_search_nope"})
    assert r.status_code == 401


async def test_search_key_is_search_only(client, project):
    r = await client.post(f"/v1/projects/{project.id}/documents", json=[{"id": 1}], headers=project.searcher)
    assert r.status_code == 403
    r = await client.get(f"/v1/projects/{project.id}/schema", headers=project.searcher)
    assert r.status_code == 403
    r = await client.post("/v1/search", json={"query": "x"}, headers=project.searcher)
    assert r.status_code == 200


async def test_alternate_key_header(client, project):
    r = await client.post("/v1/search", json={"query": "x"}, headers={"x-zerch-key": project.search_key})
    assert r.status_code == 200


async def test_admin_key_scoped_to_its_project(client, state, project):
    other = await new_project(client, state, "other")
    r = await client.get(f"/v1/projects/{other.id}", headers=project.admin)
    assert r.status_code == 404
    r = await client.post(f"/v1/projects/{other.id}/documents", json=[{"id": 1}], headers=project.admin)
    assert r.status_code == 404
    r = await client.get(f"/v1/projects/{project.id}", headers=project.admin)
    assert r.status_code == 200


async def test_admin_key_can_search(client, project):
    r = await client.post("/v1/search", json={"query": "x"}, headers=project.admin)
    assert r.status_code == 200


async def test_keys_are_not_stored_in_plaintext(state, project):
    async with state.db.connect() as conn:
        rows = (await conn.exec_driver_sql("SELECT key_hash, key_prefix FROM api_keys")).all()
    assert all(project.admin_key not in (h, p) and project.search_key not in (h, p) for h, p in rows)


async def test_bootstrap_token(state):
    app = create_app(make_settings(bootstrap_token="s3cret"), state.embedder)
    st = await _state_with(state, bootstrap_token="s3cret")
    app.state.zerch = st
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/v1/projects", json={})).status_code == 401
        assert (await c.post("/v1/projects", json={}, headers={"authorization": "Bearer wrong"})).status_code == 401
        assert (await c.post("/v1/projects", json={}, headers={"authorization": "Bearer s3cret"})).status_code == 201


async def test_rate_limit(state, project):
    st = await _state_with(state, rate_limit_per_second=3)
    app = create_app(st.settings, state.embedder)
    app.state.zerch = st
    _key_cache.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.post("/v1/search", json={"query": "x"}, headers=project.searcher)).status_code
                 for _ in range(8)]
    assert 429 in codes and codes[0] == 200
    r429 = codes.index(429)
    assert all(c == 200 for c in codes[:r429])


async def _state_with(state, **over):
    """Same connections, different settings."""
    from dataclasses import replace

    return replace(state, settings=make_settings(**over))
