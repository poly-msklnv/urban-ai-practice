"""Собирает dashboard.html только из готовых GeoJSON (data/*.geojson).

Ничего не скачивает и не пересчитывает метрики; медианное время пешком уже сохранено
ноутбуком в blocks_metrics.geojson (колонка median_time_min).
Запуск:  python dashboard.py
"""

import json
import os

import folium
import geopandas as gpd
import pandas as pd
from branca.colormap import LinearColormap


def find_project_root() -> str:
    for cand in (os.getcwd(), os.path.abspath(os.path.join(os.getcwd(), ".."))):
        if os.path.exists(os.path.join(cand, "pyproject.toml")):
            return cand
    return os.getcwd()


ROOT = find_project_root()
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "dashboard.html")

blocks = gpd.read_file(os.path.join(DATA, "blocks_metrics.geojson"))
schools = gpd.read_file(os.path.join(DATA, "schools.geojson"))

if blocks.crs is None:
    blocks = blocks.set_crs("EPSG:32631")

blocks["area_ha"] = blocks.area / 1e4
built = blocks[blocks["footprint_area"] > 0].copy()
g = blocks.to_crs(4326)

population = int(blocks["population"].sum())
capacity = int(blocks["capacity"].sum())
demand = int(blocks["demand"].sum())
fsi_median = round(float(built["fsi"].median()), 2)
gsi_median = round(float(built["gsi"].median()), 2)
walk_median = round(float(blocks["median_time_min"].median()), 1)
walk_max = round(float(blocks["median_time_min"].max()), 0)
deficit_blocks = int((blocks["demand_left"] > 0).sum())
provision_mean = round(float(built["provision_strong"].fillna(0).mean()), 2)
area_ha = round(float(blocks["area_ha"].sum()), 0)


def ru(num: int) -> str:
    return f"{num:,}".replace(",", " ")


# ------------------------------------------------------------------ карта
m = folium.Map(location=[41.3925, 2.1645], zoom_start=14, tiles=None, control_scale=True)

# Бесплатные подложки без API-ключа: Carto с 2026 требует ключ, поэтому используем Esri и OSM.
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attr="Esri, HERE, Garmin, OpenStreetMap contributors",
    name="Светлая подложка (Esri)",
    max_zoom=19,
    show=True,
).add_to(m)
folium.TileLayer(
    tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr="© OpenStreetMap contributors",
    name="OpenStreetMap",
    max_zoom=19,
    show=False,
).add_to(m)


def choropleth(column, name, palette, vmin=None, vmax=None, show=False):
    values = g[column].astype(float)
    lo = values.min() if vmin is None else vmin
    hi = values.max() if vmax is None else vmax
    cmap = LinearColormap(palette, vmin=lo, vmax=hi)
    cmap.caption = name

    def style(feature):
        value = feature["properties"].get(column)
        fill = "#e2e8f0" if value is None else cmap(value)
        return {"fillColor": fill, "color": "#4a5568", "weight": 0.3, "fillOpacity": 0.82}

    layer = folium.FeatureGroup(name=name, show=show)
    folium.GeoJson(
        g[["geometry", column]].to_json(),
        style_function=style,
        tooltip=folium.GeoJsonTooltip(fields=[column], aliases=[name]),
    ).add_to(layer)
    layer.add_to(m)


choropleth("fsi", "FSI — интенсивность застройки", ["#f7fbff", "#08306b"])
choropleth("population", "Население (оценка), чел.", ["#fff5eb", "#7f2704"])
choropleth("provision_strong", "Обеспеченность школами, доля", ["#d73027", "#fee08b", "#1a9850"], 0, 1)
choropleth("area_accessibility", "Доступность с учётом площади, мин", ["#ffffcc", "#800026"])
choropleth("l", "Средняя этажность L, этажей", ["#f2f0f7", "#54278f"])
choropleth("provision_weak", "Обеспеченность школами (мягкая), доля", ["#d73027", "#fee08b", "#1a9850"], 0, 1)
choropleth("demand_left", "Непокрытый спрос на школы (оценка), мест", ["#fff5f0", "#a50f15"])
choropleth("median_time_min", "Медианное время пешком, мин", ["#f1eef6", "#045a8d"])
choropleth("capacity", "Вместимость школ (оценка), мест", ["#f7fcf5", "#00441b"])

LU_COLORS = {
    "RESIDENTIAL": "#1f78b4", "BUSINESS": "#e31a1c", "RECREATION": "#33a02c",
    "INDUSTRIAL": "#6a3d9a", "SPECIAL": "#ff7f00", "TRANSPORT": "#b15928",
    "AGRICULTURE": "#b2df8a", "None": "#e2e8f0",
}


def lu_key(value) -> str:
    if value is None:
        return "None"
    text = str(value)
    if text in ("None", "nan", ""):
        return "None"
    return text.split(".")[-1].replace("'", "").replace(">", "").strip()


def lu_style(feature):
    return {"fillColor": LU_COLORS.get(lu_key(feature["properties"].get("land_use")), "#e2e8f0"),
            "color": "#4a5568", "weight": 0.3, "fillOpacity": 0.78}


# Слой землепользования: короткая подсказка при наведении и карточка со всеми показателями pipeline.ipynb по клику
TOOLTIP_FIELDS = [
    ("land_use", "Функция"), ("land_use_source", "Источник функции"),
    ("residential", "Доля жилой функции"), ("business", "Доля деловой"), ("recreation", "Доля рекреационной"),
    ("industrial", "Доля промышленной"), ("transport", "Доля транспортной"), ("special", "Доля специальной"),
    ("agriculture", "Доля с/х"), ("area_ha", "Площадь, га"), ("population", "Население (оценка), чел."),
    ("footprint_area", "Площадь застройки, м²"), ("build_floor_area", "Площадь этажей, м²"),
    ("living_area", "Жилая площадь (оценка), м²"), ("non_living_area", "Нежилая площадь, м²"),
    ("fsi", "FSI"), ("gsi", "GSI"), ("l", "Средняя этажность L"), ("mxi", "MXI"), ("osr", "OSR"),
    ("spacematrix", "Морфотип Spacematrix"), ("strelka", "Морфотип «Стрелки»"),
    ("median_time_min", "Медианное время пешком, мин"), ("area_accessibility", "Доступность с учётом площади, мин"),
    ("capacity", "Мест в школах (оценка)"), ("demand", "Спрос на места (оценка)"),
    ("demand_within", "Спрос покрыт в 15 мин"), ("demand_without", "Спрос покрыт дальше 15 мин"),
    ("demand_left", "Спрос не покрыт"), ("capacity_left", "Свободных мест"),
    ("provision_strong", "Обеспеченность (строгая)"), ("provision_weak", "Обеспеченность (мягкая)"),
]
tt_cols = [c for c, _ in TOOLTIP_FIELDS if c in g.columns]
tt = g[["geometry"] + tt_cols].copy()
INT_COLS = {"population", "footprint_area", "build_floor_area", "living_area", "non_living_area", "capacity",
            "demand", "demand_within", "demand_without", "demand_left", "capacity_left"}
for c in tt_cols:
    if pd.api.types.is_float_dtype(tt[c]):
        tt[c] = tt[c].round(0 if c in INT_COLS else 2)
tt["land_use"] = tt["land_use"].astype(str).str.replace("LandUse.", "", regex=False)

lu_layer = folium.FeatureGroup(name="Землепользование (OSM + оценка по застройке)", show=True)
short = [c for c in ("land_use", "land_use_source", "population", "fsi") if c in tt_cols]
folium.GeoJson(tt.to_json(), style_function=lu_style,
               tooltip=folium.GeoJsonTooltip(fields=short, aliases=[dict(TOOLTIP_FIELDS)[c] for c in short]),
               # по клику — все показатели квартала (прокручиваемая карточка)
               popup=folium.GeoJsonPopup(fields=tt_cols, aliases=[dict(TOOLTIP_FIELDS)[c] for c in tt_cols],
                                         maxHeight=380, maxWidth=420)).add_to(lu_layer)
lu_layer.add_to(m)

# Морфотипы: два категориальных слоя на карте (Spacematrix и «Стрелка»)
MORPH_PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
                 "#9c755f", "#bab0ac"]
NO_MORPH = {"nan", "None", "", "<NA>"}
morph_legends = {}


def morph_layer(column, name):
    values = g[column].astype(str)
    cats = [c for c in values.value_counts().index if c not in NO_MORPH]
    colors = {c: MORPH_PALETTE[i % len(MORPH_PALETTE)] for i, c in enumerate(cats)}
    morph_legends[name] = colors
    data = g[["geometry"]].assign(morph=values.where(~values.isin(NO_MORPH), "нет застройки"))

    def style(feature):
        return {"fillColor": colors.get(feature["properties"]["morph"], "#e2e8f0"), "color": "#4a5568",
                "weight": 0.3, "fillOpacity": 0.82}

    layer = folium.FeatureGroup(name=name, show=False)
    folium.GeoJson(data.to_json(), style_function=style,
                   tooltip=folium.GeoJsonTooltip(fields=["morph"], aliases=[name])).add_to(layer)
    layer.add_to(m)


morph_layer("spacematrix", "Морфотипы Spacematrix")
morph_layer("strelka", "Морфотипы «Стрелки»")

if len(schools):
    sch = folium.FeatureGroup(name="Школы (OSM)", show=False)
    for geom in schools.to_crs(4326).geometry:
        pt = geom.representative_point()
        folium.CircleMarker([pt.y, pt.x], radius=4, color="#1a9850", weight=1,
                            fill=True, fill_opacity=0.9, tooltip="Школа").add_to(sch)
    sch.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
map_iframe = m._repr_html_()

# ------------------------------------------------------------------ данные графиков
lu_norm = (blocks["land_use"].astype(str)
           .str.replace("LandUse.", "", regex=False)
           .replace({"None": "нет данных", "nan": "нет данных"}))
source = blocks.get("land_use_source", pd.Series("osm", index=blocks.index)).fillna("none")
osm_counts = lu_norm[source == "osm"].value_counts()
est_counts = lu_norm[source == "buildings"].value_counts()
lu_labels = sorted(set(osm_counts.index) | set(est_counts.index))
lu_osm = [int(osm_counts.get(c, 0)) for c in lu_labels]
lu_est = [int(est_counts.get(c, 0)) for c in lu_labels]
lu_osm_total = int((source == "osm").sum())
lu_est_total = int((source == "buildings").sum())
sm_counts = blocks["spacematrix"].astype(str).replace({"nan": "нет застройки", "None": "нет застройки"}).value_counts()
st_counts = blocks["strelka"].astype(str).replace({"nan": "нет застройки", "None": "нет застройки"}).value_counts()
provision_bins = pd.cut(built["provision_strong"].fillna(0),
                        bins=[-0.01, 0.0001, 0.25, 0.5, 0.75, 1.0],
                        labels=["0", "0–0,25", "0,25–0,5", "0,5–0,75", "0,75–1"]).value_counts().sort_index()
fsi_hist = pd.cut(built["fsi"], bins=[0, 0.5, 1, 1.5, 2, 3, 5, 100],
                  labels=["<0,5", "0,5–1", "1–1,5", "1,5–2", "2–3", "3–5", ">5"]).value_counts().sort_index()

# Распределение спроса на школьные места (сумма по району, оценка)
demand_parts = [("Спрос (дети)", "demand"), ("Мест в школах", "capacity"), ("Покрыт в пределах 15 мин", "demand_within"),
                ("Покрыт дальше 15 мин", "demand_without"), ("Не покрыт (нехватка)", "demand_left"),
                ("Свободных мест (остаток)", "capacity_left")]
demand_parts = [(lbl, col) for lbl, col in demand_parts if col in blocks.columns]

# Характеристики групп Spacematrix (медианы по застроенным кварталам каждой группы)
sm = built[~built["spacematrix"].astype(str).isin(NO_MORPH)]
sm_groups = (sm.groupby(sm["spacematrix"].astype(str))
               .agg(blocks=("fsi", "size"), population=("population", "sum"), fsi=("fsi", "median"),
                    gsi=("gsi", "median"), l=("l", "median"), mxi=("mxi", "median"))
               .sort_values("blocks", ascending=False))
sm_rows = "".join(
    f"<tr><td>{name}</td><td>{int(r.blocks)}</td><td>{ru(int(r.population))}</td><td>{r.fsi:.2f}</td>"
    f"<td>{r.gsi:.2f}</td><td>{r.l:.1f}</td><td>{r.mxi:.2f}</td></tr>"
    for name, r in sm_groups.iterrows()
)
legend_html = "".join(
    f"<div style='margin-bottom:8px'><b>{name}</b><br>" + " ".join(
        f"<span style='display:inline-block;margin:2px 10px 2px 0'><i style='display:inline-block;width:12px;"
        f"height:12px;background:{col};margin-right:4px;vertical-align:-1px'></i>{cat}</span>"
        for cat, col in colors.items()) + "</div>"
    for name, colors in morph_legends.items()
)

charts = {
    "land_use": {"labels": lu_labels, "osm": lu_osm, "estimate": lu_est},
    "spacematrix": {"labels": list(sm_counts.index), "values": [int(v) for v in sm_counts.values]},
    "strelka": {"labels": list(st_counts.index), "values": [int(v) for v in st_counts.values]},
    "provision": {"labels": [str(x) for x in provision_bins.index], "values": [int(v) for v in provision_bins.values]},
    "fsi": {"labels": [str(x) for x in fsi_hist.index], "values": [int(v) for v in fsi_hist.values]},
    "demand": {"labels": [lbl for lbl, _ in demand_parts],
               "values": [int(blocks[col].fillna(0).sum()) for _, col in demand_parts]},
}

top = built.sort_values("population", ascending=False).head(10)[
    ["population", "capacity", "fsi", "gsi", "provision_strong", "area_accessibility"]
].round(2)
top_rows = "".join(
    "<tr><td>{}</td>{}</tr>".format(idx, "".join(f"<td>{v}</td>" for v in row))
    for idx, row in top.iterrows()
)

density_rows = "".join(
    f"<tr><td>{label}</td><td>{built[col].median():.2f}</td><td>{built[col].mean():.2f}</td>"
    f"<td>{built[col].min():.2f}</td><td>{built[col].max():.2f}</td></tr>"
    for label, col in (("FSI — площадь этажей / площадь квартала", "fsi"),
                       ("GSI — доля застроенной земли", "gsi"),
                       ("MXI — смешанность функций", "mxi"),
                       ("OSR — открытые пространства", "osr"))
    if col in built.columns
)

METRICS_TABLE = """
<table>
<thead><tr><th>Показатель</th><th>Что означает</th><th>Единицы</th><th>Источник</th></tr></thead>
<tbody>
<tr><td>land_use</td><td>преобладающая функция квартала</td><td>категория</td><td>OSM landuse; где зон нет — оценка по составу застройки</td></tr>
<tr><td>residential … agriculture</td><td>доли функций в площади квартала</td><td>0–1</td><td>assign_land_use</td></tr>
<tr><td>median_time_min</td><td>медианное время пешком до остальных кварталов</td><td>минуты</td><td>матрица calculate_accessibility_matrix</td></tr>
<tr><td>population</td><td>население квартала</td><td>чел.</td><td><b>оценка</b> impute_buildings</td></tr>
<tr><td>footprint_area, build_floor_area</td><td>площадь застройки и площадь этажей</td><td>м²</td><td>OSM + восстановленная этажность</td></tr>
<tr><td>living_area, non_living_area</td><td>жилая и нежилая площадь</td><td>м²</td><td><b>оценка</b> impute_buildings</td></tr>
<tr><td>capacity</td><td>вместимость школ квартала</td><td>места</td><td><b>оценка</b> impute_services (250 мест на школу)</td></tr>
<tr><td>demand</td><td>спрос на школьные места (120 на 1000 жителей)</td><td>места</td><td><b>оценка</b> competitive_provision</td></tr>
<tr><td>demand_within / demand_without</td><td>спрос, покрытый в пределах 15 мин / дальше</td><td>места</td><td>competitive_provision</td></tr>
<tr><td>demand_left</td><td>непокрытый спрос на школьные места</td><td>места</td><td>competitive_provision</td></tr>
<tr><td>capacity_left</td><td>свободные места в школах квартала</td><td>места</td><td>competitive_provision</td></tr>
<tr><td>provision_strong / provision_weak</td><td>доля спроса, покрытая в 15 мин / с учётом дальних мест</td><td>0–1</td><td>competitive_provision</td></tr>
<tr><td>fsi</td><td>площадь этажей / площадь квартала</td><td>м²/м²</td><td>calculate_density_indicators</td></tr>
<tr><td>gsi</td><td>доля застроенной земли</td><td>0–1</td><td>calculate_density_indicators</td></tr>
<tr><td>l</td><td>средняя этажность (FSI / GSI)</td><td>этажи</td><td>calculate_density_indicators</td></tr>
<tr><td>mxi</td><td>доля жилой площади в площади этажей (индекс смешанности)</td><td>0–1</td><td>calculate_density_indicators</td></tr>
<tr><td>osr</td><td>открытое пространство на 1 м² площади этажей</td><td>м²/м²</td><td>calculate_density_indicators</td></tr>
<tr><td>spacematrix</td><td>морфотип по Spacematrix</td><td>категория</td><td>get_spacematrix_morphotypes</td></tr>
<tr><td>strelka</td><td>морфотип по классификации «Стрелки»</td><td>категория</td><td>get_strelka_morphotypes</td></tr>
<tr><td>area_accessibility</td><td>среднее время пешком до всех кварталов, взвешенное по их площади (меньше — центральнее)</td><td>минуты</td><td>area_accessibility</td></tr>
</tbody></table>
"""

conclusions = f"""
<ul>
<li><b>Плотность.</b> Медианный FSI застроенных кварталов — {fsi_median}, GSI — {gsi_median}:
кварталы Eixample застроены по периметру почти полностью, внутри — дворы.</li>
<li><b>Пешая доступность.</b> Медиана времени пешком до остальных кварталов — {walk_median} мин,
максимум {walk_max} мин: район компактен, любая точка достижима пешком.</li>
<li><b>Население.</b> Модельная оценка — {ru(population)} человек. Официально в Eixample около 265 000,
то есть модель завышает примерно на 20%: норма 30 м²/чел. и достроенная этажность.</li>
<li><b>Школы.</b> Оценка вместимости — {ru(capacity)} мест при спросе {ru(demand)} мест.
Дефицит возникает в {deficit_blocks} кварталах, средняя обеспеченность — {provision_mean}.</li>
<li><b>Землепользование.</b> Зоны OSM дают функцию только {lu_osm_total} кварталам, ещё {lu_est_total}
получили оценку по составу застройки (>= 50% зданий одного типа). Без метки остались кварталы без зданий —
мелкие осколки улиц, они занимают 8% площади.</li>
</ul>
"""

page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Eixample, Barcelona — кварталы и метрики</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: "Segoe UI", Roboto, Arial, sans-serif; margin: 0; background: #f7f7f9; color: #1f2933; }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  h3 {{ margin: 0 0 12px; font-size: 17px; }}
  .sub {{ color: #616e7c; margin-bottom: 20px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .kpi {{ background: #fff; border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .kpi b {{ display: block; font-size: 22px; }}
  .kpi span {{ color: #616e7c; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px; margin-bottom: 18px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  @media (max-width: 860px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
  iframe {{ width: 100%; height: 560px; border: 0; border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #e4e7eb; padding: 6px 8px; text-align: left; }}
  th {{ background: #f0f4f8; font-weight: 600; }}
  .note {{ background: #fff8e6; border-left: 4px solid #f0b429; padding: 12px 16px; border-radius: 6px; margin: 16px 0; font-size: 14px; }}
  ul {{ margin: 0; padding-left: 20px; line-height: 1.55; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Eixample, Barcelona — кварталы и метрики</h1>
  <div class="sub">Практика 2 · BlocksNet 1.0.0a9 · {len(blocks)} кварталов · {area_ha:.0f} га ·
  данные OpenStreetMap (выгрузка Geofabrik от 19.10.2026)</div>

  <div class="kpis">
    <div class="kpi"><span>Население (оценка)</span><b>{ru(population)}</b></div>
    <div class="kpi"><span>Мест в школах (оценка)</span><b>{ru(capacity)}</b></div>
    <div class="kpi"><span>Медианный FSI</span><b>{fsi_median}</b></div>
    <div class="kpi"><span>Медианный GSI</span><b>{gsi_median}</b></div>
    <div class="kpi"><span>Пешком, медиана</span><b>{walk_median} мин</b></div>
    <div class="kpi"><span>Кварталов с дефицитом школ</span><b>{deficit_blocks}</b></div>
  </div>

  <div class="card">
    {map_iframe}
  </div>
  <div class="note">Переключайте слои в правом верхнем углу карты; клик по кварталу открывает карточку со всеми его показателями. Население, вместимость школ
  и часть этажности — модельные оценки BlocksNet, а не официальная статистика.</div>

  <div class="grid2">
    <div class="card"><canvas id="landuse" height="220"></canvas></div>
    <div class="card"><canvas id="provision" height="220"></canvas></div>
    <div class="card"><canvas id="fsi" height="220"></canvas></div>
    <div class="card"><canvas id="spacematrix" height="220"></canvas></div>
    <div class="card"><canvas id="strelka" height="220"></canvas></div>
    <div class="card"><canvas id="demand" height="220"></canvas>
      <div class="note" style="font-size:12px">Распределение спроса моделью <code>competitive_provision</code>:
      норматив 120 мест на 1000 жителей, доступность 15 минут пешком. Вместимость школ — оценка (250 мест на школу).</div></div>
  </div>

  <div class="card">
    <h3>Цвета слоёв морфотипов на карте</h3>
    {legend_html}
  </div>

  <div class="card">
    <h3>Характеристики групп Spacematrix</h3>
    <table>
      <thead><tr><th>Группа</th><th>Кварталов</th><th>Население (оценка)</th><th>FSI, медиана</th>
      <th>GSI, медиана</th><th>L, этажей</th><th>MXI, медиана</th></tr></thead>
      <tbody>{sm_rows}</tbody>
    </table>
    <div class="note" style="margin-top:12px;font-size:13px">FSI — площадь этажей / площадь квартала, GSI — доля
    застроенной земли, L — средняя этажность, MXI — доля жилой площади. Медианы по застроенным кварталам группы.</div>
  </div>

  <div class="card">
    <h3>Плотность застройки: статистика по застроенным кварталам</h3>
    <table>
      <thead><tr><th>Показатель</th><th>Медиана</th><th>Среднее</th><th>Мин</th><th>Макс</th></tr></thead>
      <tbody>{density_rows}</tbody>
    </table>
    <div class="note" style="margin-top:12px;font-size:13px">Экстремальные значения OSR
    (от −0,5 до 731) — следствие деления на малую площадь этажей в отдельных кварталах;
    ориентируйтесь на медиану.</div>
  </div>

  <div class="card"><h3>Что означают показатели</h3>{METRICS_TABLE}</div>
  <div class="card"><h3>Выводы</h3>{conclusions}</div>

  <div class="card">
    <h3>Топ-10 кварталов по населению</h3>
    <table>
      <thead><tr><th>Квартал</th><th>Население</th><th>Мест в школах</th><th>FSI</th><th>GSI</th>
      <th>Обеспеченность</th><th>Доступность с учётом площади, мин</th></tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
  </div>

  <div class="note">Ограничения: границы кварталов построены по осям улиц, а не по кадастру;<br>землепользование взято из OSM там, где есть зоны, иначе оценено по составу застройки (помечено в подсказке);<br>доступность считается только пешком, без общественного транспорта и рельефа.</div>
</div>
<script>
const DATA = {json.dumps(charts, ensure_ascii=False)};
const PALETTE = ['#2b6cb0','#c53030','#2f855a','#6b46c1','#d69e2e','#2c7a7b','#975a16','#4a5568'];
function draw(id, title, obj, horizontal) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels: obj.labels, datasets: [{{ data: obj.values, backgroundColor: PALETTE }}] }},
    options: {{
      indexAxis: horizontal ? 'y' : 'x',
      plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: title, font: {{ size: 14 }} }} }},
      scales: {{ x: {{ beginAtZero: true }}, y: {{ beginAtZero: true }} }}
    }}
  }});
}}
new Chart(document.getElementById('landuse'), {{
  type: 'bar',
  data: {{ labels: DATA.land_use.labels, datasets: [
    {{ label: 'OSM', data: DATA.land_use.osm, backgroundColor: '#2b6cb0' }},
    {{ label: 'оценка по застройке', data: DATA.land_use.estimate, backgroundColor: '#90cdf4' }}
  ] }},
  options: {{
    indexAxis: 'y',
    plugins: {{ title: {{ display: true, text: 'Землепользование: число кварталов', font: {{ size: 14 }} }},
               legend: {{ position: 'bottom' }} }},
    scales: {{ x: {{ stacked: true, beginAtZero: true }}, y: {{ stacked: true }} }}
  }}
}});
draw('provision', 'Обеспеченность школами (доля покрытого спроса)', DATA.provision, false);
draw('fsi', 'Распределение FSI по застроенным кварталам', DATA.fsi, false);
draw('spacematrix', 'Морфотипы Spacematrix', DATA.spacematrix, true);
draw('strelka', 'Морфотипы «Стрелки»', DATA.strelka, true);
draw('demand', 'Распределение спроса на школьные места (оценка), мест', DATA.demand, true);
</script>
</body>
</html>
"""

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(page)

print("dashboard.html:", round(os.path.getsize(OUT) / 1e6, 2), "MB")
print("кварталов:", len(blocks), "| застроенных:", len(built), "| школ:", len(schools))
