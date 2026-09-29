from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory, flash, abort
from urllib.parse import urlparse, urljoin
from functools import wraps
from contextlib import contextmanager
from io import BytesIO
import fcntl
import json
import math
import os
import re
import secrets
import threading
import urllib.request
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from PIL import Image, UnidentifiedImageError

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森県"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

WEATHER_CODES = {
    0: "快晴",
    1: "晴れ",
    2: "一部くもり",
    3: "くもり",
    45: "霧",
    48: "霧氷",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    80: "にわか雨",
    81: "強いにわか雨",
    82: "激しいにわか雨",
    95: "雷雨",
    96: "ひょうを伴う雷雨",
    99: "強いひょうを伴う雷雨"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
DAMAGE_REPORTS_FILE = os.path.join(APP_DIR, 'data', 'damage_reports.json')
DAMAGE_UPLOAD_DIR = os.environ.get(
    'DAMAGE_UPLOAD_DIR', os.path.join(APP_DIR, 'data', 'damage_uploads')
)
DAMAGE_REPORTS_LOCK = threading.Lock()
DAMAGE_TYPES = {
    'flood': '道路冠水',
    'damage': '建物被害',
    'landslide': '土砂・倒木',
    'heavy_rain': '大雨',
    'slope_failure': '土砂崩れ',
    'fire': '火災',
    'river_flood': '河川氾濫',
    'other': 'その他',
}
DAMAGE_IMAGE_FORMATS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.gif': 'GIF', '.webp': 'WEBP'}
DAMAGE_IMAGE_LIMIT = 8 * 1024 * 1024
RECEIVED_MATERIALS_FILE = os.path.join(APP_DIR, 'data', 'received_materials.json')
DISASTER_CASES_FILE = os.environ.get(
    'DISASTER_CASES_FILE', os.path.join(APP_DIR, 'data', 'disaster_cases.json')
)
DISASTER_UPLOAD_DIR = os.environ.get(
    'DISASTER_UPLOAD_DIR', os.path.join(APP_DIR, 'data', 'disaster_uploads')
)
DISASTER_CASES_LOCK = threading.Lock()
DISASTER_PRIORITIES = ('緊急', '高', '中', '低')
DISASTER_RISKS = ('人命・救助', '避難・孤立', '道路・ライフライン', '建物被害', 'その他')
DISASTER_REPORTER_TYPES = ('住民', '消防団', '監視所', '地元企業', '観光施設', '行政機関', 'その他')
DISASTER_SOURCES = ('電話', 'チャット', '画像', '現地確認')
DISASTER_STATUSES = ('未対応', '対応中', '現地確認中', '完了')
DISASTER_UPLOAD_EXTENSIONS = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
DISASTER_UPLOAD_LIMIT = 5 * 1024 * 1024
CALL_REPORTS_FILE = os.environ.get(
    'CALL_REPORTS_FILE', os.path.join(APP_DIR, 'data', 'call_reports.json')
)
CALL_REPORTS_LOCK = threading.Lock()
CALL_REPORT_PAIR_LOCK = threading.Lock()
CALL_TRANSCRIPT_FILE_LIMIT = 256 * 1024
CALL_REPORT_UNKNOWN = '不明'
CALL_REPORT_PLACE_FIELDS = (
    '都道府県', '市区町村', '地区・町名', '詳細な場所', '目印・ランドマーク'
)
CALL_REPORT_DISASTER_FIELDS = ('災害種別', '災害内容', '発生・確認状況', '進行中')
CALL_REPORT_DAMAGE_FIELDS = (
    '人的被害', '人数', '建物被害', '道路被害', '車両被害', 'ライフライン被害', '水位・浸水深等'
)
CALL_REPORT_CALLER_FIELDS = ('現在地', '安全状況', '避難状況')
CALL_REPORT_URGENCY_LEVELS = ('高', '中', '要確認')
CALL_REPORT_REVIEW_STATES = ('未確認', '確認中', '確認済み')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
damage_reports = load_json(DAMAGE_REPORTS_FILE, [])
received_materials = load_json(RECEIVED_MATERIALS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)


def load_damage_reports():
    reports = load_json(DAMAGE_REPORTS_FILE, [])
    return [report for report in reports if isinstance(report, dict)] if isinstance(reports, list) else []


def read_damage_reports_for_write():
    if not os.path.exists(DAMAGE_REPORTS_FILE):
        return []
    with open(DAMAGE_REPORTS_FILE, encoding='utf-8') as report_file:
        reports = json.load(report_file)
    if not isinstance(reports, list) or any(not isinstance(item, dict) for item in reports):
        raise ValueError('被害情報JSONの形式が不正です。')
    return reports


def save_damage_reports(reports):
    temporary_path = f'{DAMAGE_REPORTS_FILE}.{uuid.uuid4().hex}.tmp'
    try:
        with open(temporary_path, 'w', encoding='utf-8') as report_file:
            json.dump(reports, report_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, DAMAGE_REPORTS_FILE)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


@contextmanager
def damage_reports_write_lock():
    os.makedirs(os.path.dirname(os.path.abspath(DAMAGE_REPORTS_FILE)), exist_ok=True)
    with DAMAGE_REPORTS_LOCK:
        with open(f'{DAMAGE_REPORTS_FILE}.lock', 'a', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def inspect_damage_image(filename, contents):
    safe_name = os.path.basename((filename or '').replace('\\', '/'))
    extension = os.path.splitext(safe_name)[1].lower()
    expected_format = DAMAGE_IMAGE_FORMATS.get(extension)
    if expected_format is None:
        return None, 'JPEG、PNG、GIF、WebP画像を選択してください。'
    if not contents or len(contents) > DAMAGE_IMAGE_LIMIT:
        return None, '写真は1枚8MB以下にしてください。'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(contents)) as image:
                if image.format != expected_format or image.width * image.height > 40000000:
                    return None, '写真の形式または画像サイズが対応範囲外です。'
                image.verify()
            with Image.open(BytesIO(contents)) as image:
                image.load()
    except (
        UnidentifiedImageError, OSError, ValueError, EOFError, SyntaxError,
        Image.DecompressionBombError, Image.DecompressionBombWarning,
    ):
        return None, '画像ファイルの内容を読み取れません。別の写真を選択してください。'
    return extension, None


def insert_damage_report(report_type, latitude_value, longitude_value, content, photo):
    if report_type not in DAMAGE_TYPES:
        return None, '被害の種類を選択してください。', 400
    try:
        latitude = float(latitude_value)
        longitude = float(longitude_value)
    except (TypeError, ValueError):
        return None, '緯度と経度を入力してください。', 400
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        return None, '緯度は-90〜90の数値で入力してください。', 400
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        return None, '経度は-180〜180の数値で入力してください。', 400
    if not isinstance(content, str) or len(content) > 1000:
        return None, '状況コメントは1,000文字以内で入力してください。', 400
    if photo is None or not getattr(photo, 'filename', ''):
        return None, '状況写真を1枚選択してください。', 400
    contents = photo.stream.read(DAMAGE_IMAGE_LIMIT + 1)
    extension, image_error = inspect_damage_image(photo.filename, contents)
    if image_error:
        return None, image_error, 400

    original_name = os.path.basename((photo.filename or '').replace('\\', '/'))
    original_name = re.sub(r'[\x00-\x1f\x7f]', '', original_name)[:255] or f'photo{extension}'
    report = {
        'id': None,
        'source': '住民投稿',
        'type': report_type,
        'type_label': DAMAGE_TYPES[report_type],
        'content': content.strip(),
        'location': f'{latitude:.6f}, {longitude:.6f}',
        'latitude': latitude,
        'longitude': longitude,
        'reported_at': datetime.now(JST).strftime('%Y年%m月%d日 %H:%M'),
        'verified': False,
        'image': f'{uuid.uuid4().hex}{extension}',
        'uploaded_image': True,
        'original_name': original_name,
    }
    saved_image = None
    try:
        os.makedirs(DAMAGE_UPLOAD_DIR, exist_ok=True)
        with damage_reports_write_lock():
            reports = read_damage_reports_for_write()
            existing_ids = [
                int(item['id']) for item in reports
                if isinstance(item.get('id'), int) or str(item.get('id', '')).isdigit()
            ]
            report['id'] = max(existing_ids, default=0) + 1
            saved_image = os.path.join(DAMAGE_UPLOAD_DIR, report['image'])
            with open(saved_image, 'wb') as image_file:
                image_file.write(contents)
            save_damage_reports(reports + [report])
    except (OSError, ValueError, json.JSONDecodeError):
        if saved_image and os.path.isfile(saved_image):
            os.remove(saved_image)
        return None, '被害情報を保存できませんでした。', 500
    return report, None, 201

def call_report_text(value, fallback=CALL_REPORT_UNKNOWN, limit=500):
    if value is None:
        return fallback
    text = str(value).strip()
    return text[:limit] if text else fallback


def call_report_lines(value):
    if isinstance(value, str):
        values = value.splitlines()
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def load_disaster_cases():
    cases = load_json(DISASTER_CASES_FILE, [])
    return [item for item in cases if isinstance(item, dict)] if isinstance(cases, list) else []


def normalized_disaster_case(case):
    normalized = dict(case) if isinstance(case, dict) else {}
    defaults = {
        'id': '不明', 'received_at': '', 'source': '電話', 'reporter_type': 'その他',
        'priority': '中', 'risk': 'その他', 'status': '未対応', 'title': '名称未設定',
        'location': '場所未設定', 'reporter': '匿名', 'details': '',
    }
    for key, value in defaults.items():
        normalized.setdefault(key, value)
    for key in ('messages', 'attachments', 'timeline'):
        if not isinstance(normalized.get(key), list):
            normalized[key] = []
    return normalized


def parse_disaster_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=JST) if parsed.tzinfo is None else parsed.astimezone(JST)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=JST)


def read_disaster_cases_for_write():
    if not os.path.exists(DISASTER_CASES_FILE):
        return []
    with open(DISASTER_CASES_FILE, encoding='utf-8') as data_file:
        cases = json.load(data_file)
    if not isinstance(cases, list) or any(not isinstance(item, dict) for item in cases):
        raise ValueError('災害対応データの形式が不正です。')
    return cases


def save_disaster_cases(cases):
    temporary_path = f'{DISASTER_CASES_FILE}.{uuid.uuid4().hex}.tmp'
    try:
        with open(temporary_path, 'w', encoding='utf-8') as data_file:
            json.dump(cases, data_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, DISASTER_CASES_FILE)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


@contextmanager
def disaster_case_write_lock():
    os.makedirs(os.path.dirname(os.path.abspath(DISASTER_CASES_FILE)), exist_ok=True)
    with DISASTER_CASES_LOCK:
        with open(f'{DISASTER_CASES_FILE}.lock', 'a', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_call_reports():
    reports = load_json(CALL_REPORTS_FILE, [])
    return [item for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []


def read_call_reports_for_write():
    if not os.path.exists(CALL_REPORTS_FILE):
        return []
    with open(CALL_REPORTS_FILE, encoding='utf-8') as data_file:
        reports = json.load(data_file)
    if not isinstance(reports, list) or any(not isinstance(item, dict) for item in reports):
        raise ValueError('通報記録の形式が不正です。')
    return reports


def save_call_reports(reports):
    temporary_path = f'{CALL_REPORTS_FILE}.{uuid.uuid4().hex}.tmp'
    try:
        with open(temporary_path, 'w', encoding='utf-8') as data_file:
            json.dump(reports, data_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, CALL_REPORTS_FILE)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


@contextmanager
def call_reports_write_lock():
    os.makedirs(os.path.dirname(os.path.abspath(CALL_REPORTS_FILE)), exist_ok=True)
    with CALL_REPORTS_LOCK:
        with open(f'{CALL_REPORTS_FILE}.lock', 'a', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def disaster_csrf_token():
    if 'disaster_csrf_token' not in session:
        session['disaster_csrf_token'] = secrets.token_urlsafe(32)
    return session['disaster_csrf_token']


def normalized_call_report(report):
    normalized = dict(report) if isinstance(report, dict) else {}
    nested_defaults = {
        '場所': CALL_REPORT_PLACE_FIELDS,
        '災害': CALL_REPORT_DISASTER_FIELDS,
        '被害': CALL_REPORT_DAMAGE_FIELDS,
        '通報者': CALL_REPORT_CALLER_FIELDS,
    }
    for key, fields in nested_defaults.items():
        source = normalized.get(key) if isinstance(normalized.get(key), dict) else {}
        normalized[key] = {field: call_report_text(source.get(field)) for field in fields}
    urgency = normalized.get('緊急度') if isinstance(normalized.get('緊急度'), dict) else {}
    normalized['緊急度'] = {
        'レベル': urgency.get('レベル') if urgency.get('レベル') in CALL_REPORT_URGENCY_LEVELS else '要確認',
        '判定根拠': call_report_text(urgency.get('判定根拠'), '判断材料不足', 1000),
    }
    management = normalized.get('管理情報') if isinstance(normalized.get('管理情報'), dict) else {}
    normalized['管理情報'] = {
        **management,
        '登録日時': call_report_text(management.get('登録日時')),
        '確認状態': management.get('確認状態') if management.get('確認状態') in CALL_REPORT_REVIEW_STATES else '未確認',
    }
    normalized['system_id'] = call_report_text(normalized.get('system_id'))
    normalized['通報ID'] = call_report_text(normalized.get('通報ID'))
    normalized['通報日時'] = call_report_text(normalized.get('通報日時'))
    normalized['救助要請'] = normalized.get('救助要請') if normalized.get('救助要請') in ('あり', 'なし') else CALL_REPORT_UNKNOWN
    normalized['確認された内容'] = call_report_lines(normalized.get('確認された内容'))
    normalized['通報者による推測'] = call_report_lines(normalized.get('通報者による推測'))
    normalized['短い要約'] = call_report_text(normalized.get('短い要約'), '', 500)
    coordinates = normalized.get('地図座標') if isinstance(normalized.get('地図座標'), dict) else {}
    normalized['地図座標'] = {
        '緯度': coordinates.get('緯度', CALL_REPORT_UNKNOWN),
        '経度': coordinates.get('経度', CALL_REPORT_UNKNOWN),
    }
    normalized['元の文字起こし'] = normalized.get('元の文字起こし') if isinstance(normalized.get('元の文字起こし'), str) else ''
    return normalized


def call_report_form_payload(form):
    return {
        '通報ID': form.get('report_id'),
        '通報日時': form.get('report_datetime'),
        '場所': {field: form.get(f'place_{index}') for index, field in enumerate(CALL_REPORT_PLACE_FIELDS)},
        '災害': {field: form.get(f'disaster_{index}') for index, field in enumerate(CALL_REPORT_DISASTER_FIELDS)},
        '被害': {field: form.get(f'damage_{index}') for index, field in enumerate(CALL_REPORT_DAMAGE_FIELDS)},
        '通報者': {field: form.get(f'caller_{index}') for index, field in enumerate(CALL_REPORT_CALLER_FIELDS)},
        '救助要請': form.get('rescue_request'),
        '緊急度': {'レベル': form.get('urgency_level'), '判定根拠': form.get('urgency_basis')},
        '確認された内容': form.get('confirmed_facts', '').splitlines(),
        '通報者による推測': form.get('caller_speculation', '').splitlines(),
        '短い要約': form.get('short_summary'),
        '地図座標': {'緯度': form.get('latitude'), '経度': form.get('longitude')},
        '元の文字起こし': form.get('transcript', ''),
    }


def validate_call_report(payload):
    if not isinstance(payload, dict):
        return None, '通報データの形式が正しくありません。'
    transcript = payload.get('元の文字起こし')
    if not isinstance(transcript, str) or not transcript.strip():
        return None, '元の文字起こしを入力してください。'
    if len(transcript) > 50000:
        return None, '文字起こしは50,000文字以内で入力してください。'

    urgency_input = payload.get('緊急度') if isinstance(payload.get('緊急度'), dict) else {}
    urgency_level = urgency_input.get('レベル') or '要確認'
    urgency_basis = call_report_text(urgency_input.get('判定根拠'), '判断材料不足', 1000)
    if urgency_level not in CALL_REPORT_URGENCY_LEVELS:
        return None, '緊急度は「高」「中」「要確認」から選択してください。'
    if urgency_level in ('高', '中') and urgency_basis == '判断材料不足':
        return None, '緊急度を「高」「中」とする場合は、文字起こしに基づく判定根拠を入力してください。'

    place = payload.get('場所') if isinstance(payload.get('場所'), dict) else {}
    disaster = payload.get('災害') if isinstance(payload.get('災害'), dict) else {}
    damage = payload.get('被害') if isinstance(payload.get('被害'), dict) else {}
    caller = payload.get('通報者') if isinstance(payload.get('通報者'), dict) else {}
    coordinates = payload.get('地図座標') if isinstance(payload.get('地図座標'), dict) else {}
    latitude = coordinates.get('緯度', CALL_REPORT_UNKNOWN)
    longitude = coordinates.get('経度', CALL_REPORT_UNKNOWN)
    if latitude not in (None, '', CALL_REPORT_UNKNOWN) or longitude not in (None, '', CALL_REPORT_UNKNOWN):
        try:
            latitude, longitude = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return None, '地図座標は緯度・経度の両方を数値で入力してください。'
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None, '地図座標が有効な範囲外です。'
    else:
        latitude = longitude = CALL_REPORT_UNKNOWN

    return {
        'system_id': '',
        '通報ID': call_report_text(payload.get('通報ID'), CALL_REPORT_UNKNOWN, 120),
        '通報日時': call_report_text(payload.get('通報日時'), CALL_REPORT_UNKNOWN, 120),
        '場所': {field: call_report_text(place.get(field), limit=240) for field in CALL_REPORT_PLACE_FIELDS},
        '災害': {field: call_report_text(disaster.get(field), limit=500) for field in CALL_REPORT_DISASTER_FIELDS},
        '被害': {field: call_report_text(damage.get(field), limit=500) for field in CALL_REPORT_DAMAGE_FIELDS},
        '通報者': {field: call_report_text(caller.get(field), limit=500) for field in CALL_REPORT_CALLER_FIELDS},
        '救助要請': payload.get('救助要請') if payload.get('救助要請') in ('あり', 'なし', CALL_REPORT_UNKNOWN) else CALL_REPORT_UNKNOWN,
        '緊急度': {'レベル': urgency_level, '判定根拠': urgency_basis},
        '確認された内容': call_report_lines(payload.get('確認された内容')),
        '通報者による推測': call_report_lines(payload.get('通報者による推測')),
        '短い要約': call_report_text(payload.get('短い要約'), '', 500),
        '地図座標': {'緯度': latitude, '経度': longitude},
        '元の文字起こし': transcript,
        '管理情報': {
            '登録日時': datetime.now(JST).isoformat(timespec='seconds'),
            '確認状態': '未確認',
            '登録者': str(session.get('username', 'api'))[:120],
        },
    }, None


def extract_transcript_speakers(transcript):
    caller_turns = []
    operator_turns = []
    active_turns = None
    caller_pattern = re.compile(r'^\s*[\[【(]?\s*(通報者|住民|発信者|caller|reporter)\s*[\]】)]?\s*[:：]\s*(.*)$', re.IGNORECASE)
    operator_pattern = re.compile(r'^\s*[\[【(]?\s*(受付担当|受付|オペレーター|職員|operator|dispatcher)\s*[\]】)]?\s*[:：]\s*(.*)$', re.IGNORECASE)
    for line in transcript.splitlines():
        caller_match = caller_pattern.match(line)
        if caller_match:
            active_turns = caller_turns
            caller_turns.append(caller_match.group(2).strip())
            continue
        operator_match = operator_pattern.match(line)
        if operator_match:
            active_turns = operator_turns
            operator_turns.append(operator_match.group(2).strip())
            continue
        if active_turns is not None and line.strip():
            active_turns.append(line.strip())
    return caller_turns, operator_turns


def extract_transcript_facts(caller_turns):
    uncertain_markers = (
        'かもしれ', 'たぶん', 'と思う', '思います', 'ように見える', 'らしい', '可能性',
        '疑い', '見込み', '分からない', 'わからない', '不明', '正確には', 'かどうか',
    )
    confirmed = []
    speculation = []
    for turn in caller_turns:
        for sentence in re.split(r'(?<=[。！？!?])\s*', turn):
            sentence = sentence.strip()
            if len(sentence) < 3 or sentence in ('はい。', 'はい', '分かりました。', 'ありがとうございます。'):
                continue
            target = speculation if any(marker in sentence for marker in uncertain_markers) else confirmed
            if sentence not in target:
                target.append(sentence)
    return confirmed, speculation


def extract_transcript_location(confirmed_sentences):
    confirmed_text = ' '.join(confirmed_sentences)
    municipality_match = re.search(r'([\u4e00-\u9fff々ぁ-んァ-ヶー]{1,12}(?:市|区|町|村))', confirmed_text)
    municipality = municipality_match.group(1) if municipality_match else CALL_REPORT_UNKNOWN
    district = CALL_REPORT_UNKNOWN
    if municipality_match:
        tail = re.sub(r'^\s*の?', '', confirmed_text[municipality_match.end():])
        district_match = re.match(r'([\u4e00-\u9fff々ぁ-んァ-ヶー0-9\-ー]{1,16})', tail)
        if district_match:
            candidate = re.split(r'(?:です|でした|から|まで|付近|周辺|地区|地域|丁目|番地|に|で|、|。|\s)', district_match.group(1))[0]
            if candidate:
                district = candidate
    landmark_match = re.search(r'([\u4e00-\u9fff々ぁ-んァ-ヶー0-9\-ー]{1,16}(?:駅|橋|交差点|学校|病院|公園))', confirmed_text)
    landmark = landmark_match.group(1) if landmark_match else CALL_REPORT_UNKNOWN
    location_parts = [part for part in (municipality, district) if part != CALL_REPORT_UNKNOWN]
    location = ' '.join(location_parts) if location_parts else CALL_REPORT_UNKNOWN
    if landmark != CALL_REPORT_UNKNOWN and landmark not in location:
        location = f'{location}（{landmark}）' if location != CALL_REPORT_UNKNOWN else landmark
    return {
        '都道府県': CALL_REPORT_UNKNOWN,
        '市区町村': municipality,
        '地区・町名': district,
        '詳細な場所': CALL_REPORT_UNKNOWN,
        '目印・ランドマーク': landmark,
    }, location


def extract_call_transcript(transcript):
    caller_turns, operator_turns = extract_transcript_speakers(transcript)
    confirmed, speculation = extract_transcript_facts(caller_turns)
    confirmed_text = ' '.join(confirmed)
    fact_text = confirmed_text.casefold()

    hazard_rules = (
        ('津波', ('津波',)),
        ('河川氾濫', ('河川氾濫', '氾濫', '川があふ', '川からあふ')),
        ('土砂崩れ', ('土砂崩れ', '土砂崩落', '斜面崩落', '地滑り')),
        ('土砂・倒木', ('倒木',)),
        ('火災', ('火災', '火事', '燃えています', '火が出')),
        ('大雨', ('大雨', '豪雨')),
        ('地震', ('地震', '揺れました', '揺れています')),
        ('浸水', ('浸水', '冠水', '水につか', '水が道路まで')),
    )
    hazard = CALL_REPORT_UNKNOWN
    for label, terms in hazard_rules:
        if any(term in fact_text for term in terms):
            hazard = label
            break

    rescue_terms = ('救助をお願いします', '救助してください', '救助を要請', '助けてください', '助けをお願いします', '助けが必要')
    rescue_denial_terms = ('救助は必要ありません', '助けは必要ありません', '救助の必要はありません')
    rescue_request = 'あり' if any(term in fact_text for term in rescue_terms) else (
        'なし' if any(term in fact_text for term in rescue_denial_terms) else CALL_REPORT_UNKNOWN
    )
    human_harm_terms = ('負傷者', 'けが人', '怪我人', '負傷しました', 'けがをしました', '怪我をしました', '出血しています')
    human_harm = any(term in fact_text for term in human_harm_terms)

    damage_labels = []
    if any(term in fact_text for term in ('道路', '車道', '歩道')) and any(term in fact_text for term in ('水', '冠水', '浸水', '通行でき', '通れ')):
        damage_labels.append('道路浸水')
    if any(term in fact_text for term in ('車', '車両')) and any(term in fact_text for term in ('動けなく', '立ち往生', '停止')):
        damage_labels.append('車両停止')
    if '倒木' in fact_text:
        damage_labels.append('倒木')
    if any(term in fact_text for term in ('建物が壊', '建物が崩', '屋根が', '壁が崩', '家屋が')):
        damage_labels.append('建物被害')
    if any(term in fact_text for term in ('停電', '断水', 'ガスが止')):
        damage_labels.append('ライフライン被害')

    if rescue_request == 'あり' or (hazard == '津波' and any(term in fact_text for term in ('来てい', '入って', '流れて', '到達'))):
        priority = '緊急'
        priority_basis = '通報者の直接発言に明示的な救助要請、または現在進行中の津波情報があります。'
    elif human_harm:
        priority = '高'
        priority_basis = '通報者の直接発言に人的被害を示す内容があります。'
    elif damage_labels:
        priority = '中'
        priority_basis = '通報者の直接発言に道路・車両・建物等の被害情報があります。'
    else:
        priority = '要確認'
        priority_basis = '直接確認できる災害/被害の分類が不足しています。'

    if rescue_request == 'あり' or human_harm:
        risk = '人命・救助'
    elif any(term in fact_text for term in ('避難', '孤立', '取り残')):
        risk = '避難・孤立'
    elif damage_labels and any(label in damage_labels for label in ('道路浸水', '車両停止', 'ライフライン被害')):
        risk = '道路・ライフライン'
    elif '建物被害' in damage_labels:
        risk = '建物被害'
    else:
        risk = 'その他'

    place, location = extract_transcript_location(confirmed)
    title_parts = []
    if hazard != CALL_REPORT_UNKNOWN:
        title_parts.append(hazard)
    title_parts.extend(label for label in damage_labels if label not in title_parts)
    title = '・'.join(title_parts[:3]) + 'の通報' if title_parts else '災害通報（内容要確認）'
    summary = '、'.join(title_parts[:3]) if title_parts else '通報内容の分類は要確認'
    if speculation:
        summary += '（推測表現は未確認）'

    reporter_type = 'その他'
    for label in ('消防団', '監視所', '地元企業', '観光施設', '行政機関', '住民'):
        if any(label in turn for turn in caller_turns):
            reporter_type = label
            break
    current_location = CALL_REPORT_UNKNOWN
    for sentence in confirmed:
        if any(term in sentence for term in ('今は', '現在', 'います', 'にいる')) and any(term in sentence for term in ('建物', '階', '屋内', '屋外', '場所')):
            current_location = sentence
            break
    human_value = next((sentence for sentence in confirmed if any(term in sentence for term in human_harm_terms)), CALL_REPORT_UNKNOWN)
    vehicle_value = next((sentence for sentence in confirmed if '車' in sentence and any(term in sentence for term in ('動けなく', '立ち往生', '停止'))), CALL_REPORT_UNKNOWN)
    road_value = next((sentence for sentence in confirmed if '道路' in sentence and any(term in sentence for term in ('水', '冠水', '浸水', '通行'))), CALL_REPORT_UNKNOWN)
    hazard_state = '進行中' if any(term in fact_text for term in ('現在も', 'まだ', '流れてきて', '入ってきて')) else CALL_REPORT_UNKNOWN

    call_payload = {
        '元の文字起こし': transcript,
        '場所': place,
        '災害': {
            '災害種別': hazard,
            '災害内容': '、'.join(title_parts) if title_parts else CALL_REPORT_UNKNOWN,
            '発生・確認状況': '通報者の直接発言から抽出' if confirmed else CALL_REPORT_UNKNOWN,
            '進行中': hazard_state,
        },
        '被害': {
            '人的被害': human_value,
            '人数': CALL_REPORT_UNKNOWN,
            '建物被害': '建物被害の申告あり' if '建物被害' in damage_labels else CALL_REPORT_UNKNOWN,
            '道路被害': road_value,
            '車両被害': vehicle_value,
            'ライフライン被害': 'ライフライン被害の申告あり' if 'ライフライン被害' in damage_labels else CALL_REPORT_UNKNOWN,
            '水位・浸水深等': CALL_REPORT_UNKNOWN,
        },
        '通報者': {
            '現在地': current_location if current_location != CALL_REPORT_UNKNOWN else location,
            '安全状況': CALL_REPORT_UNKNOWN,
            '避難状況': next((sentence for sentence in confirmed if '避難' in sentence or '逃げました' in sentence), CALL_REPORT_UNKNOWN),
        },
        '救助要請': rescue_request,
        '緊急度': {
            'レベル': '高' if priority == '緊急' else priority if priority in ('高', '中') else '要確認',
            '判定根拠': priority_basis,
        },
        '確認された内容': confirmed,
        '通報者による推測': speculation,
        '短い要約': summary,
    }
    extracted, error = validate_call_report(call_payload)
    if error:
        return None, error
    return {
        'call_report': extracted,
        'operation': {
            'source': '電話' if caller_turns and operator_turns else '要確認',
            'reporter_type': reporter_type,
            'priority': priority,
            'risk': risk,
            'status': '未対応',
            'title': title,
            'location': location,
            'reporter': '匿名',
            'details': f'文字起こしからの一次抽出: {summary}。重要度根拠: {priority_basis}',
            'messages': [],
            'attachments': [],
            'timeline': [],
        },
    }, None


def read_disaster_cases_for_write():
    if not os.path.exists(DISASTER_CASES_FILE):
        return []
    with open(DISASTER_CASES_FILE, encoding='utf-8') as cases_file:
        cases = json.load(cases_file)
    if not isinstance(cases, list) or any(not isinstance(item, dict) for item in cases):
        raise ValueError('災害対応JSONの形式が不正です。')
    return cases


def get_submitted_call_transcript(form, files):
    uploaded_file = files.get('transcript_file')
    if uploaded_file and uploaded_file.filename:
        filename = os.path.basename(uploaded_file.filename.replace('\\', '/'))
        if os.path.splitext(filename)[1].lower() != '.txt':
            return None, '添付できる文字起こしファイルはUTF-8形式の.txtのみです。'
        contents = uploaded_file.stream.read(CALL_TRANSCRIPT_FILE_LIMIT + 1)
        if len(contents) > CALL_TRANSCRIPT_FILE_LIMIT:
            return None, '文字起こしファイルは256KB以下にしてください。'
        try:
            transcript = contents.decode('utf-8-sig')
        except UnicodeDecodeError:
            return None, '文字起こしファイルをUTF-8で読み取れません。'
        if '\x00' in transcript:
            return None, '文字起こしファイルの内容がテキストではありません。'
    else:
        transcript = form.get('transcript', '')
    if not isinstance(transcript, str) or not transcript.strip():
        return None, '文字起こしを貼り付けるか、.txtファイルを添付してください。'
    if len(transcript) > 50000:
        return None, '文字起こしは50,000文字以内で入力してください。'
    return transcript, None


def insert_transcript_call_report(transcript):
    extraction, error = extract_call_transcript(transcript)
    if error:
        return None, error, 400
    call_report = extraction['call_report']
    operation = extraction['operation']
    saved_disaster_cases = False
    try:
        with CALL_REPORT_PAIR_LOCK:
            with disaster_case_write_lock():
                with call_reports_write_lock():
                    existing_cases = read_disaster_cases_for_write()
                    existing_reports = read_call_reports_for_write()
                    disaster_numbers = [
                        int(match.group(1)) for item in existing_cases
                        if (match := re.fullmatch(r'DR-(\d+)', str(item.get('id', ''))))
                    ]
                    transcript_numbers = [
                        int(match.group(1)) for item in existing_reports
                        if (match := re.fullmatch(r'TR-(\d+)', str(item.get('system_id', ''))))
                    ]
                    operation_id = f'DR-{max(disaster_numbers, default=0) + 1:03d}'
                    call_report_id = f'TR-{max(transcript_numbers, default=0) + 1:04d}'
                    received_at = datetime.now(JST).isoformat(timespec='minutes')
                    call_report['system_id'] = call_report_id
                    call_report['管理情報']['災害対応ID'] = operation_id
                    operation.update({
                        'id': operation_id,
                        'received_at': received_at,
                        'source_call_report_id': call_report_id,
                        'messages': [],
                        'timeline': [{
                            'time': received_at,
                            'label': '文字起こし受付',
                            'detail': f'{call_report_id}から直接発言を一次抽出しました。内容と重要度を職員が確認してください。',
                        }],
                    })
                    save_disaster_cases(existing_cases + [operation])
                    saved_disaster_cases = True
                    try:
                        save_call_reports(existing_reports + [call_report])
                    except (OSError, ValueError, json.JSONDecodeError):
                        save_disaster_cases(existing_cases)
                        saved_disaster_cases = False
                        raise
    except (OSError, ValueError, json.JSONDecodeError):
        if saved_disaster_cases:
            try:
                with disaster_case_write_lock():
                    save_disaster_cases(existing_cases)
            except (OSError, ValueError):
                pass
        return None, '通報または災害対応案件を保存できませんでした。既存データは保護されています。', 500
    return {'call_report': call_report, 'operation': operation}, None, 201


def call_report_related_key(report):
    place = report.get('場所', {})
    municipality = place.get('市区町村', CALL_REPORT_UNKNOWN)
    district = place.get('地区・町名', CALL_REPORT_UNKNOWN)
    detailed_place = place.get('詳細な場所', CALL_REPORT_UNKNOWN)
    landmark = place.get('目印・ランドマーク', CALL_REPORT_UNKNOWN)
    disaster = report.get('災害', {}).get('災害種別', CALL_REPORT_UNKNOWN)
    if (
        municipality == CALL_REPORT_UNKNOWN or district == CALL_REPORT_UNKNOWN
        or disaster == CALL_REPORT_UNKNOWN
        or (detailed_place == CALL_REPORT_UNKNOWN and landmark == CALL_REPORT_UNKNOWN)
    ):
        return None
    exact_location = tuple(
        str(place.get(field, CALL_REPORT_UNKNOWN)).casefold()
        for field in ('市区町村', '地区・町名', '詳細な場所', '目印・ランドマーク')
    )
    return exact_location + (str(disaster).casefold(),)


def group_call_reports(reports):
    groups = {}
    for report in reports:
        key = call_report_related_key(report)
        if key is not None:
            groups.setdefault(key, []).append(report)
    related_groups = [group for group in groups.values() if len(group) > 1]
    for group in related_groups:
        common_facts = set(group[0].get('確認された内容', []))
        for report in group[1:]:
            common_facts.intersection_update(report.get('確認された内容', []))
        related_summaries = [{
            'system_id': item.get('system_id', CALL_REPORT_UNKNOWN),
            '通報日時': item.get('通報日時', CALL_REPORT_UNKNOWN),
            '短い要約': item.get('短い要約', ''),
        } for item in group]
        for report in group:
            report['関連通報'] = related_summaries
            report['複数通報で確認'] = sorted(common_facts)
    for report in reports:
        report.setdefault('関連通報', [{
            'system_id': report.get('system_id', CALL_REPORT_UNKNOWN),
            '通報日時': report.get('通報日時', CALL_REPORT_UNKNOWN),
            '短い要約': report.get('短い要約', ''),
        }])
        report.setdefault('複数通報で確認', [])
    return reports, len(related_groups)


def call_report_has_human_harm(report):
    harm = str(report.get('被害', {}).get('人的被害', CALL_REPORT_UNKNOWN)).strip()
    if harm in ('', CALL_REPORT_UNKNOWN):
        return False
    if harm.startswith(('なし', '無', 'いない', '該当なし', '0人')) or any(
        phrase in harm for phrase in ('はいない', 'はいません', 'はいませんでした', 'けが人なし', '怪我人なし')
    ):
        return False
    uncertain_phrases = (
        '不明', '要確認', '未確認', 'かもしれ', 'たぶん', '思う', 'ように見える',
        '可能性', '疑い', '見込み', 'らしい', 'ようだ', 'と思われ',
    )
    return not any(phrase in harm for phrase in uncertain_phrases)


def read_call_reports_for_write():
    if not os.path.exists(CALL_REPORTS_FILE):
        return []
    with open(CALL_REPORTS_FILE, encoding='utf-8') as report_file:
        reports = json.load(report_file)
    if not isinstance(reports, list) or any(not isinstance(item, dict) for item in reports):
        raise ValueError('通報データの保存形式が不正です。')
    return reports


def insert_call_report(payload):
    report, error = validate_call_report(payload)
    if error:
        return None, error, 400
    try:
        with call_reports_write_lock():
            reports = read_call_reports_for_write()
            existing_numbers = [
                int(match.group(1)) for item in reports
                if (match := re.fullmatch(r'TR-(\d+)', str(item.get('system_id', ''))))
            ]
            report['system_id'] = f'TR-{max(existing_numbers, default=0) + 1:04d}'
            reports.append(report)
            save_call_reports(reports)
    except (OSError, ValueError, json.JSONDecodeError):
        return None, '通報データを保存できませんでした。保存先を確認してください。', 500
    return report, None, 201


def set_call_report_review_state(system_id, review_state):
    if review_state not in CALL_REPORT_REVIEW_STATES:
        return False, '確認状態の値が正しくありません。', 400
    try:
        with call_reports_write_lock():
            reports = read_call_reports_for_write()
            report = next((item for item in reports if item.get('system_id') == system_id), None)
            if report is None:
                return False, '指定された通報が見つかりません。', 404
            report.setdefault('管理情報', {})['確認状態'] = review_state
            report['管理情報']['確認更新日時'] = datetime.now(JST).isoformat(timespec='seconds')
            report['管理情報']['確認者'] = str(session.get('username', 'api'))[:120]
            save_call_reports(reports)
    except (OSError, ValueError, json.JSONDecodeError):
        return False, '確認状態を保存できませんでした。', 500
    return True, None, 200


def call_report_api_login_required(function):
    @wraps(function)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '認証が必要です。'}), 401
        return function(*args, **kwargs)
    return decorated


def get_call_report_dashboard(filters):
    reports = [normalized_call_report(item) for item in load_call_reports()]
    reports, related_group_count = group_call_reports(reports)
    for report in reports:
        report['人的被害情報あり'] = call_report_has_human_harm(report)
    stats = {
        'total': len(reports),
        'unreviewed': sum(item['管理情報']['確認状態'] == '未確認' for item in reports),
        'urgent': sum(item['緊急度']['レベル'] == '高' for item in reports),
        'human_harm': sum(call_report_has_human_harm(item) for item in reports),
        'rescue': sum(item['救助要請'] == 'あり' for item in reports),
        'related_groups': related_group_count,
    }

    matching = []
    for report in reports:
        if filters.get('hazard') and report['災害']['災害種別'] != filters['hazard']:
            continue
        if filters.get('urgency') and report['緊急度']['レベル'] != filters['urgency']:
            continue
        place = report['場所']
        if filters.get('area') and filters['area'].casefold() not in ' '.join((place['市区町村'], place['地区・町名'])).casefold():
            continue
        if filters.get('rescue') and report['救助要請'] != 'あり':
            continue
        if filters.get('unreviewed') and report['管理情報']['確認状態'] != '未確認':
            continue
        keyword = filters.get('q', '').casefold()
        searchable = ' '.join((
            report.get('system_id', ''), report.get('通報ID', ''), report.get('短い要約', ''),
            report.get('元の文字起こし', ''), report['災害']['災害種別'],
            *place.values(), *report['確認された内容'], *report['通報者による推測'],
        )).casefold()
        if keyword and keyword not in searchable:
            continue
        matching.append(report)

    urgency_order = {'高': 0, '中': 1, '要確認': 2}
    if filters.get('sort') == 'urgency':
        matching.sort(key=lambda item: (
            urgency_order[item['緊急度']['レベル']],
            -parse_disaster_time(item['管理情報']['登録日時']).timestamp(),
        ))
    else:
        sort_key = '通報日時' if filters.get('sort') == 'reported' else '登録日時'
        matching.sort(key=lambda item: -parse_disaster_time(
            item[sort_key] if sort_key == '通報日時' else item['管理情報'][sort_key]
        ).timestamp())

    hazard_options = sorted({item['災害']['災害種別'] for item in reports if item['災害']['災害種別'] != CALL_REPORT_UNKNOWN})
    area_options = sorted({
        ' '.join(value for value in (item['場所']['市区町村'], item['場所']['地区・町名']) if value != CALL_REPORT_UNKNOWN)
        for item in reports
        if item['場所']['市区町村'] != CALL_REPORT_UNKNOWN or item['場所']['地区・町名'] != CALL_REPORT_UNKNOWN
    })
    return matching, stats, related_group_count, hazard_options, area_options, reports


def valid_disaster_upload(file_storage, contents):
    original_filename = os.path.basename((file_storage.filename or '').replace('\\', '/'))
    extension = os.path.splitext(original_filename)[1].lower()
    expected_mime = DISASTER_UPLOAD_EXTENSIONS.get(extension)
    if not expected_mime:
        return False
    actual_mime = None
    if contents.startswith(b'\xff\xd8\xff'):
        actual_mime = 'image/jpeg'
    elif contents.startswith(b'\x89PNG\r\n\x1a\n'):
        actual_mime = 'image/png'
    elif len(contents) >= 12 and contents[:4] == b'RIFF' and contents[8:12] == b'WEBP':
        actual_mime = 'image/webp'
    return actual_mime == expected_mime and file_storage.mimetype in (expected_mime, 'application/octet-stream')
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def parse_area_warnings(warning_data):
    """気象庁JSONの最新発表から青森県全体の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    reports = []
    for report in warning_data:
        if not isinstance(report, dict):
            continue
        report_datetime = report.get("reportDatetime")
        if not isinstance(report_datetime, str) or not report_datetime:
            continue
        try:
            parsed_datetime = datetime.fromisoformat(
                report_datetime.replace("Z", "+00:00")
            )
        except ValueError:
            continue
        reports.append((parsed_datetime, report_datetime, report))

    if not reports:
        return [], ""

    _, latest_report_datetime, latest_report = max(reports, key=lambda item: item[0])
    warning = latest_report.get("warning", {})
    class10_items = warning.get("class10Items", [])
    if not isinstance(class10_items, list):
        return [], latest_report_datetime

    warnings = []
    seen_codes = set()
    for area in class10_items:
        if not isinstance(area, dict):
            continue
        for kind in area.get("kinds", []):
            if not isinstance(kind, dict):
                continue
            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue
            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


def get_current_weather():
    """Open-Meteoから青森市の現在の天気を取得する"""
    weather_url = (
        "https://api.open-meteo.com/v1/forecast?latitude=40.8222"
        "&longitude=140.7474&current=temperature_2m,apparent_temperature,"
        "relative_humidity_2m,wind_speed_10m,weather_code"
        "&hourly=temperature_2m,precipitation_probability,weather_code"
        "&forecast_days=1"
        "&timezone=Asia%2FTokyo"
    )
    try:
        with urllib.request.urlopen(weather_url, timeout=10) as res:
            weather_data = json.loads(res.read())
        current = weather_data.get("current", {})
        hourly = weather_data.get("hourly", {})
        hourly_units = weather_data.get("hourly_units", {})
        weather_code = current.get("weather_code")
        hourly_forecast = [
            {
                "time": time,
                "temperature": temperature,
                "precipitation_probability": precipitation_probability,
                "condition": WEATHER_CODES.get(hourly_code, "-")
            }
            for time, temperature, precipitation_probability, hourly_code in zip(
                hourly.get("time", []),
                hourly.get("temperature_2m", []),
                hourly.get("precipitation_probability", []),
                hourly.get("weather_code", [])
            )
        ]
        return {
            "location": "青森市",
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "condition": WEATHER_CODES.get(weather_code, "天気情報あり"),
            "observed_at": current.get("time"),
            "unit": weather_data.get("current_units", {}),
            "hourly": hourly_forecast,
            "hourly_units": hourly_units,
            "error": False
        }
    except Exception:
        return {
            "location": "青森市",
            "error": True
        }

# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        damage_reports=damage_reports
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            session['logout_csrf_token'] = secrets.token_urlsafe(32)
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout', methods=['POST'])
def logout():
    expected_token = session.get('logout_csrf_token', '')
    submitted_token = request.form.get('csrf_token', '')
    if not expected_token or not secrets.compare_digest(submitted_token, expected_token):
        abort(403)
    session.clear()
    return redirect(url_for('login'))

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所名を入力してください。'
            )

        shelter_ids = [
            shelter.get('id') for shelter in shelters
            if isinstance(shelter.get('id'), int)
        ]
        new_id = max(shelter_ids, default=0) + 1
        shelters.append({'id': new_id, 'name': name})

        try:
            save_shelters()
        except OSError:
            shelters.pop()
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所情報を保存できませんでした。'
            )

        return render_template(
            'shelter_register.html',
            success=True,
            message='避難所を登録しました。'
        )

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 被害情報：住民通報・自治体提供の情報を位置と画像付きで確認する
@app.route('/board')
def board():
    reports = []
    safe_static_images = {'damage-road.svg', 'damage-landslide.svg'}
    for source_report in load_damage_reports():
        report = dict(source_report)
        report['verified'] = report.get('verified') is True
        report['type'] = report.get('type') if report.get('type') in DAMAGE_TYPES else 'other'
        report['legacy_report'] = source_report.get('type') not in DAMAGE_TYPES
        report['type_label'] = report.get('type_label') or (
            DAMAGE_TYPES[report['type']] if source_report.get('type') in DAMAGE_TYPES else '既存の被害情報'
        )
        report['source'] = report.get('source', '')
        report['original_name'] = report.get('original_name') or report.get('image', '')
        report['image_url'] = None
        image_name = str(report.get('image', ''))
        if report.get('uploaded_image') is True and re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp)', image_name):
            if os.path.isfile(os.path.join(DAMAGE_UPLOAD_DIR, image_name)):
                report['image_url'] = url_for('damage_uploaded_image', filename=image_name)
        elif image_name in safe_static_images:
            report['image_url'] = url_for('static', filename=image_name)
        try:
            report['latitude'] = float(report['latitude'])
            report['longitude'] = float(report['longitude'])
            report['has_coordinates'] = (
                math.isfinite(report['latitude']) and math.isfinite(report['longitude'])
                and -90 <= report['latitude'] <= 90 and -180 <= report['longitude'] <= 180
            )
        except (KeyError, TypeError, ValueError):
            report['has_coordinates'] = False
        reports.append(report)

    sort_options = {
        'reported_at': lambda report: str(report.get('reported_at', '')),
        'type': lambda report: str(report.get('type_label', '')),
        'content': lambda report: str(report.get('content', '')),
        'location': lambda report: str(report.get('location', '')),
        'verified': lambda report: report.get('verified', False),
    }
    sort_key = request.args.get('sort', 'reported_at')
    if sort_key not in sort_options:
        sort_key = 'reported_at'
    reports.sort(key=sort_options[sort_key], reverse=True)
    return render_template(
        'board.html',
        instructions=[i for i in instructions if i.get('target') == '住民'],
        damage_reports=reports,
        damage_reports_json=[{
            'id': report.get('id'), 'type': report.get('type'),
            'type_label': report.get('type_label'), 'content': report.get('content', ''),
            'location': report.get('location', ''), 'source': report.get('source', ''),
            'legacy_report': report.get('legacy_report', False),
            'latitude': report.get('latitude'), 'longitude': report.get('longitude'),
            'has_coordinates': report.get('has_coordinates', False),
            'reported_at': report.get('reported_at', ''), 'verified': report['verified'],
            'image_url': report.get('image_url'), 'original_name': report.get('original_name', ''),
        } for report in reports],
        sort_key=sort_key,
        can_manage=bool(session.get('logged_in')),
        csrf_token=disaster_csrf_token(),
        success=request.args.get('posted') == '1',
    )

# ヘッダーの被害情報タブから開く公開ページ
@app.route('/damage_info')
def damage_info():
    return redirect(url_for('board'))


@app.route('/damage_reports/new', methods=['GET', 'POST'])
def damage_report_new():
    error = None
    values = request.form if request.method == 'POST' else {}
    csrf_token = disaster_csrf_token()
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf_token', ''), csrf_token):
            error = 'フォームの有効期限が切れました。ページを再読み込みしてください。'
        else:
            photos = [photo for photo in request.files.getlist('photo') if photo.filename]
            if len(photos) != 1:
                error = '状況写真を1枚選択してください。'
            else:
                report, error, status = insert_damage_report(
                    request.form.get('type'), request.form.get('latitude'),
                    request.form.get('longitude'), request.form.get('content', ''), photos[0]
                )
                if status == 201:
                    return redirect(url_for('board', posted=1))
    return render_template(
        'damage_report_form.html', values=values, error=error,
        csrf_token=csrf_token, damage_types=DAMAGE_TYPES,
    ), (400 if error else 200)


@app.route('/damage_uploads/<filename>')
def damage_uploaded_image(filename):
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp)', filename):
        return '', 404
    if not os.path.isfile(os.path.join(DAMAGE_UPLOAD_DIR, filename)):
        return '', 404
    return send_from_directory(DAMAGE_UPLOAD_DIR, filename, as_attachment=False, conditional=True)


@app.route('/damage_reports/<int:report_id>/verification', methods=['POST'])
@login_required
def damage_report_verification(report_id):
    if not secrets.compare_digest(request.form.get('csrf_token', ''), disaster_csrf_token()):
        flash('フォームの有効期限が切れました。', 'error')
        return redirect(url_for('board'))
    verified_value = request.form.get('verified')
    if verified_value not in ('true', 'false'):
        flash('確認状態の指定が正しくありません。', 'error')
        return redirect(url_for('board'))
    try:
        with damage_reports_write_lock():
            reports = read_damage_reports_for_write()
            report = next((item for item in reports if str(item.get('id')) == str(report_id)), None)
            if report is None:
                flash('指定された投稿が見つかりません。', 'error')
                return redirect(url_for('board'))
            report['verified'] = verified_value == 'true'
            save_damage_reports(reports)
    except (OSError, ValueError, json.JSONDecodeError):
        flash('確認状態を保存できませんでした。', 'error')
        return redirect(url_for('board'))
    flash('確認状態を更新しました。', 'success')
    return redirect(url_for('board'))


@app.route('/damage_reports/<int:report_id>/delete', methods=['POST'])
@login_required
def damage_report_delete(report_id):
    if not secrets.compare_digest(request.form.get('csrf_token', ''), disaster_csrf_token()):
        flash('フォームの有効期限が切れました。', 'error')
        return redirect(url_for('board'))
    quarantine_path = None
    image_path = None
    try:
        with damage_reports_write_lock():
            reports = read_damage_reports_for_write()
            report = next((item for item in reports if str(item.get('id')) == str(report_id)), None)
            if report is None:
                flash('指定された投稿が見つかりません。', 'error')
                return redirect(url_for('board'))
            image_name = str(report.get('image', ''))
            if report.get('uploaded_image') is True and re.fullmatch(
                r'[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp)', image_name
            ):
                image_path = os.path.join(DAMAGE_UPLOAD_DIR, image_name)
                if os.path.isfile(image_path):
                    quarantine_path = os.path.join(DAMAGE_UPLOAD_DIR, f'.delete-{uuid.uuid4().hex}.tmp')
                    os.replace(image_path, quarantine_path)
            save_damage_reports([item for item in reports if str(item.get('id')) != str(report_id)])
            if quarantine_path and os.path.exists(quarantine_path):
                try:
                    os.remove(quarantine_path)
                except OSError:
                    save_damage_reports(reports)
                    os.replace(quarantine_path, image_path)
                    quarantine_path = None
                    raise
    except (OSError, ValueError, json.JSONDecodeError):
        if quarantine_path and image_path and os.path.exists(quarantine_path):
            os.replace(quarantine_path, image_path)
        flash('投稿を削除できませんでした。', 'error')
        return redirect(url_for('board'))
    flash('投稿を削除しました。', 'success')
    return redirect(url_for('board'))


@app.route('/operations')
@login_required
def disaster_operations():
    cases = [normalized_disaster_case(case) for case in load_disaster_cases()]
    filters = {
        'priority': request.args.get('priority', ''),
        'risk': request.args.get('risk', ''),
        'reporter_type': request.args.get('reporter_type', ''),
        'source': request.args.get('source', ''),
        'status': request.args.get('status', ''),
        'q': request.args.get('q', '').strip(),
    }
    filtered_cases = []
    for case in cases:
        if filters['priority'] and case['priority'] != filters['priority']:
            continue
        if filters['risk'] and case['risk'] != filters['risk']:
            continue
        if filters['reporter_type'] and case['reporter_type'] != filters['reporter_type']:
            continue
        if filters['source'] and case['source'] != filters['source']:
            continue
        if filters['status'] and case['status'] != filters['status']:
            continue
        searchable = ' '.join(str(case.get(key, '')) for key in (
            'id', 'title', 'location', 'risk', 'reporter_type', 'reporter', 'details'
        )).casefold()
        if filters['q'].casefold() not in searchable:
            continue
        filtered_cases.append(case)

    priority_order = {priority: index for index, priority in enumerate(DISASTER_PRIORITIES)}
    filtered_cases.sort(key=lambda case: (
        priority_order.get(case['priority'], len(priority_order)),
        -parse_disaster_time(case['received_at']).timestamp()
    ))
    stats = {
        'total': len(cases),
        'priority': sum(case['priority'] in ('緊急', '高') for case in cases),
        'open': sum(case['status'] != '完了' for case in cases),
        'media': sum(
            case['source'] in ('チャット', '画像') or bool(case['attachments'])
            for case in cases
        ),
    }
    return render_template(
        'operations.html', cases=filtered_cases, stats=stats, filters=filters,
        priorities=DISASTER_PRIORITIES, risks=DISASTER_RISKS,
        reporter_types=DISASTER_REPORTER_TYPES, sources=DISASTER_SOURCES,
        statuses=DISASTER_STATUSES
    )


@app.route('/operations/new', methods=['GET', 'POST'])
@login_required
def disaster_operation_new():
    csrf_token = disaster_csrf_token()
    form_values = request.form if request.method == 'POST' else {}
    error = None
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf_token', ''), csrf_token):
            error = 'フォームの有効期限が切れました。ページを再読み込みして、もう一度お試しください。'
        else:
            source = request.form.get('source', '')
            priority = request.form.get('priority', '')
            risk = request.form.get('risk', '')
            reporter_type = request.form.get('reporter_type', '')
            title = request.form.get('title', '').strip()
            location = request.form.get('location', '').strip()
            details = request.form.get('details', '').strip()
            reporter = request.form.get('reporter', '').strip() or '匿名'
            uploaded_files = [item for item in request.files.getlist('attachments') if item.filename]

            if source not in DISASTER_SOURCES:
                error = '受付方法を選択してください。'
            elif priority not in DISASTER_PRIORITIES:
                error = '重要度を選択してください。'
            elif risk not in DISASTER_RISKS:
                error = '危険の種類を選択してください。'
            elif reporter_type not in DISASTER_REPORTER_TYPES:
                error = '報告元を選択してください。'
            elif not title or not location or not details:
                error = '案件名、場所、通報内容を入力してください。'
            elif len(uploaded_files) > 4:
                error = '現場画像は1件につき4枚までです。'
            elif source == '画像' and not uploaded_files:
                error = '受付方法が「画像」の場合は、現場画像を1枚以上添付してください。'

            prepared_uploads = []
            if not error:
                for uploaded_file in uploaded_files:
                    contents = uploaded_file.stream.read(DISASTER_UPLOAD_LIMIT + 1)
                    if len(contents) > DISASTER_UPLOAD_LIMIT:
                        error = '画像は1枚あたり5MB以下にしてください。'
                        break
                    if not valid_disaster_upload(uploaded_file, contents):
                        error = 'JPG、JPEG、PNG、WebP形式の画像を選択してください。'
                        break
                    original_filename = os.path.basename(uploaded_file.filename.replace('\\', '/'))
                    extension = os.path.splitext(original_filename)[1].lower()
                    original_name = re.sub(r'[\x00-\x1f\x7f]', '', original_filename)[:255]
                    original_name = original_name or f'image{extension}'
                    prepared_uploads.append({
                        'filename': f'{uuid.uuid4().hex}{extension}',
                        'original_name': original_name,
                        'contents': contents,
                    })

            if not error:
                received_at = datetime.now(JST).isoformat(timespec='minutes')
                case = {
                    'received_at': received_at,
                    'source': source,
                    'reporter_type': reporter_type,
                    'priority': priority,
                    'risk': risk,
                    'status': '未対応',
                    'title': title,
                    'location': location,
                    'reporter': reporter,
                    'details': details,
                    'messages': [{'time': received_at, 'sender': reporter_type, 'content': details}],
                    'attachments': [
                        {'filename': item['filename'], 'original_name': item['original_name']}
                        for item in prepared_uploads
                    ],
                    'timeline': [{
                        'time': received_at,
                        'label': f'{source}受付',
                        'detail': '新しい災害報告を受け付けました。',
                    }],
                }
                saved_paths = []
                try:
                    os.makedirs(DISASTER_UPLOAD_DIR, exist_ok=True)
                    with disaster_case_write_lock():
                        existing_cases = load_disaster_cases()
                        existing_ids = [
                            int(match.group(1)) for item in existing_cases
                            if (match := re.fullmatch(r'DR-(\d+)', str(item.get('id', ''))))
                        ]
                        case['id'] = f'DR-{max(existing_ids, default=0) + 1:03d}'
                        for item in prepared_uploads:
                            file_path = os.path.join(DISASTER_UPLOAD_DIR, item['filename'])
                            with open(file_path, 'wb') as image_file:
                                image_file.write(item['contents'])
                            saved_paths.append(file_path)
                        save_disaster_cases(existing_cases + [case])
                except OSError:
                    for saved_path in saved_paths:
                        if os.path.exists(saved_path):
                            os.remove(saved_path)
                    error = '受付情報を保存できませんでした。時間をおいて再度お試しください。'
                if not error:
                    return redirect(url_for('disaster_operation_detail', report_id=case['id']))

    return render_template(
        'operation_register.html', error=error, values=form_values,
        csrf_token=csrf_token, priorities=DISASTER_PRIORITIES, risks=DISASTER_RISKS,
        reporter_types=DISASTER_REPORTER_TYPES, sources=DISASTER_SOURCES
    ), (400 if error else 200)


@app.route('/operations/<report_id>')
@login_required
def disaster_operation_detail(report_id):
    case = next((
        normalized_disaster_case(item)
        for item in load_disaster_cases()
        if str(item.get('id', '')) == report_id
    ), None)
    if case is None:
        return render_template('operation_not_found.html'), 404
    valid_attachments = []
    for attachment in case['attachments']:
        if not isinstance(attachment, dict):
            continue
        filename = str(attachment.get('filename', ''))
        if not re.fullmatch(r'(?:[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)|sample-[a-z-]+\.svg)', filename):
            continue
        if os.path.isfile(os.path.join(DISASTER_UPLOAD_DIR, filename)):
            valid_attachments.append(attachment)
    case['attachments'] = valid_attachments
    return render_template('operation_detail.html', case=case)


@app.route('/operations/uploads/<filename>')
@login_required
def disaster_operation_image(filename):
    if not re.fullmatch(r'(?:[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)|sample-[a-z-]+\.svg)', filename):
        return '', 404
    if not os.path.isfile(os.path.join(DISASTER_UPLOAD_DIR, filename)):
        return '', 404
    return send_from_directory(DISASTER_UPLOAD_DIR, filename, as_attachment=False, conditional=True)


@app.route('/call-reports', methods=['GET', 'POST'])
@login_required
def call_reports_dashboard():
    error = None
    transcript = ''
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf_token', ''), disaster_csrf_token()):
            error = 'フォームの有効期限が切れました。再読み込みしてやり直してください。'
        else:
            transcript, error = get_submitted_call_transcript(request.form, request.files)
            if not error:
                result, error, status = insert_transcript_call_report(transcript)
                if status == 201:
                    return redirect(url_for('disaster_operation_detail', report_id=result['operation']['id']))
    return render_template(
        'call_transcript_intake.html', csrf_token=disaster_csrf_token(),
        transcript=transcript, error=error,
    ), (400 if error else 200)


@app.route('/call-reports/new', methods=['GET', 'POST'])
@login_required
def call_report_new():
    return redirect(url_for('call_reports_dashboard'))


@app.route('/call-reports/<system_id>', methods=['GET', 'POST'])
@login_required
def call_report_detail(system_id):
    report = next((item for item in load_call_reports() if item.get('system_id') == system_id), None)
    if report is None:
        return render_template('call_report_not_found.html'), 404
    operation_id = report.get('管理情報', {}).get('災害対応ID')
    if operation_id:
        return redirect(url_for('disaster_operation_detail', report_id=operation_id))
    return redirect(url_for('call_reports_dashboard'))


@app.route('/api/call-reports', methods=['GET', 'POST'])
@call_report_api_login_required
def api_call_reports():
    if request.method == 'GET':
        reports, stats, related_group_count, _, _, _ = get_call_report_dashboard({'sort': 'registered'})
        return jsonify({
            'items': reports,
            'stats': stats,
            'related_group_count': related_group_count,
            'csrf_token': disaster_csrf_token(),
        })
    if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), disaster_csrf_token()):
        return jsonify({'error': 'CSRFトークンが正しくありません。'}), 403
    report, error, status = insert_call_report(request.get_json(silent=True))
    if error:
        return jsonify({'error': error}), status
    return jsonify(report), status


@app.route('/api/call-reports/<system_id>/review', methods=['PATCH'])
@call_report_api_login_required
def api_call_report_review(system_id):
    if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), disaster_csrf_token()):
        return jsonify({'error': 'CSRFトークンが正しくありません。'}), 403
    payload = request.get_json(silent=True)
    review_state = payload.get('確認状態') if isinstance(payload, dict) else None
    success, error, status = set_call_report_review_state(system_id, review_state)
    if not success:
        return jsonify({'error': error}), status
    return jsonify({'system_id': system_id, '確認状態': review_state}), 200

# 届いた資料：住民・自治体から受信した資料を一覧で確認する
@app.route('/materials')
def materials():
    current_materials = load_json(RECEIVED_MATERIALS_FILE, received_materials)
    return render_template('materials.html', materials=current_materials)

# 通知API：住民から届いた資料の件数と最新情報を返す
@app.route('/api/notifications')
def api_notifications():
    current_materials = load_json(RECEIVED_MATERIALS_FILE, received_materials)
    resident_materials = [
        material for material in current_materials
        if material.get('sender') == '住民通報'
    ]
    latest = resident_materials[0] if resident_materials else None
    return jsonify({
        'count': len(resident_materials),
        'latest': latest,
        'notifications': resident_materials
    })

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results = filter_shelters(request.args.get('district'))
    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

# 現在天気API
@app.route('/api/current_weather')
def api_current_weather():
    return jsonify(get_current_weather())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
