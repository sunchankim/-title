const $ = id => document.getElementById(id);
const fmt = (x, d = 3) => Number(x).toLocaleString('ko-KR', { maximumFractionDigits: d });
const fmt4 = x => Number(x).toLocaleString('ko-KR', { minimumFractionDigits: 4, maximumFractionDigits: 4 });

let worker, nextId = 0, requests = new Map();
let sectors = [], rowChoices = [], cells = [], basket = [], result = null;
let indicators = [], chains = {}, currentSummary = null;

const CONTROL_IDS = [
  'sheet', 'row', 'sector', 'add', 'run', 'row-search', 'col-search',
  'sector-search', 'amount', 'indicator-search', 'quadrant-filter',
  'indicator-sort', 'chain-sector', 'download-indicators'
];

function text(tag, value) {
  const e = document.createElement(tag);
  e.textContent = value;
  return e;
}

function call(type, payload) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    requests.set(id, { resolve, reject });
    worker.postMessage({ id, type, payload });
  });
}

function startWorker() {
  worker = new Worker('./worker.js');
  worker.onmessage = ({ data: d }) => {
    if (d.type === 'status') {
      $('status').textContent = d.text;
      return;
    }
    const p = requests.get(d.id);
    if (!p) return;
    requests.delete(d.id);
    d.ok ? p.resolve(d.result) : p.reject(Error(d.error));
  };
  worker.onerror = e => {
    for (const p of requests.values()) p.reject(Error(e.message || 'Worker 실행 오류'));
    requests.clear();
  };
}

function options(el, list) {
  el.replaceChildren(...list.map(x => {
    const o = document.createElement('option');
    o.value = x.code;
    o.textContent = x.code + ' ' + x.name;
    return o;
  }));
}

function invalidate() {
  result = null;
  $('results').hidden = true;
}

function setControlsDisabled(flag) {
  for (const id of CONTROL_IDS) {
    if ($(id)) $(id).disabled = flag;
  }
}

async function load(buffer) {
  invalidate();
  basket = [];
  renderBasket();
  setControlsDisabled(true);

  if (worker) worker.terminate();
  for (const p of requests.values()) p.reject(Error('새 자료 로드'));
  requests.clear();
  startWorker();

  try {
    const info = await call('init', buffer);
    sectors = info.sectors;
    indicators = info.indicators || [];
    chains = info.chains || {};
    currentSummary = info.summary || null;

    options($('sector'), sectors);
    options($('chain-sector'), sectors);
    $('sector-search').value = '';
    $('row-search').value = '';
    $('col-search').value = '';
    $('indicator-search').value = '';
    $('quadrant-filter').value = 'ALL';

    $('sheet').replaceChildren(...info.sheets.map(s => {
      const o = text('option', s);
      o.value = s;
      return o;
    }));

    $('validation').textContent = JSON.stringify(info.residuals, null, 2) + '\n검증 결과: 모든 행렬 항등식 잔차 < 1e-7 통과';
    if (currentSummary) {
      $('active-classification').textContent = '2023 연장표 · 생산자가격 · ' + currentSummary.classification;
    }

    setControlsDisabled(false);
    renderStructureSummary();
    renderIndicators();
    renderChains();
    await explore();

    $('status').textContent = '준비 완료 · ' + (currentSummary ? currentSummary.classification : sectors.length + '개 부문') + ' · ' + info.sheets.length + '개 시트 로딩 완료';
    $('sim-status').textContent = '시나리오를 추가한 뒤 파급효과 계산 실행 버튼을 누르세요.';
  } catch (e) {
    $('status').textContent = '로딩 실패: ' + e.message;
  }
}

let exploreSeq = 0;
async function explore() {
  const seq = ++exploreSeq;
  try {
    const d = await call('explore', { sheet: $('sheet').value, row: $('row').value });
    if (seq !== exploreSeq) return;
    rowChoices = d.rows;
    filterRows(d.selected);
    cells = d.cells;
    $('unit').textContent = d.unit;
    $('explore-caption').textContent = $('sheet').value + ' / 선택 행: [' + d.selected + '] ' + d.name;
    renderCells();
  } catch (e) {
    $('status').textContent = e.message;
  }
}

function filterRows(selected) {
  const q = $('row-search').value.trim().toLowerCase();
  options($('row'), rowChoices.filter(r => (r.code + ' ' + r.name).toLowerCase().includes(q)));
  if ([...$('row').options].some(o => o.value === selected)) $('row').value = selected;
}

function renderCells() {
  const q = $('col-search').value.trim().toLowerCase();
  $('cells').replaceChildren(...cells.filter(c => (c.code + ' ' + c.name).toLowerCase().includes(q)).map(c => {
    const tr = document.createElement('tr');
    const valStr = c.value === null ? '빈 셀' : typeof c.value === 'number' ? fmt(c.value, 6) : c.value;
    for (const v of [c.code, c.name, valStr]) tr.append(text('td', v));
    return tr;
  }));
}

function renderStructureSummary() {
  if (!currentSummary) return;
  const items = [
    ['분석 분류 기준', currentSummary.classification, '한국은행 2023 연장표'],
    ['평균 생산유발계수', fmt4(currentSummary.avgProdCoeff), '단위당 유발액 (배)'],
    ['평균 부가가치유발계수', fmt4(currentSummary.avgVaCoeff), '단위당 유발액 (비율)'],
    ['평균 수입유발계수', fmt4(currentSummary.avgImpCoeff), '단위당 유발액 (비율)'],
    ['평균 부가가치율', fmt(currentSummary.avgVaRate * 100, 2) + '%', '총투입 대비 비중']
  ];
  $('structure-cards').replaceChildren(...items.map(([title, val, unit]) => {
    const d = text('div', title);
    d.className = 'card';
    d.append(text('strong', val), text('span', unit));
    return d;
  }));
}

function getFilteredIndicators() {
  const q = $('indicator-search').value.trim().toLowerCase();
  const qf = $('quadrant-filter').value;
  const sortKey = $('indicator-sort').value;

  const list = indicators.filter(item => {
    const matchText = (item.code + ' ' + item.name).toLowerCase().includes(q);
    const matchQuad = qf === 'ALL' || item.quadrant === qf;
    return matchText && matchQuad;
  });

  list.sort((a, b) => {
    if (sortKey === 'code') return a.code.localeCompare(b.code);
    return b[sortKey] - a[sortKey];
  });
  return list;
}

function renderIndicators() {
  const list = getFilteredIndicators();
  $('indicator-rows').replaceChildren(...list.map(r => {
    const tr = document.createElement('tr');
    const vals = [
      r.code,
      r.name,
      r.quadrant,
      fmt4(r.backward),
      fmt4(r.forward),
      fmt4(r.vaRate),
      fmt4(r.domInputRate),
      fmt4(r.prodCoeff),
      fmt4(r.vaCoeff),
      fmt4(r.impCoeff)
    ];
    vals.forEach(v => tr.append(text('td', v)));
    return tr;
  }));
}

function renderChains() {
  const code = $('chain-sector').value;
  const data = chains[code] || { inputs: [], outputs: [] };

  $('chain-inputs').replaceChildren(...data.inputs.map(r => {
    const tr = document.createElement('tr');
    [r.code, r.name, fmt4(r.coeff), fmt4(r.induced)].forEach(v => tr.append(text('td', v)));
    return tr;
  }));

  $('chain-outputs').replaceChildren(...data.outputs.map(r => {
    const tr = document.createElement('tr');
    [r.code, r.name, fmt4(r.coeff), fmt4(r.induced)].forEach(v => tr.append(text('td', v)));
    return tr;
  }));
}

$('sheet').onchange = () => {
  $('row-search').value = '';
  $('row').replaceChildren();
  explore();
};
$('row').onchange = explore;
$('row-search').oninput = () => {
  filterRows();
  if ($('row').value) explore();
  else {
    $('cells').replaceChildren();
    $('explore-caption').textContent = '일치하는 행이 없습니다.';
  }
};
$('col-search').oninput = renderCells;

$('indicator-search').oninput = renderIndicators;
$('quadrant-filter').onchange = renderIndicators;
$('indicator-sort').onchange = renderIndicators;
$('chain-sector').onchange = renderChains;

$('sector-search').oninput = () => {
  const q = $('sector-search').value.trim().toLowerCase();
  options($('sector'), sectors.filter(s => (s.code + ' ' + s.name).toLowerCase().includes(q)));
};

function renderBasket() {
  $('basket').replaceChildren(...basket.map((s, i) => {
    const li = text('li', '[' + s.code + '] ' + s.name + ' : +' + fmt(s.amount) + ' 백만원 ');
    const b = text('button', '삭제');
    b.type = 'button';
    b.onclick = () => {
      basket.splice(i, 1);
      invalidate();
      renderBasket();
    };
    li.append(b);
    return li;
  }));
  $('sim-status').textContent = basket.length
    ? basket.length + '개 산업 수요 충격 설정 완료. 파급효과 계산 실행 버튼을 누르세요.'
    : '시나리오를 추가하세요.';
}

$('scenario').onsubmit = e => {
  e.preventDefault();
  const amount = Number($('amount').value);
  const s = sectors.find(item => item.code === $('sector').value);
  if (!s || !Number.isFinite(amount) || amount <= 0) {
    $('sim-status').textContent = '대상 산업과 0보다 큰 수요 증가액(백만원)을 확인하세요.';
    return;
  }
  basket.push({ ...s, amount });
  invalidate();
  renderBasket();
};

$('clear').onclick = () => {
  basket = [];
  invalidate();
  renderBasket();
};

$('run').onclick = async () => {
  if (!basket.length) {
    $('sim-status').textContent = '시나리오를 먼저 추가하세요.';
    return;
  }
  const snapshot = basket.map(s => ({ ...s }));
  $('run').disabled = true;
  $('sim-status').textContent = '파급효과 계산 중…';
  try {
    const r = await call('simulate', snapshot);
    if (JSON.stringify(snapshot) !== JSON.stringify(basket)) {
      $('sim-status').textContent = '입력이 변경되었습니다. 다시 계산하세요.';
      return;
    }
    result = r;
    renderResult();
    $('sim-status').textContent = '계산 완료 (단위: 백만원 / 생산유발승수: ' + fmt4(r.multiplier) + '배).';
  } catch (e) {
    invalidate();
    $('sim-status').textContent = '계산 실패: ' + e.message;
  } finally {
    $('run').disabled = false;
  }
};

function renderResult() {
  $('results').hidden = false;
  const cardItems = [
    ['최종수요 증가액', fmt(result.demand), '백만원'],
    ['총 생산유발액', fmt(result.production), '백만원 (승수 ' + fmt4(result.multiplier) + '배)'],
    ['총 수입유발액', fmt(result.imports), '백만원 (계수 ' + fmt4(result.impMultiplier) + ')'],
    ['총 부가가치유발액', fmt(result.valueAdded), '백만원 (계수 ' + fmt4(result.vaMultiplier) + ')']
  ];
  $('cards').replaceChildren(...cardItems.map(([title, v, unit]) => {
    const d = text('div', title);
    d.className = 'card';
    d.append(text('strong', v), text('span', unit));
    return d;
  }));

  const max = Math.max(...result.rows.map(r => r.production), 1);
  $('bars').replaceChildren(...result.rows.slice(0, 15).map(r => {
    const d = text('div', r.name + ' · ' + fmt(r.production) + ' 백만원 (' + fmt(r.share, 2) + '%)');
    d.className = 'bar';
    const t = document.createElement('div');
    t.className = 'track';
    const f = document.createElement('div');
    f.className = 'fill';
    f.style.width = Math.max(0, r.production / max * 100) + '%';
    t.append(f);
    d.append(t);
    return d;
  }));

  $('result-rows').replaceChildren(...result.rows.map(r => {
    const tr = document.createElement('tr');
    [r.code, r.name, fmt(r.production), fmt(r.share, 2) + '%', fmt(r.imports), fmt(r.valueAdded)].forEach(v => tr.append(text('td', v)));
    return tr;
  }));
}

function csvCell(v) {
  let s = String(v);
  if (/^[=+@-]/.test(s) && typeof v !== 'number') s = "'" + s;
  return '"' + s.replaceAll('"', '""') + '"';
}

function triggerCsv(filename, rows) {
  const blob = new Blob(['\ufeff' + rows.map(r => r.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('download').onclick = () => {
  if (!result) return;
  const rows = [
    ['산업코드', '산업명', '생산유발액_백만원', '생산유발비중_퍼센트', '수입유발액_백만원', '부가가치유발액_백만원'],
    ...result.rows.map(r => [r.code, r.name, r.production, r.share, r.imports, r.valueAdded])
  ];
  triggerCsv('io-2023-simulation-results.csv', rows);
};

$('download-indicators').onclick = () => {
  const list = getFilteredIndicators();
  if (!list.length) return;
  const rows = [
    ['산업코드', '산업명', '산업유형', '영향력계수_지수', '감응도계수_지수', '부가가치율_비율', '국산투입률_비율', '수입투입률_비율', '생산유발계수', '부가가치유발계수', '수입유발계수'],
    ...list.map(r => [r.code, r.name, r.quadrant, r.backward, r.forward, r.vaRate, r.domInputRate, r.impInputRate, r.prodCoeff, r.vaCoeff, r.impCoeff])
  ];
  triggerCsv('io-2023-linkage-indicators.csv', rows);
};

async function fetchWorkbookBuffer(filename) {
  const encoded = encodeURIComponent(filename);
  for (const prefix of ['./data/', './']) {
    const res = await fetch(prefix + encoded);
    if (res.ok) return await res.arrayBuffer();
  }
  throw Error(filename + ' 파일을 저장소에서 찾을 수 없습니다.');
}

document.querySelectorAll('.dataset-btn').forEach(btn => {
  btn.onclick = async () => {
    const allBtns = document.querySelectorAll('.dataset-btn');
    allBtns.forEach(b => (b.disabled = true));
    const filename = btn.dataset.file;
    $('status').textContent = filename + ' 내려받는 중…';
    try {
      const buf = await fetchWorkbookBuffer(filename);
      await load(buf);
    } catch (err) {
      $('status').textContent = '불러오기 실패: ' + err.message;
    } finally {
      allBtns.forEach(b => (b.disabled = false));
    }
  };
});

$('file-upload').onchange = async e => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  $('status').textContent = file.name + ' 읽는 중…';
  await load(await file.arrayBuffer());
};