import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import analyse, parse_upload, make_advice
import qwen_advice as qwen

SAMPLE = Path(__file__).resolve().parents[1] / 'example.csv'
VALID = {field: '根据上传观测保持常规关注，核对现场情况，并以当地正式指令和最新信息安排相关工作。' for field in qwen.FIELDS}


class QwenTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'DASHSCOPE_API_KEY': '', 'QWEN_MODEL': 'qwen-max', 'QWEN_BASE_URL': qwen.DEFAULT_URL})
        self.env.start()
        self.addCleanup(self.env.stop)
        groups, meta = parse_upload(SAMPLE.read_bytes())
        self.result = analyse(groups, meta)

    def test_missing_key_uses_rule_without_call(self):
        with patch.object(qwen, 'call_model') as call:
            result = qwen.generate_advice(self.result)
        call.assert_not_called()
        self.assertEqual(result['generation']['method'], 'rule')
        self.assertFalse(qwen.public_settings()['model_configured'])

    def test_valid_model_advice_keeps_scores_and_evidence(self):
        os.environ['DASHSCOPE_API_KEY'] = 'unit-test-placeholder'
        original = copy.deepcopy(self.result)
        overview = make_advice(copy.deepcopy(original))['advice']['overview']
        with patch.object(qwen, 'call_model', return_value=json.dumps(VALID)):
            result = qwen.generate_advice(self.result)
        self.assertEqual(result['overall'], original['overall'])
        self.assertEqual(result['reaches'], original['reaches'])
        self.assertEqual(result['advice']['overview'], overview)
        self.assertEqual(result['generation']['model'], 'qwen-max')
        self.assertEqual(result['generation']['method'], 'qwen')

    def test_invalid_output_rewrites_once(self):
        os.environ['DASHSCOPE_API_KEY'] = 'unit-test-placeholder'
        with patch.object(qwen, 'call_model', side_effect=['not-json', json.dumps(VALID)]) as call:
            result = qwen.generate_advice(self.result)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result['generation']['method'], 'qwen')

    def test_repeated_invalid_output_falls_back(self):
        os.environ['DASHSCOPE_API_KEY'] = 'unit-test-placeholder'
        with patch.object(qwen, 'call_model', return_value='{}'):
            result = qwen.generate_advice(self.result)
        self.assertEqual(result['generation']['method'], 'rule')
        self.assertIn('reason', result['generation'])

    def test_invalid_evidence_is_rejected(self):
        for value in ['未来24小时降水100毫米，请保持关注并根据当地正式指令采取行动。',
                      '黄河沿岸当前出现强降水，请保持关注并根据当地正式指令采取行动。',
                      '预计会将出现暴雨，请保持关注并根据当地正式指令采取行动。',
                      '玉树附近应加强巡查，请保持关注并根据当地正式指令采取行动。']:
            bad = dict(VALID, public=value)
            with self.subTest(value=value), self.assertRaises(qwen.AdviceError):
                qwen.validate_advice(json.dumps(bad), self.result)

    def test_auth_failure_never_returns_remote_error_or_key(self):
        os.environ['DASHSCOPE_API_KEY'] = 'unit-test-placeholder'
        error = HTTPError(qwen.DEFAULT_URL, 401, 'private upstream content', {}, None)
        with patch.object(qwen, 'build_opener') as opener:
            opener.return_value.open.side_effect = error
            result = qwen.generate_advice(self.result)
        payload = json.dumps(result, ensure_ascii=False)
        self.assertIn('鉴权失败', payload)
        self.assertNotIn('private upstream content', payload)
        self.assertNotIn('unit-test-placeholder', payload)

    def test_request_uses_requested_model_and_bearer_auth(self):
        os.environ['DASHSCOPE_API_KEY'] = 'unit-test-placeholder'
        data = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(VALID)}}]}
        with patch.object(qwen, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode()
            qwen.call_model([{'role': 'system', 'content': 'test'}])
            request = opener.return_value.open.call_args[0][0]
        self.assertEqual(json.loads(request.data)['model'], 'qwen-max')
        self.assertEqual(request.full_url, qwen.DEFAULT_URL + '/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer unit-test-placeholder')

    def test_unapproved_endpoint_and_redirect_are_rejected(self):
        os.environ['QWEN_BASE_URL'] = 'https://example.com/v1'
        with self.assertRaises(qwen.AdviceError):
            qwen.call_model([])
        with self.assertRaises(qwen.AdviceError):
            qwen.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')


if __name__ == '__main__':
    unittest.main()
