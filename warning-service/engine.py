"""Evidence-based rainfall warning engine; compatible with Python 3.6.

Scoring mirrors 03_analyze_and_plot_innov.py. Upload validation adds explicit
checks for duplicate observations, continuous windows and a single basin.
"""
import csv
import io
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / 'station_catalog.json').read_text(encoding='utf-8'))
WEIGHTS = CATALOG['weights']
BY_ID = defaultdict(list)
for station in CATALOG['stations']:
    BY_ID[str(station['station_id'])].append(station)

ALIASES = {
    'station_id': 'Station_Id_C', '站号': 'Station_Id_C', '区站号': 'Station_Id_C',
    '时间': 'datetime', '观测时间': 'datetime', '流域': 'basin', '河流': 'basin',
    '站名': 'station_name', '河段': 'reach', '3小时降水': 'PRE_3h',
    '气压': 'PRS', '能见度': 'VIS', '最大风速': 'WIN_S_MAX', '天气编码': 'WEP_Now',
}
CORE = ['PRE_3h', 'PRS', 'VIS', 'WIN_S_MAX', 'WEP_Now']
NUMERIC = CORE + ['TEM', 'RHU', 'VAP', 'WIN_S_Avg_2mi']
REACH_ORDER = ['上游', '中游', '下游']


class InputError(ValueError):
    pass


def basin_name(value):
    value = str(value or '').strip().lower()
    if value in ['长江', '长江流域', 'yangtze']:
        return '长江'
    if value in ['黄河', '黄河流域', 'yellow']:
        return '黄河'
    return None


def number(value, field, line):
    if str(value or '').strip() in ['', 'nan', 'NaN', 'NA', 'null']:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise InputError('第{}行：{}必须是数值。'.format(line, field))
    if not math.isfinite(result) or result in [999998, 999999]:
        return None
    if field == 'PRE_3h' and result == 999990:
        return 0.0
    if field in ['PRE_3h', 'VIS', 'WIN_S_MAX'] and result < 0:
        raise InputError('第{}行：{}不能为负数。'.format(line, field))
    if field == 'WEP_Now' and (result != int(result) or not 0 <= result <= 999):
        raise InputError('第{}行：WEP_Now 应为天气现象整数编码。'.format(line))
    return result


def parse_time(row, line):
    text = str(row.get('datetime') or '').strip()
    if text:
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S',
                    '%Y/%m/%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y%m%d%H%M%S']:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
    elif all(str(row.get(k) or '').strip() for k in ['Year', 'Mon', 'Day', 'Hour']):
        try:
            return datetime(*[int(float(row[k])) for k in ['Year', 'Mon', 'Day', 'Hour']])
        except (ValueError, TypeError):
            pass
    raise InputError('第{}行：时间无效，请使用 YYYY-MM-DD HH:MM:SS。'.format(line))


def parse_upload(raw):
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise InputError('请上传非空 CSV，文件大小不超过10 MB。')
    text = None
    for encoding in ['utf-8-sig', 'gb18030']:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None or '\x00' in text:
        raise InputError('文件不是可读取的 CSV，请按示例格式保存。')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise InputError('CSV 缺少表头。')
    original_names = [str(x).strip() for x in reader.fieldnames]
    if len(original_names) != len(set(original_names)):
        raise InputError('CSV 存在重复列名。')
    names = [ALIASES.get(x, x) if ALIASES.get(x, x) not in original_names else x for x in original_names]
    if len(names) != len(set(names)):
        raise InputError('CSV 存在重复列名。')
    missing = [x for x in ['Station_Id_C'] + CORE if x not in names]
    if 'datetime' not in names and not all(x in names for x in ['Year', 'Mon', 'Day', 'Hour']):
        missing.append('datetime（或 Year、Mon、Day、Hour）')
    if missing:
        raise InputError('缺少必要字段：' + '、'.join(missing) + '。请下载示例 CSV 查看格式。')
    reader.fieldnames = names
    records = []
    declared = set()
    for line, row in enumerate(reader, 2):
        if len(records) >= 100000:
            raise InputError('CSV 最多支持100,000条观测记录。')
        if None in row:
            raise InputError('第{}行：列数与表头不一致。'.format(line))
        if not any(str(v or '').strip() for v in row.values()):
            continue
        station_id = str(row.get('Station_Id_C') or '').strip()
        if station_id.endswith('.0'):
            station_id = station_id[:-2]
        if not station_id:
            raise InputError('第{}行：站号为空。'.format(line))
        declaration = str(row.get('basin') or '').strip()
        if declaration:
            label = basin_name(declaration)
            if not label:
                raise InputError('第{}行：暂不支持流域“{}”，当前支持长江、黄河。'.format(line, declaration))
            declared.add(label)
        records.append({'station_id': station_id, 'datetime': parse_time(row, line),
                        'raw': row, 'line': line,
                        'values': {key: number(row.get(key), key, line) for key in NUMERIC}})
    if not records:
        raise InputError('CSV 没有有效观测记录。')
    if len(declared) > 1:
        raise InputError('文件包含多个流域，请将每个流域分别保存为一份 CSV。')
    possible = set(declared) if declared else set(WEIGHTS)
    if not declared:
        for station_id in set(x['station_id'] for x in records):
            if station_id in BY_ID:
                possible &= set(x['basin'] for x in BY_ID[station_id])
    if len(possible) != 1:
        raise InputError('站号无法唯一确定一个流域，请在 CSV 中增加 basin 列并填写长江或黄河。')
    basin = next(iter(possible))
    groups = defaultdict(list)
    keys = set()
    missing_aux = defaultdict(int)
    custom_ids = set()
    for record in records:
        row = record['raw']
        candidates = [x for x in BY_ID.get(record['station_id'], []) if x['basin'] == basin]
        if candidates:
            station = dict(candidates[0])
            if str(row.get('station_name') or '').strip():
                station['station_name'] = str(row['station_name']).strip()
        else:
            if not str(row.get('station_name') or '').strip() or str(row.get('reach') or '').strip() not in REACH_ORDER:
                raise InputError('第{}行：站号 {} 不在目录中，请在CSV补充 station_name 和 reach（上游/中游/下游）。'.format(record['line'], record['station_id']))
            station = {'station_id': record['station_id'], 'station_name': str(row['station_name']).strip(),
                       'basin': basin, 'reach': str(row['reach']).strip(), 'province': str(row.get('province') or '')}
            custom_ids.add(record['station_id'])
        if row.get('reach') and str(row['reach']).strip() != station['reach']:
            raise InputError('第{}行：站号 {} 的河段应为{}，与目录不一致。'.format(record['line'], record['station_id'], station['reach']))
        key = (record['station_id'], record['datetime'])
        if key in keys:
            raise InputError('第{}行：同一站点、同一时刻出现重复观测。'.format(record['line']))
        keys.add(key)
        if record['values']['PRE_3h'] is None:
            raise InputError('第{}行：降水缺测，无法可靠计算累计雨量。'.format(record['line']))
        for field in CORE[1:]:
            if record['values'][field] is None:
                missing_aux[field] += 1
        record['station'] = station
        groups[record['station_id']].append(record)
    endpoints = set()
    for station_id, rows in groups.items():
        rows.sort(key=lambda x: x['datetime'])
        if len(rows) < 16:
            raise InputError('站点 {} 只有{}条记录；至少需要16个连续3小时时次，示例提供24个。'.format(station_id, len(rows)))
        for previous, current in zip(rows, rows[1:]):
            if current['datetime'] - previous['datetime'] != timedelta(hours=3):
                raise InputError('站点 {} 在 {} 附近时间不连续；观测间隔应为3小时。'.format(station_id, current['datetime']))
        endpoints.add(rows[-1]['datetime'])
    if len(endpoints) != 1:
        raise InputError('不同站点的数据截至时间不一致，请上传同一观测时段的数据。')
    warnings = []
    if custom_ids:
        warnings.append('{}个站点使用CSV自带的站名与河段，未与内置目录核对。'.format(len(custom_ids)))
    if missing_aux:
        warnings.append('部分辅助要素缺测（{}）；缺测分量按现有方法不贡献分数，结果可能低估风险。'.format(
            '、'.join('{}:{}条'.format(k, v) for k, v in sorted(missing_aux.items()))))
    if any(len(x) < 24 for x in groups.values()):
        warnings.append('部分站点不足24个时次，72小时累计降水窗口不完整；48小时评分窗口已满足。')
    meta = {'basin': basin, 'station_count': len(groups), 'record_count': len(records),
            'start': min(x['datetime'] for x in records).strftime('%Y-%m-%d %H:%M:%S'),
            'end': max(endpoints).strftime('%Y-%m-%d %H:%M:%S'),
            'reach_counts': {r: sum(rows[0]['station']['reach'] == r for rows in groups.values()) for r in REACH_ORDER},
            'warnings': warnings, 'encoding': encoding,
            'inference': '流域字段与站点目录核对' if declared else '站号匹配流域目录'}
    return groups, meta


def bucket(value, thresholds, inverse=False):
    if value is None:
        return 0.0
    thresholds = sorted(thresholds)
    if inverse:
        for index, threshold in enumerate(thresholds):
            if value <= threshold:
                return (len(thresholds) - index) / len(thresholds)
        return 0.0
    return sum(value >= threshold for threshold in thresholds) / len(thresholds)


def weather(code):
    if code is None:
        return '未知', 0.0
    code = int(code)
    if 190 <= code <= 196: return '雷暴相关', 1.0
    if 180 <= code <= 184: return '阵性或间歇性降水', 0.8
    if 160 <= code <= 168: return '雨/雨夹雪', 0.6
    if 140 <= code <= 148: return '降水强度类', 0.7
    if 50 <= code <= 99: return '观测时有降水', 0.5
    if 10 <= code <= 12 or code in {28, 40, 41, 42, 43, 45, 47, 48, 130, 131, 132}: return '雾/低能见度', 0.6
    if 0 <= code <= 49: return '无降水类天气', 0.0
    return '其他', 0.2


def risk_level(value):
    if value <= 25: return '低风险'
    if value <= 50: return '关注'
    if value <= 75: return '较高风险'
    return '高风险'


def analyse(groups, meta):
    latest = []
    for station_id, observations in groups.items():
        current = observations[-1]
        values = current['values']
        precipitation = [x['values']['PRE_3h'] for x in observations]
        sums = {hours: sum(precipitation[-hours // 3:]) for hours in [3, 6, 12, 24, 48, 72]}
        previous_pressure = observations[-2]['values']['PRS']
        delta = None if values['PRS'] is None or previous_pressure is None else values['PRS'] - previous_pressure
        weather_class, weather_score = weather(values['WEP_Now'])
        components = {'p3': bucket(sums[3], [10, 20, 30, 50]),
                      'p24': bucket(sums[24], [10, 25, 50, 100]),
                      'p48': bucket(sums[48], [20, 50, 100, 150]),
                      'weather': weather_score, 'vis': bucket(values['VIS'], [500, 1000, 3000], True),
                      'wind': bucket(values['WIN_S_MAX'], [8, 10.8, 17.2]),
                      'prs': bucket(delta, [-4, -2, -1], True) if delta is not None and delta <= 0 else 0.0}
        station = current['station']
        weights = WEIGHTS[meta['basin']][station['reach']]
        risk = max(0.0, min(100.0, 100 * sum(weights[k] * components[k] for k in components)))
        reasons = []
        if sums[3] >= 30: reasons.append('近3小时降水强度偏大')
        elif sums[3] >= 10: reasons.append('近3小时降水明显')
        if sums[24] >= 50: reasons.append('24小时累计降水偏高')
        elif sums[24] >= 25: reasons.append('24小时累计降水较高')
        if sums[48] >= 80: reasons.append('48小时持续过程显著')
        if weather_class in ['雷暴相关', '阵性或间歇性降水']: reasons.append('存在' + weather_class + '天气')
        if values['VIS'] is not None and values['VIS'] <= 1000: reasons.append('能见度偏低')
        if values['WIN_S_MAX'] is not None and values['WIN_S_MAX'] >= 10.8: reasons.append('伴随偏强阵风')
        if delta is not None and delta <= -2: reasons.append('短时压降明显')
        entry = dict(station)
        entry.update(values)
        entry.update({'datetime': meta['end'], 'risk_index': round(risk, 2),
                      '_risk': risk, 'risk_level': risk_level(risk),
                      'weather_class': weather_class, 'trigger_reasons': reasons or ['降水及辅助要素整体处于一般水平']})
        entry.update({'precip_{}h'.format(hours): round(value, 2) for hours, value in sums.items()})
        latest.append(entry)
    latest.sort(key=lambda x: (-x['_risk'], x['station_id']))
    reaches = []
    for reach in REACH_ORDER:
        stations = [x for x in latest if x['reach'] == reach]
        if not stations:
            continue
        count = len(stations)
        maximum = max(x['_risk'] for x in stations)
        reaches.append({'basin': meta['basin'], 'reach': reach, 'station_count': count,
                        'max_risk_index': round(maximum, 2),
                        'avg_risk_index': round(sum(x['_risk'] for x in stations) / count, 2),
                        'risk_level': risk_level(maximum),
                        'high_risk_station_count': sum(x['_risk'] > 75 for x in stations),
                        'coherence_index': round(0.6 * sum(x['_risk'] >= 60 for x in stations) / count
                                                 + 0.4 * sum(x['precip_24h'] >= 25 for x in stations) / count, 4),
                        'max_precip_3h': max(x['precip_3h'] for x in stations),
                        'max_precip_24h': max(x['precip_24h'] for x in stations),
                        'max_precip_48h': max(x['precip_48h'] for x in stations)})
    maximum = latest[0]['_risk']
    for entry in latest:
        entry.pop('_risk', None)
    result = {'meta': meta, 'overall': {'risk_level': risk_level(maximum), 'max_risk_index': round(maximum, 2),
              'focus_station': latest[0]['station_name'], 'high_risk_station_count': sum(x['risk_level'] == '高风险' for x in latest)},
              'reaches': reaches, 'stations': latest, 'key_stations': latest[:15],
              'method': {'name': '复合风险指数与河段差异化权重',
                         'risk_bands': '≤25低风险；(25,50]关注；(50,75]较高风险；>75高风险',
                         'coherence': '0.6×风险指数≥60站点占比 + 0.4×24小时降水≥25mm站点占比',
                         'score_version': 'innov-20261014-current-rules'}}
    return result


def make_advice(result):
    meta = result['meta']
    overall = result['overall']
    stations = result['key_stations']
    top = stations[:3]
    names = '、'.join(x['station_name'] for x in top)
    rain24 = max(x['precip_24h'] for x in stations)
    low_vis = [x for x in result['stations'] if x['VIS'] is not None and x['VIS'] <= 1000]
    rain = [x for x in result['stations'] if x['precip_24h'] >= 25 or x['precip_3h'] >= 10]
    reach_text = '\n'.join('{}{}：{}，最高风险指数{}，24小时最大降水{} mm，区域协同性{}。'.format(
        meta['basin'], x['reach'], x['risk_level'], x['max_risk_index'], x['max_precip_24h'], x['coherence_index']) for x in result['reaches'])
    evidence = '\n'.join('{}（{}）：风险指数{}，3/24/48小时降水分别为{} / {} / {} mm；{}。'.format(
        x['station_name'], x['reach'], x['risk_index'], x['precip_3h'], x['precip_24h'], x['precip_48h'], '、'.join(x['trigger_reasons'])) for x in top)
    overview = '截至{}，{}上传站点的最高风险等级为“{}”，最高风险指数{}，重点关注{}。\n\n{}\n\n{}'.format(
        meta['end'], meta['basin'], overall['risk_level'], overall['max_risk_index'], names, reach_text, evidence)
    public = '关注{}及沿线地区的最新气象信息，根据当地正式预警安排出行。'.format(names)
    public += '观测存在较明显降水，建议避开积水路段、河岸和低洼地带。' if rain else '当前上传站点的降水指标整体不强，保持常规关注。'
    if low_vis:
        public += '部分站点能见度不超过1000米，出行注意减速并增加车距。'
    traffic = '根据上传站点的降水、能见度及风速进行道路巡查和运行监测。'
    traffic += '重点巡查{}附近的积水易发路段。'.format('、'.join(x['station_name'] for x in rain[:5])) if rain else '当前降水证据未显示大范围强降水，维持常规巡查。'
    if low_vis:
        traffic += '对{}附近路段加强低能见度提示；管制措施以现场情况和正式指令为准。'.format('、'.join(x['station_name'] for x in low_vis[:5]))
    water = '本次站点最大24小时累计降水为{} mm。结合上中下游汇总和持续降水情况，加密关注重点区域。'.format(max(x['precip_24h'] for x in result['stations']))
    water += '开展调度判断前应结合河道水位、流量、土壤含水量与水库工况；当前输入仅提供站点气象观测。'
    emergency = '重点关注{}的触发原因，核对低洼区域、易积水点和沿河风险点的现场情况。'.format(names)
    emergency += '上传站点中有{}个高风险站点（指数>75），建议按当地预案加强值守、联络与物资准备。'.format(overall['high_risk_station_count']) if overall['high_risk_station_count'] else '当前上传站点无指数>75的高风险站点，保持常规值守，动态关注后续变化。'
    uncertainty = '结果基于上传CSV中的历史/实况观测及固定规则，适用范围为本次上传的{}个站点；河段等级采用已上传站点的最大指数。尚未引入未来降水预报、实时水位或灾害实况。'.format(meta['station_count'])
    if meta['warnings']:
        uncertainty += '\n' + '\n'.join(meta['warnings'])
    result['advice'] = {'overview': overview, 'public': public, 'traffic': traffic, 'water': water,
                        'emergency': emergency, 'uncertainty': uncertainty}
    result['generation'] = {'method': 'rule', 'label': '基于观测证据的规则建议',
                            'validated': True, 'version': 'evidence-template-v1'}
    return result
