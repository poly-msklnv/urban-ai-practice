"""Практика 3: тот же competitive_provision, независимые сценарии, строгая сверка baseline."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from blocksnet.analysis.provision import competitive_provision
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
INPUT = Path(__file__).resolve().parent / "input"
MATRIX = INPUT / "accessibility_matrix.csv.gz"
ACCESSIBILITY = 15
DEMAND = 120
RESULT_COLUMNS = [
    "demand", "capacity", "demand_left", "demand_within", "demand_without",
    "capacity_left", "capacity_within", "capacity_without", "provision_strong", "provision_weak",
]
logger.disable("blocksnet")


def read_blocks(path=ROOT / "data/blocks_metrics.geojson"):
    blocks = gpd.read_file(path)
    # В исходном GeoJSON ID не записан: индекс восстанавливается как в ноутбуке, по порядку записей.
    blocks.index = pd.Index(range(len(blocks)), name="block_id")
    required = ["population", *RESULT_COLUMNS]
    if blocks.empty or any(c not in blocks for c in required):
        raise ValueError("Нет кварталов или обязательных показателей практики 2.")
    values = blocks[[c for c in required if not c.startswith("provision_")]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Население, спрос и вместимость должны быть конечными неотрицательными числами.")
    if (blocks.capacity % 1 != 0).any():
        raise ValueError("Вместимость существующих школ должна быть целой.")
    return blocks


def read_matrix(path, ids):
    matrix = pd.read_csv(path, index_col=0)
    try:
        matrix.index = matrix.index.astype(int)
        matrix.columns = matrix.columns.astype(int)
    except (ValueError, TypeError) as exc:
        raise ValueError("ID матрицы должны быть целыми идентификаторами кварталов.") from exc
    if not matrix.index.is_unique or not matrix.columns.is_unique:
        raise ValueError("Повторяющиеся ID матрицы.")
    if set(matrix.index) != set(ids) or set(matrix.columns) != set(ids):
        raise ValueError("ID строк/столбцов матрицы не совпадают с ID кварталов.")
    matrix = matrix.loc[ids, ids].astype(float)
    values = matrix.to_numpy()
    if not np.isfinite(values).all() or (values < 0).any() or not np.allclose(np.diag(values), 0):
        raise ValueError("Матрица должна содержать конечное неотрицательное время в минутах и нули на диагонали.")
    return matrix


def validate_placements(items, ids):
    if not isinstance(items, list):
        raise ValueError("Школы должны быть списком кварталов и вместимостей.")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Неверная запись школы.")
        block, capacity = item.get("block_id"), item.get("capacity")
        if type(block) is not int or block not in ids:
            raise ValueError("Неизвестный квартал.")
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("Вместимость школы должна быть положительным целым числом.")
        result.append({"block_id": block, "capacity": capacity})
    return result


class SchoolModel:
    def __init__(self, blocks, matrix, verify=True):
        if version("blocksnet") != "1.0.0a9":
            raise ValueError("Нужен BlocksNet 1.0.0a9, как в практике 2.")
        self.blocks = blocks.copy(deep=True)
        self.matrix = matrix.copy(deep=True)
        self.baseline = self.calculate([])
        if verify:
            mismatch = []
            for col in RESULT_COLUMNS:
                expected = blocks[col].fillna(0).to_numpy(dtype=float)
                actual = self.baseline[col].fillna(0).to_numpy(dtype=float)
                if not np.allclose(actual, expected, atol=1e-8, rtol=0):
                    mismatch.append(col)
            if mismatch:
                raise ValueError(
                    "Исходный расчёт НЕ воспроизведён по кварталам: " + ", ".join(mismatch)
                    + ". Нужна оригинальная матрица практики 2; новые данные OSM могут изменить результат."
                )

    def calculate(self, placements):
        placements = validate_placements(placements, self.blocks.index)
        frame = self.blocks[["population", "capacity"]].copy(deep=True)
        for item in placements:
            frame.loc[item["block_id"], "capacity"] += item["capacity"]
        result, _ = competitive_provision(
            frame, self.matrix, ACCESSIBILITY, DEMAND, self_supply=True, max_depth=1
        )
        # 0/0 в BlocksNet означает отсутствие спроса, а не нулевую обеспеченность.
        if not np.isfinite(result[["demand", "capacity", "demand_left", "demand_within"]]).all().all():
            raise ValueError("Метод вернул нечисловые показатели.")
        if (result.demand_left < 0).any() or not np.allclose(
            result.demand_left + result.demand_within + result.demand_without, result.demand
        ):
            raise ValueError("Нарушен баланс распределения спроса.")
        return result

    def payload(self, result):
        return result_payload(self.blocks, self.baseline, result)

    def search(self, capacity):
        validate_placements([{"block_id": int(self.blocks.index[0]), "capacity": capacity}], self.blocks.index)
        for block in self.blocks.index:
            try:
                result = self.calculate([{"block_id": int(block), "capacity": capacity}])
                deficit = int(result.demand_left.sum())
                yield {"block_id": int(block), "deficit": deficit,
                       "reduction": int(self.baseline.demand_left.sum()) - deficit, "error": None}
            except Exception as exc:  # один сбой не скрывает неполный перебор
                yield {"block_id": int(block), "deficit": None, "reduction": None, "error": str(exc)}


def result_payload(blocks, base, result):
    rows = pd.DataFrame({
        "block_id": blocks.index,
        "population": blocks.population.to_numpy(),
        "demand": result.demand.to_numpy(),
        "capacity_base": base.capacity.to_numpy(),
        "capacity": result.capacity.to_numpy(),
        "deficit_base": base.demand_left.to_numpy(),
        "deficit": result.demand_left.to_numpy(),
        "reduction": (base.demand_left - result.demand_left).to_numpy(),
        "provision_base": base.provision_strong.to_numpy(),
        "provision": result.provision_strong.to_numpy(),
    })
    deficit = int(result.demand_left.sum())
    return {
        "rows": json.loads(rows.to_json(orient="records")),
        "summary": {"added": int(result.capacity.sum() - base.capacity.sum()),
                    "capacity": int(result.capacity.sum()), "deficit": deficit,
                    "reduction": int(base.demand_left.sum()) - deficit},
    }


def rank_variants(variants, total):
    good = sorted((v for v in variants if not v["error"]), key=lambda v: (-v["reduction"], v["block_id"]))
    best = [v["block_id"] for v in good if v["reduction"] == good[0]["reduction"]] if good else []
    return {"variants": good + [v for v in variants if v["error"]], "best_ids": best,
            "complete": len(variants) == total and len(good) == total,
            "checked": len(variants), "successful": len(good), "total": total}


def load_model(blocks, matrix_path=MATRIX):
    return SchoolModel(blocks, read_matrix(matrix_path, blocks.index))


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
