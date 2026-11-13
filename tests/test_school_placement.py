"""Контрольные примеры практики 3: реальный метод BlocksNet на малой территории."""

import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

APP_DIR = Path(__file__).resolve().parents[1] / "school-placement"
sys.path.insert(0, str(APP_DIR))
from model import RESULT_COLUMNS, SchoolModel, rank_variants, read_matrix, validate_placements


@pytest.fixture
def example():
    blocks = gpd.GeoDataFrame(
        {"population": [1000, 1000, 1000, 0], "capacity": [0, 0, 0, 0]},
        geometry=[box(i * 10, 0, i * 10 + 5, 5) for i in range(4)], crs=32631,
    )
    matrix = pd.DataFrame([[0, 5, 30, 30], [5, 0, 30, 30], [30, 30, 0, 30], [30, 30, 30, 0]])
    model = SchoolModel(blocks, matrix, verify=False)
    return blocks, matrix, model


def test_baseline_and_spatial_effect(example):
    blocks, matrix, model = example
    before, times = blocks.copy(deep=True), matrix.copy(deep=True)
    pd.testing.assert_frame_equal(model.calculate([]), model.baseline)
    assert model.baseline.demand_left.sum() == 360
    result = model.calculate([{"block_id": 0, "capacity": 240}])
    assert result.capacity.sum() == 240
    assert result.loc[1, "demand_within"] == 120  # обслужен сосед, а не только квартал школы
    assert result.loc[2, "demand_left"] == 120  # вне 15 минут
    assert result.demand_left.sum() == 120
    pd.testing.assert_frame_equal(blocks, before)
    pd.testing.assert_frame_equal(matrix, times)
    assert model.payload(result)["rows"][3]["provision"] is None  # спроса нет, не 0%


def test_several_schools_and_reset(example):
    _, _, model = example
    result = model.calculate([{"block_id": 0, "capacity": 60}, {"block_id": 0, "capacity": 60},
                              {"block_id": 2, "capacity": 120}])
    assert result.loc[0, "capacity"] == 120
    assert result.capacity.sum() == 240
    assert model.payload(result)["summary"] == {"added": 240, "capacity": 240, "deficit": 120, "reduction": 240}
    assert model.calculate([]).capacity.sum() == 0


@pytest.mark.parametrize("capacity", [0, -1, 0.5, True, "600", None, float("nan")])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError, match="положительным целым"):
        validate_placements([{"block_id": 0, "capacity": capacity}], [0])


@pytest.mark.parametrize("block_id", [-1, 999, True, "0", None])
def test_invalid_block(block_id):
    with pytest.raises(ValueError, match="Неизвестный квартал"):
        validate_placements([{"block_id": block_id, "capacity": 600}], [0])


def test_exhaustive_independent_search_and_ties(example):
    _, _, model = example
    variants = list(model.search(240))
    assert [v["block_id"] for v in variants] == [0, 1, 2, 3]
    ranking = rank_variants(variants, 4)
    assert ranking["complete"] and ranking["best_ids"] == [0, 1]
    for v in variants:
        manual = model.calculate([{"block_id": v["block_id"], "capacity": 240}])
        assert v["deficit"] == int(manual.demand_left.sum())
    assert ranking["variants"][-1]["block_id"] == 3
    assert model.baseline.capacity.sum() == 0


def test_partial_search_explicit(example, monkeypatch):
    _, _, model = example
    original = model.calculate
    def fail_one(placements):
        if placements[0]["block_id"] == 1:
            raise RuntimeError("Проверочная ошибка")
        return original(placements)
    monkeypatch.setattr(model, "calculate", fail_one)
    ranking = rank_variants(list(model.search(240)), 4)
    assert not ranking["complete"]
    assert ranking["checked"] == 4 and ranking["successful"] == 3
    assert ranking["variants"][-1]["error"] == "Проверочная ошибка"
    assert not rank_variants([], 4)["complete"]


def test_matrix_id_alignment_and_validation(tmp_path):
    path = tmp_path / "matrix.csv"
    pd.DataFrame([[0, 4], [4, 0]], index=[1, 0], columns=[1, 0]).to_csv(path)
    assert read_matrix(path, pd.Index([0, 1])).index.tolist() == [0, 1]
    for bad in [pd.DataFrame([[0]], index=[9], columns=[9]),
                pd.DataFrame([[0, -1], [1, 0]]), pd.DataFrame([[0, np.nan], [1, 0]]),
                pd.DataFrame([[1, 1], [1, 0]]), pd.DataFrame([[0, 1], [1, 0]], columns=[0, 0])]:
        bad.to_csv(path)
        with pytest.raises(ValueError):
            read_matrix(path, pd.Index([0, 1]))


def test_baseline_checked_by_block_not_only_total(example):
    blocks, matrix, model = example
    expected = blocks.join(model.baseline[RESULT_COLUMNS].drop(columns="capacity"))
    SchoolModel(expected, matrix)
    expected.loc[0, "demand_left"] -= 1
    expected.loc[1, "demand_left"] += 1
    with pytest.raises(ValueError, match="НЕ воспроизведён"):
        SchoolModel(expected, matrix)


def test_http_calculate_search_and_missing_matrix(example, monkeypatch):
    import app
    blocks, _, model = example
    blocks = blocks.join(model.baseline[RESULT_COLUMNS].drop(columns="capacity"))
    monkeypatch.setattr(app, "read_blocks", lambda: blocks)
    monkeypatch.setattr(app, "load_model", lambda *args, **kwargs: model)
    server = app.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    def post(path, data):
        return urlopen(Request(base + path, json.dumps(data).encode(), {"Content-Type": "application/json"}), timeout=20)
    try:
        data = json.load(urlopen(base + "/api/data"))
        assert data["ready"] and len(data["geometry"]["features"]) == 4
        assert data["geometry_crs"] == "EPSG:4326"
        lon, lat = data["geometry"]["features"][0]["geometry"]["coordinates"][0][0]
        assert -180 <= lon <= 180 and -90 <= lat <= 90
        result = json.load(post("/api/calculate", {"placements": [{"block_id": 0, "capacity": 240}]}))
        assert sum(r["deficit"] for r in result["rows"]) == result["summary"]["deficit"]
        with pytest.raises(HTTPError) as exc:
            post("/api/calculate", {"placements": [{"block_id": 0, "capacity": 1.5}]})
        assert exc.value.code == 400
        events = [json.loads(line) for line in post("/api/search", {"capacity": 240})]
        assert [e["progress"] for e in events[:-1]] == [1, 2, 3, 4]
        assert events[-1]["done"]["best_ids"] == [0, 1]
        assert json.load(post("/api/calculate", {"placements": []})) == data["baseline"]
    finally:
        server.shutdown(); server.server_close(); thread.join()
    def missing(*args, **kwargs):
        raise FileNotFoundError("matrix")
    monkeypatch.setattr(app, "load_model", missing)
    server = app.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert not json.load(urlopen(base + "/api/data"))["ready"]
        with pytest.raises(HTTPError) as exc:
            post("/api/search", {"capacity": 600})
        assert exc.value.code == 409
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_committed_matrix_reproduces_every_saved_school_indicator():
    from model import MATRIX, ROOT, load_model, read_blocks, source_hash
    audit = json.loads((APP_DIR / "input/accessibility_matrix.audit.json").read_text())
    assert source_hash(MATRIX) == audit["matrix_sha256"]
    assert source_hash(ROOT / "data/blocks_metrics.geojson") == audit["blocks_sha256"]
    blocks = read_blocks()
    model = load_model(blocks)
    assert len(blocks) == 1039
    for column in RESULT_COLUMNS:
        np.testing.assert_allclose(model.baseline[column].fillna(0), blocks[column].fillna(0), rtol=0, atol=1e-8)
    assert model.payload(model.calculate([]))["summary"] == {
        "added": 0, "capacity": 15750, "deficit": 23353, "reduction": 0,
    }
