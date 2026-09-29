import io
import json
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

import app as module


@pytest.fixture
def authenticated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'CALL_REPORTS_FILE', str(tmp_path / 'call_reports.json'))
    disaster_cases_file = tmp_path / 'disaster_cases.json'
    disaster_cases_file.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(module, 'DISASTER_CASES_FILE', str(disaster_cases_file))
    monkeypatch.setitem(module.app.config, 'TESTING', True)
    client = module.app.test_client()
    client.post('/login', data={'password': '123', 'next': '/call-reports'})
    return client


def api_token(client):
    return client.get('/api/call-reports').get_json()['csrf_token']


def test_authentication_and_registration_preserve_unknowns_and_transcript(authenticated_client):
    client = authenticated_client
    transcript = '[通報者] たぶん道路が冠水しているように見えます。\n[受付] 救助要請ですか。'
    token = api_token(client)

    response = client.post(
        '/api/call-reports',
        json={'元の文字起こし': transcript, '通報者による推測': ['たぶん冠水しているように見える']},
        headers={'X-CSRF-Token': token},
    )

    assert response.status_code == 201
    stored = json.loads(Path(module.CALL_REPORTS_FILE).read_text(encoding='utf-8'))[0]
    assert stored['元の文字起こし'] == transcript
    assert stored['通報日時'] == '不明'
    assert stored['場所']['市区町村'] == '不明'
    assert stored['緊急度'] == {'レベル': '要確認', '判定根拠': '判断材料不足'}
    assert stored['管理情報']['確認状態'] == '未確認'


def test_urgency_requires_a_basis_and_api_is_protected():
    with module.app.test_client() as client:
        assert client.get('/call-reports').status_code == 302
        assert client.get('/api/call-reports').status_code == 401
        client.post('/login', data={'password': '123', 'next': '/call-reports'})
        token = api_token(client)
        response = client.post(
            '/api/call-reports',
            json={'元の文字起こし': '通報者: 人がいるかもしれない', '緊急度': {'レベル': '高'}},
            headers={'X-CSRF-Token': token},
        )
        assert response.status_code == 400
        assert '判定根拠' in response.get_json()['error']


def test_dashboard_accepts_original_transcript_without_structuring_fields(authenticated_client):
    client = authenticated_client
    token = api_token(client)
    transcript = '[通報者] 原文のまま記録します。\r\n[受付] ありがとうございます。'

    response = client.post('/call-reports', data={'csrf_token': token, 'transcript': transcript})

    assert response.status_code == 302
    assert response.location.endswith('/operations/DR-001')
    stored = json.loads(Path(module.CALL_REPORTS_FILE).read_text(encoding='utf-8'))[0]
    operation = json.loads(Path(module.DISASTER_CASES_FILE).read_text(encoding='utf-8'))[0]
    assert stored['元の文字起こし'] == transcript
    assert stored['通報日時'] == '不明'
    assert stored['管理情報']['確認状態'] == '未確認'
    assert stored['管理情報']['災害対応ID'] == 'DR-001'
    assert operation['status'] == '未対応' and operation['priority'] == '要確認'
    assert transcript not in operation['details']
    intake_page = client.get('/call-reports').get_data(as_text=True)
    assert transcript not in intake_page and '総通報件数' not in intake_page


def test_txt_transcript_upload_takes_precedence_over_pasted_text(authenticated_client):
    client = authenticated_client
    token = api_token(client)
    uploaded_transcript = '通報者：青森市安方で道路が冠水しています。\n受付：場所を確認しました。'
    response = client.post('/call-reports', data={
        'csrf_token': token,
        'transcript': 'この貼り付け内容は使わない',
        'transcript_file': (io.BytesIO(uploaded_transcript.encode('utf-8')), '通話記録.txt', 'text/plain'),
    }, content_type='multipart/form-data')

    assert response.status_code == 302 and response.location.endswith('/operations/DR-001')
    saved = json.loads(Path(module.CALL_REPORTS_FILE).read_text(encoding='utf-8'))[0]
    operation = json.loads(Path(module.DISASTER_CASES_FILE).read_text(encoding='utf-8'))[0]
    assert saved['元の文字起こし'] == uploaded_transcript
    assert '安方' in operation['location'] and operation['risk'] == '道路・ライフライン'
    assert 'この貼り付け内容は使わない' not in saved['元の文字起こし']


def test_transcript_upload_rejects_non_txt_and_invalid_utf8(authenticated_client):
    client = authenticated_client
    for filename, contents, expected in (
        ('transcript.pdf', b'%PDF-1.4', '.txt'),
        ('transcript.txt', b'\xff\xfe\x00', 'UTF-8'),
    ):
        token = api_token(client)
        response = client.post('/call-reports', data={
            'csrf_token': token,
            'transcript_file': (io.BytesIO(contents), filename, 'text/plain'),
        }, content_type='multipart/form-data')
        assert response.status_code == 400
        assert expected in response.get_data(as_text=True)
    assert json.loads(Path(module.CALL_REPORTS_FILE).read_text(encoding='utf-8')) == []
    assert json.loads(Path(module.DISASTER_CASES_FILE).read_text(encoding='utf-8')) == []


def test_extraction_ignores_operator_questions_and_keeps_speculation_unconfirmed():
    transcript = (
        '受付：青森市安方で間違いないですか。\n'
        '通報者：青森市安方だと思います。道路に水があるように見えます。'
    )
    with module.app.test_request_context('/'):
        result, error = module.extract_call_transcript(transcript)

    assert error is None
    report = result['call_report']
    operation = result['operation']
    assert report['場所']['市区町村'] == '不明'
    assert report['確認された内容'] == []
    assert report['通報者による推測']
    assert operation['priority'] == '要確認'
    assert operation['location'] == '不明'


def test_related_calls_require_exact_location_and_share_only_common_confirmed_facts():
    first = {
        'system_id': 'TR-0001',
        '場所': {'市区町村': '青森市', '地区・町名': '安方', '詳細な場所': '不明', '目印・ランドマーク': '不明'},
        '災害': {'災害種別': '浸水'},
        '確認された内容': ['道路に水がある'],
    }
    second = {**first, 'system_id': 'TR-0002'}
    _, group_count = module.group_call_reports([dict(first), dict(second)])
    assert group_count == 0

    first['場所']['詳細な場所'] = second['場所']['詳細な場所'] = '安方1丁目2番地'
    second['確認された内容'] = ['道路に水がある', '車が停車している']
    grouped, group_count = module.group_call_reports([dict(first), dict(second)])
    assert group_count == 1
    assert grouped[0]['複数通報で確認'] == ['道路に水がある']
    json.dumps(grouped, ensure_ascii=False)


def test_review_update_and_uncertain_human_harm_metric(authenticated_client):
    client = authenticated_client
    token = api_token(client)
    payload = {
        '元の文字起こし': '[通報者] 負傷者がいる可能性があります。',
        '被害': {'人的被害': '負傷者がいる可能性'},
    }
    created = client.post('/api/call-reports', json=payload, headers={'X-CSRF-Token': token})
    assert created.status_code == 201
    system_id = created.get_json()['system_id']
    token = api_token(client)
    updated = client.patch(
        f'/api/call-reports/{system_id}/review',
        json={'確認状態': '確認済み'},
        headers={'X-CSRF-Token': token},
    )
    assert updated.status_code == 200
    dashboard = client.get('/api/call-reports').get_json()
    assert dashboard['stats']['human_harm'] == 0
    assert dashboard['stats']['unreviewed'] == 0


def test_dashboard_filters_related_calls_and_explicit_coordinate_map(authenticated_client):
    client = authenticated_client
    token = api_token(client)
    location = {
        '都道府県': '青森県',
        '市区町村': '青森市',
        '地区・町名': '安方',
        '詳細な場所': '安方1丁目2番地',
        '目印・ランドマーク': '駅前交差点',
    }
    first = {
        '通報日時': '2026-09-29T09:10+09:00',
        '場所': location,
        '災害': {'災害種別': '浸水'},
        '被害': {'人的被害': 'なし', '道路被害': '道路に浸水'},
        '救助要請': 'なし',
        '緊急度': {'レベル': '中', '判定根拠': '道路の浸水を直接確認したとの記録'},
        '確認された内容': ['交差点に水がある', '車両が停止している'],
        '短い要約': '交差点に水があるとの通報',
        '地図座標': {'緯度': 40.8222, '経度': 140.7474},
        '元の文字起こし': '[通報者] 交差点に水があります。',
    }
    second = {
        **first,
        '通報ID': 'CALL-2',
        '緊急度': {'レベル': '高', '判定根拠': '明示的な救助要請が記録されている'},
        '救助要請': 'あり',
        '被害': {'人的被害': '負傷者1人を確認'},
        '確認された内容': ['交差点に水がある', '負傷者1人を確認'],
        '元の文字起こし': '[通報者] 救助をお願いします。負傷者が1人います。',
    }
    for payload in (first, second):
        created = client.post('/api/call-reports', json=payload, headers={'X-CSRF-Token': token})
        assert created.status_code == 201

    dashboard = client.get('/api/call-reports').get_json()
    assert dashboard['related_group_count'] == 1
    assert dashboard['stats'] == {
        'total': 2, 'unreviewed': 2, 'urgent': 1, 'human_harm': 1, 'rescue': 1, 'related_groups': 1,
    }
    grouped_items = dashboard['items']
    assert all(len(item['関連通報']) == 2 for item in grouped_items)
    assert all(item['複数通報で確認'] == ['交差点に水がある'] for item in grouped_items)
    for filters in (
        {'hazard': '浸水'}, {'urgency': '高'}, {'area': '青森市 安方'},
        {'rescue': '1'}, {'unreviewed': '1'}, {'q': 'CALL-2'},
    ):
        assert client.get('/call-reports', query_string=filters).status_code == 200

    legacy_detail = client.get('/call-reports/TR-0001')
    assert legacy_detail.status_code == 302
    assert legacy_detail.location.endswith('/call-reports')