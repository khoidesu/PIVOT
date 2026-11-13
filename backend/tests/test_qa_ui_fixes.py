"""Hồi quy cho QA_FINAL_REPORT lượt 3 (13/11): QA-06 (ICD chỉ thấy slot của mình), QA-10 (tên tổ chức trên lô),
QA-11 (/v1/meta cho biết bộ trích xuất đang chạy, không lộ khoá)."""
from app.config import settings
from tests.conftest import auth
from tests.helpers import match
from tests.test_login import as_, login


def _slots(client, headers):
    r = client.get("/v1/slots", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_node_operator_sees_only_its_own_slots(client):
    tok, me_o = as_(client, "Cường QA", "node_operator")      # ICD thứ hai tự đăng ký → có slot mẫu riêng
    other_h = auth(tok)
    me_c = client.get("/v1/me", headers=auth("node_c")).json()

    mine = _slots(client, auth("node_c"))
    theirs = _slots(client, other_h)
    assert mine and theirs
    assert {x["node_org_id"] for x in mine} == {me_c["org_id"]}
    assert {x["node_org_id"] for x in theirs} == {me_o["org_id"]}
    assert not {x["id"] for x in mine} & {x["id"] for x in theirs}


def test_other_roles_still_see_every_icd_with_its_name(client):
    login(client, "Cường QA", "node_operator")
    for role in ("shipper_a", "carrier_b", "dispatch"):
        rows = _slots(client, auth(role))
        assert len({x["node_org_id"] for x in rows}) >= 2
        assert all(x["node_org_name"] for x in rows)


def test_matching_still_uses_slots_of_every_icd(client):
    """Bộ ghép đọc slot trong DB, không qua GET /v1/slots — việc lọc theo vai không đổi kết quả ghép."""
    login(client, "Cường QA", "node_operator")
    body = match(client, "shipper_a", "LOT-A-001")
    assert body["proposals"], body
    assert all(p["slot"]["node_org_name"] for p in body["proposals"])


def test_shipments_carry_owner_org_name(client):
    ta, me_a = as_(client, "Hoa QA", "shipper")
    as_(client, "Lan QA", "shipper")
    rows = client.get("/v1/shipments", headers=auth("dispatch")).json()
    by_tenant = {}
    for x in rows:
        assert x["tenant_name"], x
        by_tenant.setdefault(x["tenant_id"], x["tenant_name"])
    assert len(set(by_tenant.values())) >= 3          # seed + 2 chủ hàng mới → các tên khác nhau
    own = client.get("/v1/shipments", headers=auth(ta)).json()
    assert own and {x["tenant_id"] for x in own} == {me_a["org_id"]}       # chủ hàng vẫn chỉ thấy lô của mình
    assert {x["tenant_name"] for x in own} == {me_a["org_name"]}


def test_meta_reports_extractor_kind_without_key(client, monkeypatch):
    meta = client.get("/v1/meta", headers=auth("shipper_a")).json()
    assert meta["extractor_kind"] == "rule"
    monkeypatch.setattr(settings, "intake_extractor", "hybrid")
    assert client.get("/v1/meta", headers=auth("shipper_a")).json()["extractor_kind"] == "rule"   # hybrid mà không có khoá → luật
    monkeypatch.setattr(settings, "gemini_api_key", "secret-test-key-123")
    r = client.get("/v1/meta", headers=auth("shipper_a"))
    assert r.json()["extractor_kind"] == "hybrid"
    assert "secret-test-key-123" not in r.text


def test_proposal_list_is_lean_but_detail_keeps_rejections(client):
    """Bản công khai (14/11): danh sách đề xuất kèm toàn bộ xe bị loại của từng đề xuất ≈ 458 KB → máy chủ Render nghẽn khi polling.
    Danh sách và đề xuất trong kết quả ghép bỏ `rejections`/`gates` của từng đề xuất; màn chi tiết vẫn đủ (và vẫn che dữ liệu)."""
    run = match(client, "shipper_a", "LOT-A-001")
    assert run["rejections"]                                         # kết quả ghép vẫn có danh sách xe bị loại ở cấp trên
    assert all(p["rejections"] == [] and p["gates"] for p in run["proposals"])   # thẻ đề xuất vẫn có điều kiện để giải thích
    lst = client.get("/v1/proposals", headers=auth("shipper_a")).json()
    assert lst and all(p["rejections"] == [] and p["gates"] == [] for p in lst)
    assert all(p["parties"] and "my_actions" in p for p in lst)      # đủ cho màn Xác nhận/Theo dõi/Luồng demo
    detail = client.get(f"/v1/proposals/{run['proposals'][0]['id']}", headers=auth("shipper_a")).json()
    assert detail["rejections"] and detail["gates"]
