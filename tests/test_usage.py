import httpx

from zerch import usage
from zerch.main import create_app

from .conftest import make_settings, new_project
from .test_auth import _state_with

TOKEN = "op-s3cret"


async def _operator_client(state):
    st = await _state_with(state, bootstrap_token=TOKEN)
    app = create_app(st.settings, state.embedder)
    app.state.zerch = st
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t"), st


def _op(token=TOKEN):
    return {"authorization": f"Bearer {token}"}


async def test_usage_is_metered_and_flushed(client, state):
    p = await new_project(client, state, "metered")
    for _ in range(3):
        await p.search(query="x")
    await p.search(query="x", llm=False)  # search-as-you-type: metered, not counted toward the quota
    r = await client.get(f"/v1/projects/{p.id}/usage", headers=p.admin)
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["usage"] == {"search": 3, "typeahead": 1, "chat": 0}
    assert u["quota_used"] == 3 and u["quota"] is None and not u["over_limit"]

    assert await usage.flush(state) >= 2
    await p.search(query="x")
    u = (await client.get(f"/v1/projects/{p.id}/usage", headers=p.admin)).json()
    assert u["usage"] == {"search": 4, "typeahead": 1, "chat": 0}  # flushed rows + pending counter
    assert (await client.get(f"/v1/projects/{p.id}/usage", headers=p.searcher)).status_code == 403


async def test_operator_endpoints_need_the_token(client, state, project):
    # without a configured bootstrap token the operator API is off
    assert (await client.get("/v1/operator/usage")).status_code == 404
    c, _ = await _operator_client(state)
    async with c:
        assert (await c.get("/v1/operator/usage")).status_code == 401
        assert (await c.get("/v1/operator/usage", headers=_op("nope"))).status_code == 401
        # a project's own admin key can't change its limits
        r = await c.put(f"/v1/operator/projects/{project.id}/limits", json={"documents": 1}, headers=project.admin)
        assert r.status_code == 401
        r = await c.put("/v1/operator/projects/prj_missing/limits", json={}, headers=_op())
        assert r.status_code == 404
        r = await c.get("/v1/operator/usage", headers=_op())
        assert r.status_code == 200 and any(x["project_id"] == project.id for x in r.json()["projects"])


async def test_quota_blocks_only_when_asked(client, state):
    c, _ = await _operator_client(state)
    async with c:
        p = await new_project(client, state, "quota")
        h = p.searcher
        r = await c.put(f"/v1/operator/projects/{p.id}/limits",
                        json={"plan": "free", "searches_per_month": 2}, headers=_op())
        assert r.status_code == 200 and r.json()["limits"] == {"plan": "free", "searches_per_month": 2, "llm": True}
        usage._flushed_cache.clear()
        codes = [(await c.post("/v1/search", json={"query": "x"}, headers=h)).status_code for _ in range(4)]
        assert codes == [200] * 4  # soft limit: reported, never blocked
        u = (await c.get(f"/v1/projects/{p.id}/usage", headers=p.admin)).json()
        assert u["over_limit"] and u["quota_percent"] == 200.0

        await c.put(f"/v1/operator/projects/{p.id}/limits",
                    json={"searches_per_month": 5, "block_at_percent": 100}, headers=_op())
        from zerch.auth import forget_project

        forget_project(p.id)
        r = await c.post("/v1/search", json={"query": "x"}, headers=h)
        assert r.status_code == 200  # 4 used, 5th allowed
        r = await c.post("/v1/search", json={"query": "x"}, headers=h)
        assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
        # typeahead requests are not part of the quota, so they keep working
        r = await c.post("/v1/search", json={"query": "x", "llm": False}, headers=h)
        assert r.status_code == 200


async def test_document_limit(client, state):
    c, _ = await _operator_client(state)
    async with c:
        p = await new_project(client, state, "docs")
        await c.put(f"/v1/operator/projects/{p.id}/limits", json={"documents": 2}, headers=_op())
        from zerch.auth import forget_project

        forget_project(p.id)
        job = await p.ingest([{"id": "a", "title": "one"}, {"id": "b", "title": "two"}])
        assert job["status"] == "succeeded"
        r = await c.post(f"/v1/projects/{p.id}/documents", json=[{"id": "c", "title": "three"}], headers=p.admin)
        assert r.status_code == 403 and r.json()["error"]["code"] == "document_limit_reached"
        info = (await c.get(f"/v1/projects/{p.id}", headers=p.admin)).json()
        assert info["limits"] == {"documents": 2, "llm": True}


async def test_llm_off_for_project(client, state, loaded):
    class Boom:
        async def complete(self, *a, **k):
            raise AssertionError("LLM must not be called for a project with llm: false")

    from dataclasses import replace

    st = replace(state, settings=make_settings(), planner=Boom(), chat_llm=Boom())
    project = {"limits": {"llm": False}, "schema_version": 1}
    assert not usage.llm_allowed(project) and usage.llm_allowed({"limits": {}}) and usage.llm_allowed(None)
    from zerch import store
    from zerch.understand.service import understand

    row = await store.get_project(st.db, loaded.id)
    row["limits"] = {"llm": False}
    plan, info = await understand(st, loaded.id, row, store.load_schema(row["schema"]), "zxqv plorb shoes")
    assert info["llm"] in ("skipped", "not_needed")
