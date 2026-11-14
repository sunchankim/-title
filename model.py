import json, io
import numpy as np
import openpyxl

raw_bytes = None
book = {}
sheet_names = []
codes = []
names = []
L = None
M = None
V = None
valid = False

def emit(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False)

def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(',', '')
    if s in ('', '-', '—', '–', '.', 'N/A', 'nan', 'NaN'):
        return 0.0
    return float(s)

def norm_code(val):
    if val is None:
        return ''
    s = str(val).strip()
    if s.endswith('.0') and s[:-2].isdigit():
        s = s[:-2]
    return s

def code_key(s):
    s = norm_code(s)
    if s.isdigit():
        return str(int(s))
    return s

def is_sector_code(val):
    s = norm_code(val)
    if not s or s == '0' or '.' in s or s.startswith('-'):
        return False
    skip_words = ('코드', '부문', '상품', 'Code', '합계', '계', '단위', '표')
    if any(w in s for w in skip_words):
        return False
    if s.isdigit() and int(s) >= 9000:
        return False
    if len(s) > 10:
        return False
    return True

def get_sheet_rows(s):
    if s not in book:
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
        book[s] = list(wb[s].values)
        wb.close()
    return book[s]

def find_sheet(kind):
    names_clean = [(s, s.replace(' ', '')) for s in sheet_names]
    if kind == '국산투입계수':
        for s, sc in names_clean:
            if '국산투입계수' in sc:
                return s
    elif kind == '수입투입계수':
        for s, sc in names_clean:
            if '수입투입계수' in sc:
                return s
    elif kind == '총투입계수':
        for s, sc in names_clean:
            if '총투입계수' in sc:
                return s
        for s, sc in names_clean:
            if '투입계수' in sc and '국산' not in sc and '수입' not in sc:
                return s
    elif kind == '생산유발계수':
        for s, sc in names_clean:
            if '생산유발계수' in sc and '취업' not in sc and '고용' not in sc:
                return s
    elif kind == '수입유발계수':
        for s, sc in names_clean:
            if '수입유발계수' in sc:
                return s
    elif kind == '부가가치유발계수':
        for s, sc in names_clean:
            if '부가가치유발계수' in sc:
                return s
    raise ValueError(f"필수 시트({kind})를 찾을 수 없습니다. (현재 시트: {', '.join(sheet_names)})")

def detect_layout(rows):
    best_idx = 4
    best_count = -1
    limit = min(9, len(rows))
    for idx in range(limit):
        r = rows[idx]
        if not r or len(r) < 4:
            continue
        cnt = sum(1 for c in r[2:] if is_sector_code(c))
        if cnt > best_count:
            best_count = cnt
            best_idx = idx

    code_row = best_idx
    name_row = code_row + 1 if code_row + 1 < len(rows) else code_row
    data_start = name_row + 1
    for idx in range(code_row + 1, min(code_row + 6, len(rows))):
        r = rows[idx]
        if r and len(r) > 1 and is_sector_code(r[0]) and r[1] is not None:
            data_start = idx
            break
    return code_row, name_row, data_start

def initialize(raw):
    global raw_bytes, book, sheet_names, codes, names, L, M, V, valid
    raw_bytes = bytes(raw)
    book = {}

    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    sheet_names = list(wb.sheetnames)
    needed = [
        find_sheet('국산투입계수'),
        find_sheet('수입투입계수'),
        find_sheet('총투입계수'),
        find_sheet('생산유발계수'),
        find_sheet('수입유발계수'),
        find_sheet('부가가치유발계수')
    ]
    for s in set(needed):
        book[s] = list(wb[s].values)
    wb.close()

    base = get_sheet_rows(find_sheet('국산투입계수'))
    c_row, _, d_start = detect_layout(base)

    nm_by_key = {}
    code_by_key = {}
    for r in base[d_start:]:
        if r and len(r) > 1 and is_sector_code(r[0]) and r[1] is not None:
            c_str = norm_code(r[0])
            k = code_key(c_str)
            if k not in nm_by_key:
                nm_by_key[k] = str(r[1]).strip()
                code_by_key[k] = c_str

    codes = []
    keys = []
    seen = set()
    for c in base[c_row][2:]:
        if is_sector_code(c):
            k = code_key(c)
            if k in nm_by_key and k not in seen:
                keys.append(k)
                codes.append(code_by_key[k])
                seen.add(k)

    n = len(codes)
    if n == 0:
        raise ValueError('유효한 산업 부문 코드를 읽지 못했습니다.')
    names = [nm_by_key[k] for k in keys]

    def matrix(kind):
        s = find_sheet(kind)
        rows = get_sheet_rows(s)
        cr, _, ds = detect_layout(rows)
        ri = {}
        for i in range(ds, len(rows)):
            r = rows[i]
            if r and r[0] is not None:
                k = code_key(r[0])
                if k and k not in ri:
                    ri[k] = i
        ci = {}
        for i, c in enumerate(rows[cr]):
            if c is not None:
                k = code_key(c)
                if k and k not in ci:
                    ci[k] = i

        a = np.zeros((n, n), dtype=float)
        for idx_r, kr in enumerate(keys):
            if kr not in ri:
                raise ValueError(f"{s} 시트에서 행 코드({codes[idx_r]})를 찾을 수 없습니다.")
            row_vals = rows[ri[kr]]
            for idx_c, kc in enumerate(keys):
                if kc not in ci:
                    raise ValueError(f"{s} 시트에서 열 코드({codes[idx_c]})를 찾을 수 없습니다.")
                val = row_vals[ci[kc]] if ci[kc] < len(row_vals) else 0.0
                a[idx_r, idx_c] = to_float(val)
        if not np.isfinite(a).all():
            raise ValueError(s + ': 비수치 또는 결측 데이터')
        return a

    L = matrix('생산유발계수')
    M = matrix('수입유발계수')
    V = matrix('부가가치유발계수')
    ad = matrix('국산투입계수')
    am = matrix('수입투입계수')

    rows_A = get_sheet_rows(find_sheet('총투입계수'))
    cr_A, _, ds_A = detect_layout(rows_A)
    ci_A = {code_key(c): i for i, c in enumerate(rows_A[cr_A]) if c is not None}

    vr = next((r for r in rows_A[ds_A:] if r and norm_code(r[0]) in ('9690', '9600', '9700')), None)
    if vr is None:
        vr = next((
            r for r in rows_A[ds_A:]
            if r and len(r) > 1 and r[1] is not None
            and any(w in str(r[1]).replace(' ', '') for w in ('부가가치계', '부가가치합계', '부가가치총계'))
        ), None)
    if vr is None:
        raise ValueError('투입계수 시트에서 부가가치계 행을 찾을 수 없습니다.')

    v = np.array([
        0.0 if ci_A[k] >= len(vr) else to_float(vr[ci_A[k]])
        for k in keys
    ], dtype=float)

    residuals = {
        '생산유발잔차': float(np.max(np.abs((np.eye(n) - ad) @ L - np.eye(n)))),
        '수입유발잔차': float(np.max(np.abs(am @ L - M))),
        '부가가치유발잔차': float(np.max(np.abs(v[:, None] * L - V)))
    }
    valid = max(residuals.values()) < 5e-2
    if not valid:
        raise ValueError('계수 검증 실패: ' + str(residuals))

    col_sum_L = L.sum(axis=0)
    row_sum_L = L.sum(axis=1)
    mean_L = float(L.sum()) / n
    backward = col_sum_L / mean_L
    forward = row_sum_L / mean_L

    col_sum_V = V.sum(axis=0)
    col_sum_M = M.sum(axis=0)
    col_sum_Ad = ad.sum(axis=0)
    col_sum_Am = am.sum(axis=0)

    indicators = []
    chains = {}
    for j in range(n):
        b_val = float(backward[j])
        f_val = float(forward[j])
        if b_val >= 1.0 and f_val >= 1.0:
            q_type = '전·후방 고연쇄형'
        elif b_val >= 1.0 and f_val < 1.0:
            q_type = '후방연쇄 중심형'
        elif b_val < 1.0 and f_val >= 1.0:
            q_type = '전방연쇄 중심형'
        else:
            q_type = '독립·최종소비형'

        indicators.append({
            'code': codes[j],
            'name': names[j],
            'quadrant': q_type,
            'backward': b_val,
            'forward': f_val,
            'vaRate': float(v[j]),
            'domInputRate': float(col_sum_Ad[j]),
            'impInputRate': float(col_sum_Am[j]),
            'prodCoeff': float(col_sum_L[j]),
            'vaCoeff': float(col_sum_V[j]),
            'impCoeff': float(col_sum_M[j])
        })

        in_idx = np.argsort(ad[:, j])[::-1]
        top_in = [
            {'code': codes[i], 'name': names[i], 'coeff': float(ad[i, j]), 'induced': float(L[i, j])}
            for i in in_idx if ad[i, j] > 0
        ][:8]

        out_idx = np.argsort(ad[j, :])[::-1]
        top_out = [
            {'code': codes[k], 'name': names[k], 'coeff': float(ad[j, k]), 'induced': float(L[j, k])}
            for k in out_idx if ad[j, k] > 0
        ][:8]

        chains[codes[j]] = {'inputs': top_in, 'outputs': top_out}

    label_map = {33: '통합대분류 (33부문)', 83: '통합중분류 (83부문)', 165: '통합소분류 (165부문)', 380: '기본부문 (380부문)'}
    classification = label_map.get(n, f'사용자 분류 ({n}부문)')

    summary = {
        'sectorCount': n,
        'classification': classification,
        'avgProdCoeff': float(np.mean(col_sum_L)),
        'avgVaCoeff': float(np.mean(col_sum_V)),
        'avgImpCoeff': float(np.mean(col_sum_M)),
        'avgVaRate': float(np.mean(v))
    }

    return emit({
        'sectors': [{'code': c, 'name': nm_i} for c, nm_i in zip(codes, names)],
        'sheets': sheet_names,
        'residuals': residuals,
        'summary': summary,
        'indicators': indicators,
        'chains': chains
    })

def explore(sheet, rowcode):
    rows = get_sheet_rows(sheet)
    cr, nr, ds = detect_layout(rows)
    choices = [
        {'code': norm_code(r[0]), 'name': str(r[1]).strip()}
        for r in rows[ds:] if r and len(r) > 1 and r[0] is not None and r[1] is not None
    ]
    chosen = next((r for r in rows[ds:] if r and norm_code(r[0]) == rowcode), None)
    if chosen is None:
        chosen = next(r for r in rows[ds:] if r and len(r) > 1 and r[0] is not None and r[1] is not None)

    cells = []
    for i in range(2, len(rows[cr])):
        if rows[cr][i] is None:
            continue
        val = chosen[i] if i < len(chosen) else None
        if isinstance(val, (float, int)):
            val = float(val)
        elif val is not None:
            val = str(val)
        col_name = str(rows[nr][i]).strip() if (nr < len(rows) and i < len(rows[nr]) and rows[nr][i] is not None) else ''
        cells.append({'code': norm_code(rows[cr][i]), 'name': col_name, 'value': val})

    raw_unit = ''
    for u_idx in range(min(cr, len(rows))):
        if rows[u_idx] and rows[u_idx][0] is not None and '단위' in str(rows[u_idx][0]):
            raw_unit = str(rows[u_idx][0]).strip()
            break
    if '백만원' in raw_unit:
        unit_desc = '단위: 백만원 (금액표 — 구성비·유발계수 등 요약 행은 행 명칭의 단위를 우선 확인)'
    else:
        unit_desc = '단위: 무차원 계수 / 비율 (최종수요 1단위당 유발액 또는 총투입 대비 비중)'

    return emit({
        'rows': choices,
        'selected': norm_code(chosen[0]),
        'name': str(chosen[1]).strip(),
        'unit': unit_desc,
        'cells': cells
    })

def simulate(payload):
    if not valid:
        raise ValueError('검증된 데이터가 없습니다.')
    shocks = json.loads(payload)
    f = np.zeros(len(codes))
    for s in shocks:
        a = float(s['amount'])
        if not np.isfinite(a) or a < 0:
            raise ValueError('수요 증가액은 유한한 0 이상의 수여야 합니다.')
        f[codes.index(s['code'])] += a
    if not f.sum() > 0:
        raise ValueError('한 산업 이상의 양의 수요 증가액을 입력하세요.')

    x = L @ f
    m = M @ f
    v = V @ f
    tot_x = float(x.sum())
    result = [
        {
            'code': c,
            'name': nm_i,
            'production': float(a),
            'imports': float(b),
            'valueAdded': float(d),
            'share': float(a / tot_x * 100.0) if tot_x > 0 else 0.0
        }
        for c, nm_i, a, b, d in zip(codes, names, x, m, v)
    ]
    result.sort(key=lambda r: r['production'], reverse=True)
    return emit({
        'demand': float(f.sum()),
        'production': tot_x,
        'imports': float(m.sum()),
        'valueAdded': float(v.sum()),
        'multiplier': float(tot_x / f.sum()),
        'vaMultiplier': float(v.sum() / f.sum()),
        'impMultiplier': float(m.sum() / f.sum()),
        'rows': result
    })