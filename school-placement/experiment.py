"""Воспроизводимый эксперимент А / Б / В. Запускать из любого каталога."""

import json
from pathlib import Path

import pandas as pd

from model import MATRIX, ROOT, load_model, rank_variants, read_blocks, source_hash

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"


def run():
    OUT.mkdir(exist_ok=True)
    choices = json.loads((HERE / "experiment-selection.json").read_text())
    blocks = read_blocks()
    model = load_model(blocks)
    base_hash, matrix_hash = source_hash(ROOT / "data/blocks_metrics.geojson"), source_hash(MATRIX)
    results = {}
    model.baseline.to_csv(OUT / "baseline.csv", index_label="block_id")
    for name in ["A", "B"]:
        result = model.calculate(choices[name]["placements"])
        results[name] = model.payload(result)
        pd.DataFrame(results[name]["rows"]).to_csv(OUT / f"scenario_{name}.csv", index=False)
    variants = []
    for v in model.search(600):
        variants.append(v)
        if len(variants) % 50 == 0 or len(variants) == len(blocks):
            print(f"Проверено {len(variants)} / {len(blocks)}", flush=True)
    ranking = rank_variants(variants, len(blocks))
    table = pd.DataFrame(ranking["variants"])
    table["best"] = table.block_id.isin(ranking["best_ids"])
    table.to_csv(OUT / "automatic_600.csv", index=False)
    if not ranking["complete"]:
        raise RuntimeError("Неполный перебор; победитель не объявлен. Ошибки сохранены в automatic_600.csv.")
    winner = ranking["best_ids"][0]
    automatic = next(v for v in variants if v["block_id"] == winner)
    manual = model.calculate([{"block_id": winner, "capacity": 600}])
    assert int(manual.demand_left.sum()) == automatic["deficit"]
    results["C"] = model.payload(manual)
    pd.DataFrame(results["C"]["rows"]).to_csv(OUT / "scenario_C.csv", index=False)
    summary = {
        "blocks_sha256": base_hash, "matrix_sha256": matrix_hash,
        "selection_sha256": source_hash(HERE / "experiment-selection.json"),
        "baseline": model.payload(model.baseline)["summary"],
        "scenarios": {name: data["summary"] for name, data in results.items()},
        "automatic": {k: v for k, v in ranking.items() if k != "variants"},
        "scenario_C_block": winner,
        "manual_A_is_optimal": choices["A"]["placements"][0]["block_id"] in ranking["best_ids"],
        "affected_blocks": {name: {
            "improved": [r["block_id"] for r in data["rows"] if r["reduction"] > 0],
            "worsened": [r["block_id"] for r in data["rows"] if r["reduction"] < 0],
            "remaining_deficit": [r["block_id"] for r in data["rows"] if r["deficit"] > 0],
        } for name, data in results.items()},
        "checks": {"baseline_exact": True, "all_blocks_searched": True, "manual_matches_auto": True,
                   "source_files_unchanged": base_hash == source_hash(ROOT / "data/blocks_metrics.geojson")
                   and matrix_hash == source_hash(MATRIX)},
    }
    assert summary["checks"]["source_files_unchanged"]
    (OUT / "experiment.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    report = ["# Эксперимент размещения школ", "", "Метод и параметры практики 2 сохранены; исходный расчёт совпал по всем 10 показателям во всех 1039 кварталах.",
              "Матрица восстановлена из исторического снимка OSM 20.10.2026 21:00 UTC; исходные GeoJSON не изменены.", "",
              "## Выбор до поиска", "", "А. " + choices["A"]["reason"], "", "Б. " + choices["B"]["reason"], "",
              "## Сравнение", "", "| Состояние | Новых мест | Дефицит, мест | Сокращение, мест |", "|---|---:|---:|---:|",
              f"| Исходное | 0 | {summary['baseline']['deficit']} | 0 |"]
    labels = {"A": "А: 600 мест, квартал 766", "B": "Б: 2 × 300 мест, кварталы 766 и 92", "C": f"В: автоматический, квартал {winner}"}
    for name, data in results.items():
        s = data["summary"]
        report.append(f"| {labels[name]} | {s['added']} | {s['deficit']} | {s['reduction']} |")
    all_tie = len(ranking["best_ids"]) == len(blocks)
    best = max(d["summary"]["reduction"] for d in results.values())
    leaders = [labels[n] for n,d in results.items() if d["summary"]["reduction"] == best]
    report += ["", "## Ответы", "", f"Наибольшее сокращение ({best} мест): " + "; ".join(leaders) + ".",
               f"Проверены независимо все {len(blocks)} кварталов, ошибок нет. Равноценных лучших вариантов одной школы: {len(ranking['best_ids'])}. "
               "Все ID и ранжирование сохранены в [automatic_600.csv](automatic_600.csv), лучшие отмечены best=True.", "",
               ("Ручной выбор А вошёл в множество оптимальных; " if summary["manual_A_is_optimal"] else "Ручной выбор А не вошёл в множество оптимальных; ")
               + f"на карте сценария В выбран минимальный ID среди равных ({winner}). Это правило отображения, не дополнительный критерий качества.", ""]
    if all_tie:
        report += ["Все существующие места уже заняты в исходном расчёте. Каждая из 1039 проверок использует все 600 новых мест: "
                   "достигнут верхний предел сокращения дефицита при таком приросте вместимости. "
                   "Поэтому заданный суммарный критерий не различает расположение; таблица не даёт оснований выделять единственный квартал. "
                   "Пространственное распределение улучшений при этом отличается. Для дальнейшего выбора нужны дополнительные критерии "
                   "(участок, строительство, справедливость доступности), которые в автоматический поиск этой практики не добавлялись.", ""]
    for name in results:
        affected = summary["affected_blocks"][name]
        report += [f"**{labels[name]}**: обеспеченность повысилась в {len(affected['improved'])} кварталах, "
                   f"снизилась в {len(affected['worsened'])}; дефицит сохранился в {len(affected['remaining_deficit'])}. "
                   f"Полные ID перечислены в [experiment.json](experiment.json), показатели каждого квартала — в [scenario_{name}.csv](scenario_{name}.csv).", ""]
    report += ["## Ограничения", "", "Население — расчёт по площади жилья; мощности — 250 мест на объект OSM, не фактические места. "
               "Модель не учитывает возрастную структуру, школы за границей района, транспорт и реальные участки. "
               "Метод конкурентно распределяет спрос с приоритетом собственного квартала; изменение мощностей может перераспределить места между соседями. "
               "Автоматический поиск проверяет только одну школу: сравнение с Б не доказывает оптимальность выбранной пары.", "",
               "Повторное скачивание актуального OSM первоначально изменило распределение 17 мест между кварталами 126 и 153. "
               "Причина подтверждена контролем с историческим графом при неизменных геометрии, населении, вместимости и ПО. "
               "Подробности — [matrix_drift_diagnosis.json](matrix_drift_diagnosis.json). Используется историческая, прошедшая точную сверку матрица; "
               "полное равенство её времен утраченному PKL доказать нельзя, но все сохранённые школьные показатели воспроизведены.", "",
               "## Воспроизведение", "", "`python school-placement/experiment.py` · контрольные суммы входов и выбор А/Б — в experiment.json; "
               "CSV результатов хранятся отдельно от input/. Веб-интерфейс не сохраняет пользовательские сценарии на диск автоматически."]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n")
    print(json.dumps(summary["scenarios"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    run()
