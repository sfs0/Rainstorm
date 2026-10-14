import csv
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import parse_upload, analyse, make_advice, InputError, risk_level

SAMPLE = Path(__file__).resolve().parents[1] / 'example.csv'


def rows():
    return list(csv.DictReader(io.StringIO(SAMPLE.read_text(encoding='utf-8-sig'))))


def encode(items, fields=None):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields or list(items[0]))
    writer.writeheader()
    writer.writerows(items)
    return output.getvalue().encode('utf-8-sig')


class UploadTests(unittest.TestCase):
    def test_sample_scores_and_advice_match_current_method(self):
        groups, meta = parse_upload(SAMPLE.read_bytes())
        result = make_advice(analyse(groups, meta))
        self.assertEqual(meta['basin'], '长江')
        self.assertEqual(meta['record_count'], 72)
        self.assertEqual(meta['station_count'], 3)
        self.assertEqual({x['station_name']: x['risk_index'] for x in result['stations']},
                         {'万州': 22.5, '宜昌': 22.17, '南京': 9.33})
        self.assertEqual(result['overall']['risk_level'], '低风险')
        self.assertEqual(set(result['advice']), {'overview', 'public', 'traffic', 'water', 'emergency', 'uncertainty'})
        self.assertEqual(result['generation']['method'], 'rule')

    def test_basin_inferred_without_basin_column(self):
        data = rows()
        for row in data:
            row.pop('basin')
        self.assertEqual(parse_upload(encode(data))[1]['basin'], '长江')

    def test_canonical_and_legacy_station_id_columns(self):
        data = rows()
        for row in data:
            row['station_id'] = row['Station_Id_C']
        self.assertEqual(parse_upload(encode(data))[1]['record_count'], 72)

    def test_missing_column_reports_the_field(self):
        data = rows()
        for row in data: row.pop('PRE_3h')
        with self.assertRaisesRegex(InputError, 'PRE_3h'):
            parse_upload(encode(data))

    def test_duplicate_observation_rejected(self):
        data = rows()
        data.append(data[0].copy())
        with self.assertRaisesRegex(InputError, '重复观测'):
            parse_upload(encode(data))

    def test_gap_rejected(self):
        data = rows()
        data.pop(3)
        with self.assertRaisesRegex(InputError, '不连续'):
            parse_upload(encode(data))

    def test_non_numeric_and_negative_rain_rejected(self):
        for value in ['oops', '-1']:
            data = rows();data[0]['PRE_3h'] = value
            with self.assertRaises(InputError):parse_upload(encode(data))

    def test_missing_rain_rejected_but_missing_auxiliary_flagged(self):
        data = rows();data[0]['PRE_3h'] = ''
        with self.assertRaisesRegex(InputError, '降水缺测'):parse_upload(encode(data))
        data = rows();data[0]['PRS'] = ''
        self.assertTrue(parse_upload(encode(data))[1]['warnings'])

    def test_mixed_basins_rejected(self):
        data = rows();data[0]['basin'] = '黄河'
        with self.assertRaisesRegex(InputError, '多个流域'):parse_upload(encode(data))

    def test_unknown_basin_rejected(self):
        data = rows()
        for row in data:row['basin'] = '珠江'
        with self.assertRaisesRegex(InputError, '暂不支持'):parse_upload(encode(data))

    def test_unknown_station_needs_explicit_metadata(self):
        data = rows()
        for row in data:
            if row['station_name'] == '南京':row['Station_Id_C'] = 'TEST001'
        groups, meta = parse_upload(encode(data))
        self.assertTrue(meta['warnings'])
        self.assertIn('TEST001', groups)
        for row in data:
            if row['Station_Id_C'] == 'TEST001':row['station_name'] = ''
        with self.assertRaisesRegex(InputError, 'station_name'):parse_upload(encode(data))

    def test_wrong_reach_rejected(self):
        data = rows();data[0]['reach'] = '下游'
        with self.assertRaisesRegex(InputError, '河段'):parse_upload(encode(data))

    def test_short_window_rejected(self):
        data = rows()[:10]
        with self.assertRaisesRegex(InputError, '至少需要16'):parse_upload(encode(data))

    def test_risk_band_boundaries(self):
        self.assertEqual([risk_level(x) for x in [25, 25.01, 50, 50.01, 75, 75.01]],
                         ['低风险', '关注', '关注', '较高风险', '较高风险', '高风险'])

    def test_gbk_input(self):
        raw = SAMPLE.read_text(encoding='utf-8-sig').encode('gb18030')
        self.assertEqual(parse_upload(raw)[1]['basin'], '长江')


if __name__ == '__main__':
    unittest.main()
