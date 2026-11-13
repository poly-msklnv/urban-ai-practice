"""Восстановить матрицу из доверенного кэша практики 2 или из исторического снимка OSM."""

import argparse
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from model import RESULT_COLUMNS, ROOT, SchoolModel, read_blocks, read_matrix, source_hash


def audit(blocks, matrix, output):
    model = SchoolModel(blocks, matrix, verify=False)
    comparisons = []
    for col in RESULT_COLUMNS:
        for block in blocks.index:
            old, new = blocks.loc[block, col], model.baseline.loc[block, col]
            if not np.isclose(0 if pd.isna(old) else old, 0 if pd.isna(new) else new, atol=1e-8, rtol=0):
                comparisons.append({"block_id": int(block), "column": col,
                                    "saved": None if pd.isna(old) else float(old),
                                    "recalculated": None if pd.isna(new) else float(new)})
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "blocks": len(blocks), "method": "competitive_provision", "blocksnet": version("blocksnet"),
        "iduedu": version("iduedu"), "numpy": version("numpy"), "pulp": version("pulp"),
        "accessibility_min": 15, "demand_per_1000": 120, "self_supply": True, "max_depth": 1,
        "blocks_sha256": source_hash(ROOT / "data/blocks_metrics.geojson"),
        "matrix_sha256": source_hash(output),
        "saved_deficit": int(blocks.demand_left.sum()),
        "recalculated_deficit": int(model.baseline.demand_left.sum()),
        "exact_baseline": not comparisons, "differences": comparisons,
        "id_rule": "0-based feature order in blocks_metrics.geojson; not stale intermediate layers",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--import-matrix", type=Path, help="Доверенный PKL из практики 2 или CSV с подписями ID")
    source.add_argument("--osm-date", help="Исторический снимок OSM, UTC ISO 8601, например 2026-10-20T21:00:00Z")
    parser.add_argument("--output", type=Path, required=True, help="Новый CSV(.gz), существующие файлы не перезаписываются")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Выходной файл уже существует. Выберите новый путь: исходную матрицу не перезаписываем.")
    blocks = read_blocks()
    if args.import_matrix:
        if args.import_matrix.suffix == ".pkl":
            # pickle допустим только для собственного доверенного кэша, не скачанного чужого файла.
            matrix = pd.read_pickle(args.import_matrix)
        else:
            matrix = read_matrix(args.import_matrix, blocks.index)
        origin = {"kind": "import", "source_name": args.import_matrix.name, "source_sha256": source_hash(args.import_matrix)}
    else:
        import geopandas as gpd
        import iduedu as ie
        import osmnx as ox
        stamp = datetime.strptime(args.osm_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")
        ox.settings.requests_timeout = 180
        ox.settings.overpass_settings = '[out:json][timeout:{timeout}][date:"' + stamp + '"]{maxsize}'
        boundary = gpd.read_file(ROOT / "data/boundaries.geojson")
        graph = ie.get_walk_graph(polygon=boundary.to_crs(4326).union_all(), walk_speed=83.3333)
        from blocksnet.relations import calculate_accessibility_matrix
        matrix = calculate_accessibility_matrix(blocks, graph)
        origin = {"kind": "historical_osm", "timestamp_utc": stamp, "walk_speed_m_per_min": 83.3333}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Сохраняем точные двоичные значения float16 как float64, а не округлённые десятичные строки.
    matrix.astype("float64").to_csv(args.output, index_label="block_id")
    matrix = read_matrix(args.output, blocks.index)
    report = audit(blocks, matrix, args.output)
    report["origin"] = origin
    report_path = args.output.with_name(args.output.name.removesuffix('.csv.gz') + '.audit.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ["blocks", "saved_deficit", "recalculated_deficit", "exact_baseline"]}, ensure_ascii=False))
    print("Аудит:", report_path)
    if not report["exact_baseline"]:
        print("Расчёт отличается от практики 2. Файл сохранён для диагностики, строгий режим его не примет.")
        raise SystemExit(2)
