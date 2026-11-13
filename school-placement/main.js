'use strict';
const $ = id => document.getElementById(id);
const fmt = n => n === null || n === undefined ? '—' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(n);
const pct = n => n === null ? '—' : fmt(n * 100);
let initial, current, draft = [], applied = [], selected = 0, ready = false, busy = false;
let variants = [], searchCapacity = null, saved = [], map, fullBounds, paths = new Map();
const controls = ['add', 'calculate', 'reset', 'search', 'save'];
function message(text, ok = false) { $('notice').textContent = text; $('notice').classList.toggle('ok', ok); }
function setBusy(value) {
  busy = value;
  controls.forEach(id => $(id).disabled = busy || !ready);
  document.querySelectorAll('[data-show-variant],[data-saved],[data-remove]').forEach(b => b.disabled = busy || !ready);
  $('capacity').disabled = busy;
  $('autoCapacity').disabled = busy;
}
async function post(url, body) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) throw new Error((await response.json()).error || 'Не удалось выполнить запрос.');
  return response;
}
function capacity(id) {
  const input = $(id), n = Number(input.value);
  if (!input.checkValidity() || !Number.isSafeInteger(n) || n <= 0) {
    input.reportValidity();
    throw new Error('Вместимость школы должна быть положительным целым числом.');
  }
  return n;
}
function button(text, handler) {
  const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.onclick = handler; return b;
}
function cell(row, value, className) {
  const td = document.createElement('td'); td.textContent = value; if (className) td.className = className; row.append(td); return td;
}
function draftList() {
  $('placements').replaceChildren();
  if (!draft.length) { const li = document.createElement('li'); li.textContent = 'Новые школы не добавлены.'; $('placements').append(li); }
  draft.forEach((p, i) => {
    const li = document.createElement('li'); li.textContent = `Квартал ${p.block_id} · ${fmt(p.capacity)} мест`;
    const b = button('Убрать', () => { draft.splice(i, 1); draftList(); }); b.dataset.remove = ''; b.disabled = busy;
    li.append(b); $('placements').append(li);
  });
  $('dirty').textContent = JSON.stringify(draft) === JSON.stringify(applied)
    ? (applied.length ? 'Карта и таблица: рассчитанный сценарий.' : 'Карта и таблица: исходное состояние.')
    : 'Есть нерассчитанные изменения. Карта и таблица показывают последний расчёт.';
  drawMap();
}
function selectBlock(id, zoom = false) {
  selected = id; $('block').value = id;
  const r = current.rows.find(r => r.block_id === id);
  $('blockCard').replaceChildren();
  const h = document.createElement('h2'); h.textContent = `Квартал ${id}`; $('blockCard').append(h);
  const dl = document.createElement('dl');
  [['Население, оценка', `${fmt(r.population)} чел.`], ['Вместимость: было → стало', `${fmt(r.capacity_base)} → ${fmt(r.capacity)} мест`],
   ['Обеспеченность: было → стало', `${pct(r.provision_base)} → ${pct(r.provision)} %`], ['Дефицит: был → стал', `${fmt(r.deficit_base)} → ${fmt(r.deficit)} мест`]].forEach(([label, val]) => {
    const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label; dd.textContent = val; div.append(dt, dd); dl.append(div);
  });
  $('blockCard').append(dl);
  if (zoom) map.fitBounds(paths.get(id).getBounds().pad(3), {maxZoom: 17, animate: false});
  document.querySelectorAll('#rows tr').forEach(tr => tr.classList.toggle('active', Number(tr.dataset.id) === id));
  drawMap();
}
function color(value, change) {
  if (value === null) return '#e1e5ea';
  if (change) return value < -0.00001 ? '#c97730' : value > 0.00001 ? '#3476ae' : '#edf1f5';
  return value < 0.25 ? '#f3d6b3' : value < 0.5 ? '#b3cde0' : value < 0.75 ? '#6499c0' : '#245b92';
}
function drawMap() {
  if (!current) return;
  const mode = $('mode').value, change = mode === 'change';
  for (const r of current.rows) {
    const path = paths.get(r.block_id); if (!path) continue;
    const value = mode === 'base' ? r.provision_base : change
      ? (r.provision === null || r.provision_base === null ? null : r.provision - r.provision_base) : r.provision;
    path.setStyle({fillColor: color(value, change)});
    path.getElement()?.classList.toggle('selected', r.block_id === selected);
    path.getElement()?.classList.toggle('planned', applied.some(p => p.block_id === r.block_id));
    path.setTooltipContent(`Квартал ${r.block_id}: ${change ? 'изменение' : 'обеспеченность'} ${pct(value)} ${change ? 'п. п.' : '%'}`);
  }
  $('legend').replaceChildren(document.createTextNode(change ? 'Изменение, п. п.' : 'Обеспеченность, %'));
  const entries = change ? [['#c97730', 'снижение'], ['#edf1f5', 'без изменений'], ['#3476ae', 'рост']]
    : [['#f3d6b3', '0–<25'], ['#b3cde0', '25–<50'], ['#6499c0', '50–<75'], ['#245b92', '75–100']];
  entries.push(['#e1e5ea', 'нет спроса']);
  entries.forEach(([c, text]) => { const i = document.createElement('i'); i.style.background = c; $('legend').append(i, document.createTextNode(text)); });
  const contours = document.createElement('div'); contours.textContent = 'Чёрный контур: выбранный квартал · пунктир: новая школа'; $('legend').append(contours);
}
function initMap(features) {
  map = L.map('map', {zoomControl: false, scrollWheelZoom: false});
  const tiles = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, GIS user community',
    maxNativeZoom: 16, maxZoom: 19
  });
  let tileErrors = 0;
  tiles.on('loading', () => { tileErrors = 0; $('tileStatus').textContent = 'Загрузка подложки…'; });
  tiles.on('tileerror', () => { tileErrors++; });
  tiles.on('load', () => { $('tileStatus').textContent = tileErrors
    ? 'Часть подложки недоступна. Проверьте интернет; расчёты доступны.' : 'Подложка загружена'; });
  tiles.addTo(map);
  const quarters = L.geoJSON({type: 'FeatureCollection', features}, {
    style: {color: '#707d85', weight: 0.5, fillOpacity: 0.6},
    onEachFeature: (feature, layer) => {
      paths.set(feature.properties.block_id, layer);
      layer.bindTooltip(`Квартал ${feature.properties.block_id}`);
      layer.on('click', () => selectBlock(feature.properties.block_id));
    }
  }).addTo(map);
  fullBounds = quarters.getBounds();
  map.fitBounds(fullBounds.pad(0.08), {animate: false});
  L.control.scale({imperial: false, maxWidth: 130}).addTo(map);
}
function render() {
  const s = current.summary;
  $('added').textContent = fmt(s.added); $('totalCapacity').textContent = fmt(s.capacity);
  $('deficit').textContent = fmt(s.deficit); $('reduction').textContent = fmt(s.reduction);
  const fragment = document.createDocumentFragment();
  for (const r of current.rows) {
    const tr = document.createElement('tr'); tr.dataset.id = r.block_id;
    const td = document.createElement('td'); td.append(button(String(r.block_id), () => selectBlock(r.block_id, true))); tr.append(td);
    [r.population, r.demand, r.capacity_base, r.capacity, r.deficit_base, r.deficit, r.reduction].forEach(v => cell(tr, fmt(v)));
    cell(tr, pct(r.provision_base)); cell(tr, pct(r.provision)); fragment.append(tr);
  }
  $('rows').replaceChildren(fragment); selectBlock(selected); draftList();
}
async function calculate(placements, select = null) {
  if (busy || !ready) return;
  setBusy(true); message('Рассчитываем обеспеченность всех кварталов…');
  try {
    const response = await post('/api/calculate', {placements});
    current = await response.json(); applied = structuredClone(placements); draft = structuredClone(placements);
    if (select !== null) selected = select;
    render(); $('mode').value = 'scenario'; drawMap(); message('Сценарий рассчитан. Карта, показатели и таблица обновлены.', true);
  } catch (e) { message(e.message); } finally { setBusy(false); }
}
function download(name, headers, rows) {
  const quote = x => `"${String(x ?? '').replaceAll('"', '""')}"`;
  const csv = '\uFEFF' + [headers, ...rows].map(r => r.map(quote).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderRanking(result) {
  $('ranking').replaceChildren();
  const fragment = document.createDocumentFragment();
  result.variants.forEach(v => {
    const tr = document.createElement('tr'); cell(tr, v.block_id); cell(tr, fmt(v.deficit)); cell(tr, fmt(v.reduction));
    cell(tr, v.error || (result.best_ids.includes(v.block_id) ? (result.complete ? 'Лучший результат' : 'Лучший из рассчитанных') : 'Рассчитан'), 'error');
    const td = document.createElement('td');
    if (!v.error) { const b = button('Показать', () => calculate([{block_id: v.block_id, capacity: searchCapacity}], v.block_id)); b.dataset.showVariant = ''; td.append(b); }
    tr.append(td); fragment.append(tr);
  });
  $('ranking').append(fragment); $('exportSearch').disabled = false;
  $('rankingNote').textContent = result.complete
    ? `Проверены все ${result.total} кварталов. Равноценные лучшие: ${result.best_ids.join(', ')}.`
    : `Перебор неполный: успешно ${result.successful} из ${result.total}. Лучший вариант среди всех кварталов не установлен. Ошибки приведены в таблице.`;
}
async function search() {
  if (busy || !ready) return;
  let n; try { n = capacity('autoCapacity'); } catch (e) { message(e.message); return; }
  setBusy(true); variants = []; searchCapacity = n; $('ranking').replaceChildren(); $('exportSearch').disabled = true;
  $('progress').value = 0; $('searchStatus').textContent = `Проверено 0 из ${initial.rows.length}`;
  $('rankingNote').textContent = 'Идёт поиск. Итоговый рейтинг пока недоступен.';
  message('Проверяем каждый квартал независимо. Это может занять несколько минут.');
  let result = null;
  try {
    const response = await post('/api/search', {capacity: n}), reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const chunk = await reader.read(); if (chunk.done) break;
      buffer += decoder.decode(chunk.value, {stream: true});
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.error) throw new Error(event.error);
        if (event.variant) {
          variants.push(event.variant); $('progress').value = event.progress;
          $('searchStatus').textContent = `Проверено ${event.progress} из ${event.total}; ошибок ${variants.filter(v => v.error).length}`;
        }
        if (event.done) result = event.done;
      }
    }
    if (!result) throw new Error('Соединение прервалось. Полный перебор не завершён.');
    variants = result.variants; renderRanking(result);
    message(result.complete ? `Перебор завершён. Лучших вариантов: ${result.best_ids.length}.` : 'Перебор неполный. См. ошибки в таблице.', result.complete);
  } catch (e) {
    const good = variants.filter(v => !v.error).sort((a, b) => b.reduction - a.reduction || a.block_id - b.block_id);
    renderRanking({variants: [...good, ...variants.filter(v => v.error)], best_ids: [], complete: false,
      successful: good.length, total: initial.rows.length});
    $('searchStatus').textContent += ' · Перебор прерван'; message(e.message);
  } finally { setBusy(false); }
  if (result?.complete && result.best_ids.length) await calculate([{block_id: result.best_ids[0], capacity: n}], result.best_ids[0]);
}
function renderSaved() {
  $('saved').replaceChildren();
  [{name: 'Исходное состояние', data: initial, placements: []}, ...saved].forEach(s => {
    const tr = document.createElement('tr'); cell(tr, s.name); cell(tr, s.placements.map(p => `${p.block_id} / ${p.capacity}`).join('; ') || 'Нет новых школ');
    cell(tr, fmt(s.data.summary.added)); cell(tr, fmt(s.data.summary.deficit)); cell(tr, fmt(s.data.summary.reduction));
    const td = document.createElement('td'); const b = button('Открыть', () => {
      if (busy) return;
      current = structuredClone(s.data); draft = structuredClone(s.placements); applied = structuredClone(s.placements);
      render(); $('mode').value = 'scenario'; drawMap(); message(`Открыт сценарий: ${s.name}`, true);
    }); b.dataset.saved = ''; b.disabled = busy; td.append(b); tr.append(td); $('saved').append(tr);
  });
}
$('addForm').onsubmit = e => {
  e.preventDefault(); if (!ready || busy) return;
  try { draft.push({block_id: Number($('block').value), capacity: capacity('capacity')}); draftList(); } catch (e) { message(e.message); }
};
$('block').onchange = () => selectBlock(Number($('block').value), true);
$('calculate').onclick = () => calculate(structuredClone(draft));
$('reset').onclick = () => {
  current = structuredClone(initial); draft = []; applied = []; selected = 0; $('mode').value = 'base';
  variants = []; searchCapacity = null; $('ranking').replaceChildren(); $('exportSearch').disabled = true;
  $('progress').value = 0; $('searchStatus').textContent = 'Поиск ещё не запускался.';
  $('rankingNote').textContent = 'Результаты появятся после поиска.'; map.fitBounds(fullBounds.pad(0.08), {animate: false}); render();
  message('Изменения сброшены. Показано исходное состояние.', true);
};
$('mode').onchange = drawMap;
$('search').onclick = search;
$('save').onclick = () => {
  const name = $('scenarioName').value.trim() || `Сценарий ${saved.length + 1}`;
  saved.push({name, data: structuredClone(current), placements: structuredClone(applied)}); renderSaved();
  message(`Сохранён последний рассчитанный сценарий «${name}».`, true);
};
$('export').onclick = () => download('school-placement.csv',
  ['Квартал', 'Население, чел.', 'Спрос, мест', 'Вместимость исходная, мест', 'Вместимость сценария, мест', 'Дефицит исходный, мест', 'Дефицит сценария, мест', 'Сокращение дефицита, мест', 'Обеспеченность исходная, %', 'Обеспеченность сценария, %'],
  current.rows.map(r => [r.block_id, r.population, r.demand, r.capacity_base, r.capacity, r.deficit_base, r.deficit, r.reduction,
    r.provision_base === null ? '' : r.provision_base * 100, r.provision === null ? '' : r.provision * 100]));
$('exportSearch').onclick = () => download('school-placement-search.csv', ['Квартал', 'Новая школа, мест', 'Дефицит, мест', 'Сокращение, мест', 'Ошибка'],
  variants.map(v => [v.block_id, searchCapacity, v.deficit, v.reduction, v.error]));
$('zoomIn').onclick = () => map.zoomIn(); $('zoomOut').onclick = () => map.zoomOut();
$('mapReset').onclick = () => map.fitBounds(fullBounds.pad(0.08), {animate: false});
(async () => {
  try {
    const response = await fetch('/api/data'); if (!response.ok) throw new Error('Не удалось загрузить данные.');
    const data = await response.json(); ready = data.ready; initial = data.baseline; current = structuredClone(initial);
    initMap(data.geometry.features); $('progress').max = initial.rows.length;
    for (const r of initial.rows) { const option = document.createElement('option'); option.value = r.block_id; option.textContent = `Квартал ${r.block_id}`; $('block').append(option); }
    render(); renderSaved(); setBusy(false); $('export').disabled = false;
    message(data.error || 'Исходный расчёт воспроизведён по всем кварталам. Можно сравнивать сценарии.', ready);
  } catch (e) { message(e.message); }
})();
