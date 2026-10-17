import json

from .conftest import make_catalog, new_project


async def doc_count(p) -> int:
    r = await p.client.get(f"/v1/projects/{p.id}", headers=p.admin)
    return r.json()["document_count"]


async def test_upsert_infers_schema_and_indexes(project, catalog):
    job = await project.ingest(catalog)
    assert job["status"] == "succeeded"
    assert job["total"] == job["processed"] == job["succeeded"] == len(catalog)
    assert await doc_count(project) == len(catalog)
    r = await project.client.get(f"/v1/projects/{project.id}/schema", headers=project.admin)
    fields = {f["name"]: f["role"] for f in r.json()["schema"]["fields"]}
    assert fields["id"] == "id" and fields["category"] == "category" and fields["price"] == "price"


async def test_upsert_replaces_by_id(project, catalog):
    await project.ingest(catalog[:10])
    changed = dict(catalog[0], title="Totally Renamed Gizmo")
    job = await project.ingest([changed])
    assert job["status"] == "succeeded"
    assert await doc_count(project) == 10
    r = await project.client.get(f"/v1/projects/{project.id}/documents/{changed['id']}", headers=project.admin)
    assert r.json()["document"]["title"] == "Totally Renamed Gizmo"


async def test_wrapped_documents_body(project, catalog):
    r = await project.client.post(f"/v1/projects/{project.id}/documents", json={"documents": catalog[:5]},
                                  headers=project.admin)
    assert r.status_code == 202
    assert (await project.finish(r.json()["job_id"]))["succeeded"] == 5


async def test_rejects_bad_bodies(project):
    url = f"/v1/projects/{project.id}/documents"
    assert (await project.client.post(url, content=b"{nope", headers=project.admin)).status_code == 400
    assert (await project.client.post(url, json=[], headers=project.admin)).status_code == 400
    assert (await project.client.post(url, json={"a": 1}, headers=project.admin)).status_code == 400


async def test_rows_without_id_are_reported(project, catalog):
    await project.ingest(catalog[:20])
    job = await project.ingest([{"title": "no id here"}, catalog[20]])
    assert job["status"] == "completed_with_errors"
    assert job["succeeded"] == 1 and job["failed"] == 1
    assert "missing id" in job["errors"][0]["error"]


async def test_first_ingest_without_id_fails_cleanly(project):
    job = await project.ingest([{"title": "x"}, {"title": "x"}])
    assert job["status"] == "failed"
    assert "id field" in job["message"]


async def test_import_jsonl(project, catalog):
    data = "\n".join(json.dumps(d) for d in catalog).encode() + b"\n\n{broken\n"
    r = await project.client.post(f"/v1/projects/{project.id}/import", headers=project.admin,
                                  files={"file": ("catalog.jsonl", data, "application/octet-stream")})
    assert r.status_code == 202, r.text
    job = await project.finish(r.json()["job_id"])
    assert job["succeeded"] == len(catalog)
    assert job["failed"] == 1 and job["errors"][0]["row"] == len(catalog) + 2


async def test_import_csv(client, state):
    p = await new_project(client, state, "csv")
    rows = ["sku,name,price,colour,sizes,in_stock,category"]
    for i in range(30):
        rows.append(f'S{i},"Classic Tee, edition {i}",{199 + i},{["Red", "Blue", "Black"][i % 3]},'
                    f'S;M;L,{"true" if i % 2 else "false"},Apparel > Tops')
    r = await client.post(f"/v1/projects/{p.id}/import", headers=p.admin,
                          files={"file": ("tees.csv", "\n".join(rows).encode(), "text/csv")})
    job = await p.finish(r.json()["job_id"])
    assert job["status"] == "succeeded", job
    schema = (await client.get(f"/v1/projects/{p.id}/schema", headers=p.admin)).json()["schema"]
    roles = {f["name"]: f["role"] for f in schema["fields"]}
    assert roles == {"sku": "id", "name": "title", "price": "price", "colour": "facet", "sizes": "facet",
                     "in_stock": "boolean", "category": "category"}
    res = await p.search(query="tee", filters={"sizes": "M", "price": {"lte": 205}, "in_stock": True})
    assert res["total"] == 3  # 199..205 -> S0..S6, odd ones in stock: S1, S3, S5


async def test_import_rejects_unknown_format(project):
    r = await project.client.post(f"/v1/projects/{project.id}/import", headers=project.admin,
                                  files={"file": ("data.xlsx", b"abc", "application/vnd.ms-excel")})
    assert r.status_code == 400


async def test_delete_documents(project, catalog):
    await project.ingest(catalog[:10])
    r = await project.client.delete(f"/v1/projects/{project.id}/documents/{catalog[0]['id']}", headers=project.admin)
    assert r.status_code == 202
    assert (await project.finish(r.json()["job_id"]))["status"] == "succeeded"
    r = await project.client.post(f"/v1/projects/{project.id}/documents/delete", headers=project.admin,
                                  json={"ids": [catalog[1]["id"], "does-not-exist"]})
    job = await project.finish(r.json()["job_id"])
    assert job["succeeded"] == 1 and job["errors"] == [{"id": "does-not-exist", "error": "not_found"}]
    assert await doc_count(project) == 8


async def test_new_fields_extend_schema(project, catalog):
    await project.ingest(catalog[:30])
    extra = [dict(d, warranty_years=1 + i % 3) for i, d in enumerate(catalog[30:60])]
    assert (await project.ingest(extra))["status"] == "succeeded"
    schema = (await project.client.get(f"/v1/projects/{project.id}/schema", headers=project.admin)).json()
    roles = {f["name"]: f["role"] for f in schema["schema"]["fields"]}
    assert roles["warranty_years"] == "numeric"
    res = await project.search(query="", filters={"warranty_years": {"gte": 3}})
    assert res["total"] == 10


async def test_put_schema_reindexes(project, catalog):
    await project.ingest(catalog)
    url = f"/v1/projects/{project.id}/schema"
    schema = (await project.client.get(url, headers=project.admin)).json()["schema"]
    for f in schema["fields"]:
        if f["name"] == "material":  # demote material from facet to plain keyword
            f.update(role="keyword", facet=None, filterable=None, searchable=None, sortable=None, weight=None)
    r = await project.client.put(url, json={"fields": schema["fields"]}, headers=project.admin)
    assert r.status_code == 202, r.text
    job = await project.finish(r.json()["job_id"])
    assert job["status"] == "succeeded" and job["succeeded"] == len(catalog)
    after = (await project.client.get(url, headers=project.admin)).json()
    assert after["pending_schema"] is None
    assert {f["name"]: f["role"] for f in after["schema"]["fields"]}["material"] == "keyword"
    res = await project.search(query="bottle")
    assert "material" not in res["facets"] and "color" in res["facets"]
    assert res["total"] > 0
    assert await doc_count(project) == len(catalog)


async def test_put_schema_validation(project):
    r = await project.client.put(f"/v1/projects/{project.id}/schema", headers=project.admin,
                                 json={"fields": [{"name": "a", "role": "title"}]})
    assert r.status_code == 400 and "id" in r.json()["error"]["message"]
    r = await project.client.put(f"/v1/projects/{project.id}/schema", headers=project.admin,
                                 json={"fields": [{"name": "a", "role": "bogus"}]})
    assert r.status_code == 400


async def test_put_schema_before_ingest(project, catalog):
    fields = [{"name": "id", "role": "id"}, {"name": "title", "role": "title"},
              {"name": "color", "role": "facet"}, {"name": "price", "role": "price"}]
    r = await project.client.put(f"/v1/projects/{project.id}/schema", json={"fields": fields}, headers=project.admin)
    assert (await project.finish(r.json()["job_id"]))["status"] == "succeeded"
    await project.ingest(catalog[:12])
    schema = (await project.client.get(f"/v1/projects/{project.id}/schema", headers=project.admin)).json()["schema"]
    assert schema["inferred"] is False
    res = await project.search(query="", filters={"color": "Black"})
    assert res["total"] == sum(1 for d in catalog[:12] if d["color"] == "Black")


async def test_job_status_not_found(project):
    r = await project.client.get(f"/v1/projects/{project.id}/jobs/job_missing", headers=project.admin)
    assert r.status_code == 404


async def test_delete_project(client, state):
    p = await new_project(client, state, "doomed")
    await p.ingest(make_catalog(12))
    r = await client.delete(f"/v1/projects/{p.id}", headers=p.admin)
    assert r.status_code == 204
    assert (await client.post("/v1/search", json={"query": "x"}, headers=p.searcher)).status_code == 401
    assert not await state.os.indices.exists(index=f"findarotest-{p.id}-v1")


async def test_job_retries_when_search_cluster_is_unreachable(client, state, monkeypatch):
    from opensearchpy import ConnectionError as OSConnectionError

    from findaro.ingest import processor

    p = await new_project(client, state, "retry")
    r = await client.post(f"/v1/projects/{p.id}/documents", json=[{"id": "a", "title": "one"}], headers=p.admin)
    jid = r.json()["job_id"]
    real, calls = processor.ingest_documents, []

    async def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSConnectionError("N/A", "connection refused", None)
        return await real(*a, **k)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(processor, "ingest_documents", flaky)
    monkeypatch.setattr(processor.asyncio, "sleep", no_sleep)
    job = await p.finish(jid)
    assert job["status"] == "succeeded" and len(calls) == 2
