import io
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from PIL import Image

import app as module


@pytest.fixture
def damage_client(tmp_path, monkeypatch):
    reports_file = tmp_path / 'damage_reports.json'
    reports_file.write_text('[]', encoding='utf-8')
    upload_dir = tmp_path / 'damage_uploads'
    monkeypatch.setattr(module, 'DAMAGE_REPORTS_FILE', str(reports_file))
    monkeypatch.setattr(module, 'DAMAGE_UPLOAD_DIR', str(upload_dir))
    monkeypatch.setitem(module.app.config, 'TESTING', True)
    return module.app.test_client()


def image_bytes(image_format):
    image_file = io.BytesIO()
    Image.new('RGB', (8, 6), 'red').save(image_file, format=image_format)
    return image_file.getvalue()


def csrf_from_board(client):
    html = client.get('/damage_reports/new').get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def csrf_from_admin_action(client, report_id, action):
    html = client.get('/board').get_data(as_text=True)
    form_pattern = rf'<form method="post" action="/damage_reports/{report_id}/{action}".*?</form>'
    form = re.search(form_pattern, html, re.DOTALL).group(0)
    return re.search(r'name="csrf_token" value="([^"]+)"', form).group(1)


def post_damage(client, image_name='scene.png', image_format='PNG', **overrides):
    values = {
        'type': 'flood',
        'latitude': '40.8222',
        'longitude': '140.7474',
        'content': '道路に水がたまっています。',
    }
    values.update(overrides)
    values['csrf_token'] = csrf_from_board(client)
    values['photo'] = (io.BytesIO(image_bytes(image_format)), image_name, 'application/octet-stream')
    return client.post('/damage_reports/new', data=values, content_type='multipart/form-data')


def admin_login(client):
    client.post('/login', data={'password': '123', 'next': '/board'})


def test_empty_board_renders_accessible_map_and_list_tabs(damage_client):
    response = damage_client.get('/board')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '0件' in html and '被害情報の投稿はまだありません。' in html
    assert 'role="tablist"' in html and 'aria-controls="damageMapPanel"' in html
    assert '衛星画像 © Esri' in html and 'Tiles &copy; Esri' in html


def test_navigation_is_collapsed_into_accessible_menu(damage_client):
    html = damage_client.get('/board').get_data(as_text=True)
    assert 'id="mainNavigation" aria-label="情報メニュー" hidden' in html
    assert 'aria-controls="mainNavigation" aria-expanded="false"' in html
    assert 'メニューを開く' in html
    assert 'event.key === \'Escape\'' in html
    assert "if (event.target.closest('a')) setMenuOpen(false)" in html


def test_verified_map_pin_uses_blue_style(damage_client):
    Path(module.DAMAGE_REPORTS_FILE).write_text(json.dumps([{
        'id': 501, 'type': 'fire', 'type_label': '火災', 'latitude': 40.8,
        'longitude': 140.7, 'verified': True, 'content': '確認済み',
    }], ensure_ascii=False), encoding='utf-8')

    html = damage_client.get('/board').get_data(as_text=True)

    assert 'damage-marker.is-verified { background: #2458a6; }' in html
    assert "report.verified ? ' is-verified' : ''" in html
    assert '"verified": true' in html


@pytest.mark.parametrize(('extension', 'image_format'), [
    ('.jpg', 'JPEG'), ('.jpeg', 'JPEG'), ('.png', 'PNG'), ('.gif', 'GIF'), ('.webp', 'WEBP'),
])
def test_image_formats_are_decoded_and_report_is_persisted(damage_client, extension, image_format):
    response = post_damage(damage_client, '現場写真' + extension, image_format)
    assert response.status_code == 302 and response.location.endswith('/board?posted=1')
    reports = json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8'))
    assert len(reports) == 1
    report = reports[0]
    assert report['type'] == 'flood' and report['type_label'] == '道路冠水'
    assert report['verified'] is False and report['latitude'] == 40.8222
    assert report['original_name'] == '現場写真' + extension
    assert Path(module.DAMAGE_UPLOAD_DIR, report['image']).is_file()
    html = damage_client.get('/board').get_data(as_text=True)
    assert '道路冠水' in html and '40.8222' in html and report['image'] in html
    assert damage_client.get('/damage_uploads/' + report['image']).status_code == 200


@pytest.mark.parametrize(('values', 'message'), [
    ({'type': 'unknown'}, '種類'),
    ({'latitude': ''}, '緯度'),
    ({'latitude': 'nan'}, '緯度'),
    ({'latitude': '90.1'}, '緯度'),
    ({'longitude': 'inf'}, '経度'),
    ({'longitude': '180.1'}, '経度'),
    ({'content': 'x' * 1001}, '1,000文字'),
])
def test_invalid_report_fields_are_rejected(damage_client, values, message):
    response = post_damage(damage_client, **values)
    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8')) == []


def test_missing_fake_and_oversized_photos_are_rejected(damage_client):
    token = csrf_from_board(damage_client)
    missing = damage_client.post('/damage_reports/new', data={
        'csrf_token': token, 'type': 'flood', 'latitude': '1', 'longitude': '2',
    })
    assert missing.status_code == 400 and '写真を1枚' in missing.get_data(as_text=True)

    fake = damage_client.post('/damage_reports/new', data={
        'csrf_token': token, 'type': 'flood', 'latitude': '1', 'longitude': '2',
        'photo': (io.BytesIO(b'not a real image'), 'fake.jpg', 'image/jpeg'),
    }, content_type='multipart/form-data')
    assert fake.status_code == 400 and '画像ファイルの内容' in fake.get_data(as_text=True)

    truncated = damage_client.post('/damage_reports/new', data={
        'csrf_token': token, 'type': 'flood', 'latitude': '1', 'longitude': '2',
        'photo': (io.BytesIO(b'\x89PNG\r\n\x1a\n'), 'truncated.png', 'image/png'),
    }, content_type='multipart/form-data')
    assert truncated.status_code == 400 and '画像ファイルの内容' in truncated.get_data(as_text=True)

    too_large = damage_client.post('/damage_reports/new', data={
        'csrf_token': token, 'type': 'flood', 'latitude': '1', 'longitude': '2',
        'photo': (io.BytesIO(b'x' * (8 * 1024 * 1024 + 1)), 'large.png', 'image/png'),
    }, content_type='multipart/form-data')
    assert too_large.status_code == 400 and '8MB以下' in too_large.get_data(as_text=True)


def test_admin_verification_and_delete_remove_only_managed_upload(damage_client, tmp_path):
    assert post_damage(damage_client).status_code == 302
    report = json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8'))[0]
    managed_image = Path(module.DAMAGE_UPLOAD_DIR, report['image'])
    outside_image = tmp_path / 'protected.jpg'
    outside_image.write_bytes(b'keep')
    admin_login(damage_client)
    token = csrf_from_admin_action(damage_client, report['id'], 'verification')

    changed = damage_client.post(f"/damage_reports/{report['id']}/verification", data={
        'csrf_token': token, 'verified': 'true',
    })
    assert changed.status_code == 302
    assert json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8'))[0]['verified'] is True
    invalid = damage_client.post(f"/damage_reports/{report['id']}/verification", data={
        'csrf_token': csrf_from_admin_action(damage_client, report['id'], 'verification'), 'verified': 'yes',
    })
    assert invalid.status_code == 302
    missing = damage_client.post('/damage_reports/999/verification', data={
        'csrf_token': csrf_from_admin_action(damage_client, report['id'], 'verification'), 'verified': 'true',
    })
    assert missing.status_code == 302

    reports_file = Path(module.DAMAGE_REPORTS_FILE)
    reports = json.loads(reports_file.read_text(encoding='utf-8'))
    reports.append({
        'id': 900, 'uploaded_image': True, 'image': str(outside_image),
        'latitude': 1, 'longitude': 2, 'content': 'unsafe legacy path',
    })
    reports_file.write_text(json.dumps(reports), encoding='utf-8')
    deleted = damage_client.post(f"/damage_reports/{report['id']}/delete", data={
        'csrf_token': csrf_from_admin_action(damage_client, report['id'], 'delete'),
    })
    assert deleted.status_code == 302
    remaining = json.loads(reports_file.read_text(encoding='utf-8'))
    assert [item['id'] for item in remaining] == [900]
    assert not managed_image.exists() and outside_image.read_bytes() == b'keep'


def test_delete_failure_restores_report_and_managed_image(damage_client, monkeypatch):
    assert post_damage(damage_client).status_code == 302
    report = json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8'))[0]
    image_path = Path(module.DAMAGE_UPLOAD_DIR, report['image'])
    admin_login(damage_client)
    token = csrf_from_admin_action(damage_client, report['id'], 'delete')
    original_remove = module.os.remove

    def fail_quarantine_remove(path):
        if Path(path).name.startswith('.delete-'):
            raise OSError('simulated image removal failure')
        original_remove(path)

    monkeypatch.setattr(module.os, 'remove', fail_quarantine_remove)
    response = damage_client.post(
        f"/damage_reports/{report['id']}/delete",
        data={'csrf_token': token},
    )

    assert response.status_code == 302
    assert len(json.loads(Path(module.DAMAGE_REPORTS_FILE).read_text(encoding='utf-8'))) == 1
    assert image_path.is_file()
    assert not list(Path(module.DAMAGE_UPLOAD_DIR).glob('.delete-*'))