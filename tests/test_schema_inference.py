import pytest

from findaro.index.normalize import category_paths, normalize
from findaro.schema import Role, Schema, SchemaError, infer_fields, infer_schema
from findaro.schema.infer import parse_bool, parse_number
from findaro.schema.model import FieldSpec

from .conftest import make_catalog


def roles(schema: Schema) -> dict[str, Role]:
    return {f.name: f.role for f in schema.fields}


def test_infers_catalog_roles():
    s = infer_schema(make_catalog())
    r = roles(s)
    assert r["id"] == Role.id
    assert r["title"] == Role.title
    assert r["description"] == Role.description
    assert r["brand"] == Role.facet
    assert r["color"] == Role.facet
    assert r["category"] == Role.category
    assert s.get("category").separator == " > "
    assert r["price"] == Role.price
    assert r["currency"] == Role.currency
    assert r["rating"] == Role.numeric
    assert r["in_stock"] == Role.boolean
    assert r["image_url"] == Role.image_url
    assert r["url"] == Role.url
    assert r["tags"] == Role.facet and s.get("tags").multi


def test_infers_from_csv_strings():
    """CSV gives strings only: numbers, booleans and ';'-lists must still be recognised."""
    docs = [
        {"sku": f"S{i}", "name": f"Widget model {i} deluxe edition", "selling_price": f"₹{100 + i * 7:,}",
         "available": "yes" if i % 2 else "no", "sizes": "S;M;L" if i % 3 else "M;XL", "qty": str(i % 9),
         "breadcrumb": "Tools / Hand Tools / Spanners"}
        for i in range(40)
    ]
    r = roles(infer_schema(docs))
    assert r["sku"] == Role.id
    assert r["name"] == Role.title
    assert r["selling_price"] == Role.price
    assert r["available"] == Role.boolean
    assert r["sizes"] == Role.facet
    assert r["qty"] == Role.numeric
    assert r["breadcrumb"] == Role.category
    s = infer_schema(docs)
    assert s.get("sizes").separator == ";" and s.get("sizes").multi
    assert s.get("breadcrumb").separator == " / "


def test_unit_values_are_facets_not_numbers():
    docs = [{"id": i, "title": f"Thing number {i}", "capacity": ["1 L", "500 ml", "2 L"][i % 3]} for i in range(30)]
    assert roles(infer_schema(docs))["capacity"] == Role.facet


def test_nested_objects_are_flattened():
    docs = [{"id": i, "title": f"Item {i} of the list", "attrs": {"color": ["red", "blue"][i % 2]}} for i in range(30)]
    s = infer_schema(docs)
    assert roles(s)["attrs.color"] == Role.facet
    _, body, _ = normalize(docs[0], s)
    assert body["f"][s.get("attrs.color").key] == "red"


def test_id_required():
    with pytest.raises(SchemaError):
        infer_schema([{"title": "a"}, {"title": "a"}])


def test_title_fallback_without_name_hints():
    docs = [{"pid": f"x{i}", "headline_text": f"Unique product headline number {i}", "kind": ["a", "b"][i % 2]}
            for i in range(30)]
    r = roles(infer_schema(docs))
    assert r["pid"] == Role.id
    assert r["headline_text"] == Role.title


def test_infer_new_fields():
    specs = infer_fields([{"id": 1, "warranty_months": 12}, {"id": 2, "warranty_months": 24}], {"warranty_months"})
    assert [(f.name, f.role) for f in specs] == [("warranty_months", Role.numeric)]


def test_schema_validation():
    with pytest.raises(SchemaError):
        Schema.build([FieldSpec(name="a", role=Role.title)])
    with pytest.raises(SchemaError, match="exactly one"):
        Schema.build([FieldSpec(name="a", role=Role.id), FieldSpec(name="b", role=Role.id)])


def test_role_defaults():
    f = FieldSpec(name="t", role=Role.title)
    assert f.searchable and not f.filterable and not f.facet
    f = FieldSpec(name="u", role=Role.url, searchable=True)
    assert not f.searchable  # non-indexed roles cannot be searchable


def test_parsers():
    assert parse_number("Rs. 1,299") == 1299
    assert parse_number("1,00,000") == 100000
    assert parse_number("-2.5") == -2.5
    assert parse_number("5 L") is None
    assert parse_number(True) is None
    assert parse_bool("Yes") is True and parse_bool("0") is False and parse_bool("maybe") is None


def test_category_paths():
    full, prefixes = category_paths("A > B > C", " > ")
    assert full == ["A > B > C"]
    assert prefixes == ["A", "A > B", "A > B > C"]
    full, prefixes = category_paths(["X / Y", "X / Z"], " / ")
    assert full == ["X > Y", "X > Z"] and prefixes == ["X", "X > Y", "X > Z"]
