"""Loopback-only, authenticated, bounded explanation jobs and review sessions."""
from __future__ import annotations

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import secrets
import threading
import time
import uuid
import io
from urllib.parse import urlsplit

import cv2
import numpy as np
from PIL import Image
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .explanations import AnalysisCancelled, capture_options, explain, prepare_position


class Answers(BaseModel):
    revision: int
    question_id: str
    fen: str = Field(min_length=5, max_length=120)
    confirmed_history: bool = False
    before_fen: str = Field(default="", max_length=120)
    target_uci: str = Field(default="", max_length=5)
    capture_uci: str = Field(default="", max_length=5)


class CapturePreview(BaseModel):
    fen: str = Field(min_length=5, max_length=120)
    before_fen: str = Field(default="", max_length=120)
    target_uci: str = Field(default="", max_length=5)


class JobStore:
    def __init__(self, recognize, config, popup=None, analyser=explain):
        self.recognize, self.config, self.popup, self.analyser = recognize, config, popup, analyser
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chesslens")
        self.jobs = {}
        self.requests = {}
        self.token = secrets.token_urlsafe(32)

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise HTTPException(404, "분석 세션이 없거나 만료됐습니다.")
            return self.jobs[job_id]

    def snapshot(self, job_id):
        with self.lock:
            job = self.get(job_id)
            return json.loads(json.dumps({k: v for k, v in job.items() if not k.startswith("_")}))

    def update(self, job, **values):
        with self.lock:
            if job['_cancel'].is_set():
                return False
            job.update(values)
            job['revision'] += 1
            job['_updated'] = time.monotonic()
            return True

    def create(self, request_id, question, payload, fen, confirmed, before_fen, target_uci, show_popup, source_bounds, capture_uci=""):
        identity = hashlib.sha256(payload + json.dumps([question, fen, confirmed, before_fen, target_uci, show_popup, source_bounds, capture_uci], sort_keys=True).encode()).hexdigest()
        with self.lock:
            # Only expired sessions are removed; never evict active review sessions.
            for key, old in list(self.jobs.items()):
                if time.monotonic() - old['_updated'] > 1800:
                    self.cancel(key)
                    self.requests.pop(old['request_id'], None)
                    self.jobs.pop(key, None)
            if request_id in self.requests:
                old_id, old_hash = self.requests[request_id]
                if old_hash != identity:
                    raise HTTPException(409, "같은 request_id에 다른 입력을 보낼 수 없습니다.")
                return self.snapshot(old_id)
            if len(self.jobs) >= 24:
                raise HTTPException(429, "분석 세션이 많습니다. 세션을 닫거나 만료 후 다시 시도하세요.")
            job_id = uuid.uuid4().hex
            job = dict(schema_version=1, request_id=request_id, job_id=job_id, revision=1,
                       status='queued', progress_stage='접수', needs_review=False, clarifications=[], result=None,
                       recognition=None, proposed_fen=fen, question=question, popup_error='', source_bounds=source_bounds,
                       before_fen=before_fen, target_uci=target_uci, capture_uci=capture_uci,
                       gui_url=f'/explain?job={job_id}', _cancel=threading.Event(), _updated=time.monotonic())
            self.jobs[job_id] = job
            self.requests[request_id] = (job_id, identity)
            self.pool.submit(self.process, job, payload, fen, confirmed, before_fen, target_uci, capture_uci)
        if show_popup and self.popup:
            try:
                self.popup(job_id, source_bounds)
            except (OSError, ValueError, RuntimeError):
                self.update(job, popup_error='팝업 런타임을 열지 못했습니다. ChessLens 웹 화면을 사용하세요.')
        return self.snapshot(job_id)

    def process(self, job, payload, fen, confirmed, before_fen, target_uci, capture_uci=""):
        try:
            if job['_cancel'].is_set():
                return
            if payload and not (fen and confirmed):
                self.update(job, status='recognizing', progress_stage='보드 인식')
                try:
                    recognition = self.recognize(payload)
                    if not self.update(job, recognition=recognition):
                        return
                except (ValueError, RuntimeError, FileNotFoundError) as exc:
                    if not self.update(job, recognition_error='자동 인식 실패: '+str(exc)[:300]):
                        return
            if not (fen and confirmed):
                self.update(job, status='needs_input', progress_stage='판·게임 정보 확인', needs_review=True,
                            clarifications=[dict(id='confirm-position', text='판 전체·차례·캐슬링·앙파상 권리를 확인하세요. 직전 수를 설명하려면 이전 FEN과 대상 수가 필요합니다.')])
                return
            self.analyse(job, fen, before_fen, target_uci, capture_uci)
        except AnalysisCancelled:
            pass
        except Exception as exc:
            self.update(job, status='failed', progress_stage='실패', error=str(exc)[:400])

    def analyse(self, job, fen, before_fen, target_uci, capture_uci=""):
        if not self.update(job, status='analyzing', progress_stage='Stockfish 분석', needs_review=False, clarifications=[]):
            return
        options = {'capture_uci': capture_uci} if capture_uci else {}
        result = self.analyser(fen, self.config.engine_path, before_fen, target_uci, cancelled=job['_cancel'], **options)
        self.update(job, status='ready', progress_stage='완료', result=result)

    def answer(self, job_id, answer):
        if not answer.confirmed_history:
            raise HTTPException(400, '게임 정보 확인이 필요합니다.')
        try:
            capture_options(answer.fen, answer.before_fen, answer.target_uci, answer.capture_uci)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with self.lock:
            job = self.get(job_id)
            if job['status'] != 'needs_input' or answer.revision != job['revision'] or answer.question_id != 'confirm-position':
                raise HTTPException(409, '세션이 변경됐습니다. 최신 확인 질문을 다시 불러오세요.')
            self.update(job, status='queued', progress_stage='분석 대기', needs_review=False, proposed_fen=answer.fen,
                        before_fen=answer.before_fen, target_uci=answer.target_uci, capture_uci=answer.capture_uci)
            self.pool.submit(self.process, job, b'', answer.fen, True, answer.before_fen, answer.target_uci, answer.capture_uci)
        return self.snapshot(job_id)

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['status'] != 'cancelled':
                job['_cancel'].set()
                job.update(status='cancelled', progress_stage='닫힘', needs_review=False, clarifications=[], recognition=None)
                # Completed facts stay available until expiry; source crop is removed.
                job['revision'] += 1
                job['_updated'] = time.monotonic()
            return self.snapshot(job_id)

    def shutdown(self):
        with self.lock:
            for job in self.jobs.values():
                job['_cancel'].set()
        self.pool.shutdown(wait=False, cancel_futures=True)


def install_explanation_api(app, recognize_payload, web_dir, popup=None, analyser=explain):
    store = JobStore(recognize_payload, app.state.config, popup, analyser)
    app.state.explanations = store

    @app.middleware('http')
    async def local_security(request: Request, call_next):
        if request.url.path.startswith('/api/') or request.url.path == '/explain':
            host = urlsplit('http://' + request.headers.get('host', '')).hostname
            # TestClient is in-process; live requests must use a loopback Host AND peer.
            peer = request.client.host if request.client else ''
            local = {'127.0.0.1', '::1', 'localhost'}
            if host not in local and not (host == 'testserver' and peer == 'testclient'):
                return Response('Loopback Host required', status_code=403)
            if peer not in local and peer != 'testclient':
                return Response('Loopback peer required', status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return Response('Origin rejected', status_code=403)
            if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
                return Response('Cross-origin request rejected', status_code=403)
            if request.url.path.startswith('/api/explanations') and request.url.path != '/api/explanations/session':
                token = request.headers.get('x-chesslens-token', '')
                if not secrets.compare_digest(token, store.token):
                    return Response('Session token required', status_code=401)
        response = await call_next(request)
        if request.url.path.startswith('/api/explanations') or request.url.path == '/explain':
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/explain', include_in_schema=False)
    def explanation_page():
        return FileResponse(web_dir / 'explain.html')

    @app.get('/api/explanations/session')
    def session():
        return dict(token=store.token, schema_version=1)

    @app.post('/api/explanations/capture-options')
    def preview_capture(position: CapturePreview):
        try:
            return capture_options(position.fen, position.before_fen, position.target_uci)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/explanations')
    async def create(request_id: str = Form(..., min_length=1, max_length=100), question: str = Form('', max_length=2000),
                     image: UploadFile | None = File(None), fen: str = Form('', max_length=120),
                     confirmed_history: bool = Form(False), before_fen: str = Form('', max_length=120),
                     target_uci: str = Form('', max_length=5), show_popup: bool = Form(False),
                     source_bounds: str = Form(''), capture_uci: str = Form('', max_length=5)):
        payload = b''
        if image:
            if image.content_type not in {'image/png', 'image/jpeg'}:
                raise HTTPException(415, 'PNG/JPEG만 지원합니다.')
            payload = await image.read(10*1024*1024+1)
            if len(payload) > 10*1024*1024:
                raise HTTPException(413, '10 MiB 이하 이미지만 지원합니다.')
            try:
                with Image.open(io.BytesIO(payload)) as header:
                    if header.format not in {'PNG', 'JPEG'}:
                        raise ValueError()
                    if header.width * header.height > 24_000_000:
                        raise HTTPException(413, '이미지 해상도가 너무 큽니다.')
            except HTTPException:
                raise
            except (OSError, ValueError, Image.DecompressionBombError):
                raise HTTPException(422, '유효한 PNG/JPEG 이미지가 아닙니다.')
            decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR) if payload else None
            if decoded is None:
                raise HTTPException(422, '유효한 PNG/JPEG 이미지가 아닙니다.')
            if decoded.shape[0] * decoded.shape[1] > 24_000_000:
                raise HTTPException(413, '이미지 해상도가 너무 큽니다.')
        if not payload and not fen:
            raise HTTPException(400, '이미지 또는 FEN을 입력하세요.')
        if fen and confirmed_history:
            try:
                capture_options(fen, before_fen, target_uci, capture_uci)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        try:
            bounds = json.loads(source_bounds) if source_bounds else None
            if bounds is not None and (not isinstance(bounds, dict) or set(bounds) != {'x', 'y', 'width', 'height'} or
                                       any(not isinstance(v, (int, float)) or isinstance(v, bool) or not -100000 <= v <= 100000 for v in bounds.values()) or
                                       bounds['width'] <= 0 or bounds['height'] <= 0):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, '화면 위치 형식 오류')
        return store.create(request_id, question, payload, fen, confirmed_history, before_fen, target_uci, show_popup, bounds, capture_uci)

    @app.get('/api/explanations/{job_id}')
    def get_job(job_id: str):
        return store.snapshot(job_id)

    @app.post('/api/explanations/{job_id}/answers')
    def answers(job_id: str, answer: Answers):
        return store.answer(job_id, answer)

    @app.post('/api/explanations/{job_id}/cancel')
    def cancel(job_id: str):
        return store.cancel(job_id)

    previous_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application) as state:
            try:
                yield state
            finally:
                store.shutdown()
    app.router.lifespan_context = lifespan
    return store
