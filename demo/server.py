#!/usr/bin/env python3
"""English video demo. A single application worker serializes every SDK call."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
import json
import math
import signal
import sys
from pathlib import Path
from urllib.parse import unquote
import threading
import time
import uuid
from av import FFmpegError
from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from werkzeug.exceptions import HTTPException
from .source import VideoSource
from .policy import PlaybackSession, video_question, segment_profile, PROFILES, resolve_prompt, MAX_PROMPT_BYTES, MAX_PROMPT_WORDS
from pandora_mage_vl import VideoPacketModel as Engine

TERMINAL={'done','stopped','error'}

@dataclass
class Job:
    id: str
    source_id: str
    max_words: int
    max_tokens: int
    segment_seconds: int = 15
    prompt: str = ''
    prompt_mode: str = 'default'
    request_id: str = ''
    state: str = 'preparing'
    error: str | None = None
    head: float = 0.
    sequence: int = -1
    clock_received: float | None = None
    started: bool = False
    stop: bool = False
    event_count: int = 0
    journal_failed: bool = False
    duration_s: float | None = None
    windows: list = field(default_factory=list)
    video_target_canvas: int = 12
    video_group_size: int = 20
    video_images_per_group: int = 4
    results: dict | None = None
    def public(self):
        return dict(id=self.id,request_id=self.request_id,source_id=self.source_id,state=self.state,error=self.error,
                    playhead_s=self.head,sequence=self.sequence,max_words=self.max_words,max_tokens=self.max_tokens,
                    results=self.results,windows=self.windows,duration_s=self.duration_s,video_target_canvas=self.video_target_canvas,
                    video_group_size=self.video_group_size,video_images_per_group=self.video_images_per_group,segment_seconds=self.segment_seconds,prompt=self.prompt,prompt_mode=self.prompt_mode)

class Service:
    def __init__(self, model_dir, media_dir, runs_dir):
        self.model_dir=model_dir;self.media_dir=Path(media_dir).resolve()
        self.runs_dir=Path(runs_dir);self.runs_dir.mkdir(parents=True,exist_ok=True)
        self.cv=threading.Condition();self.jobs={};self.current=None;self.closed=False
        self.status='loading';self.error=None;self.reset_pending=False;self.reload_pending=False;self.revision=0
        self.close_error=None
        self.sources={};builtin=self.media_dir/'cafe.mp4'
        if builtin.is_file():
            source=VideoSource(builtin,segment_seconds=15)
            self.sources['cafe']=dict(path=builtin,name='Cafe activity · fixed camera',**source.public())
        self.thread=threading.Thread(target=self._worker,name='sdk-owner',daemon=False);self.thread.start()
    def emit(self, job, event):
        with self.cv:
            # Disk journal preserves reconnect replay without an event-count duration cap.
            directory=self.runs_dir/job.id
            entry=dict(event,event_id=job.event_count+1)
            try:
                directory.mkdir(parents=True,exist_ok=True)
                with (directory/'events.jsonl').open('a') as target:
                    target.write(json.dumps(entry)+'\n')
            except OSError as exc:
                job.journal_failed=True
                raise OSError('Unable to write the session event log. Reload the model before starting a new session.') from exc
            job.event_count+=1
            self.cv.notify_all()
    def wake(self):
        self.revision+=1;self.cv.notify_all()
    def _load_model(self, limits):
        try:
            return Engine(self.model_dir,max_output_words=limits[0],max_output_tokens=limits[1],do_sample=False,repetition_penalty=1.0)
        except Exception as exc:
            print(f'Model load failed: {exc}', file=sys.stderr, flush=True)
            raise RuntimeError('Model load failed. Check the model download and runtime setup, then select Reload model. See the server log for details.') from exc
    def _worker(self):
        signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGTERM,signal.SIGINT})
        engine=None;options=None;session=None;job=None
        load_requested=True
        try:
            seen=-1
            while True:
                with self.cv:
                    if self.closed:break
                    candidate=self.jobs.get(self.current)
                    idle=candidate is None or candidate.state in TERMINAL
                    reload_now=self.reload_pending and idle
                    if reload_now:self.reload_pending=False;load_requested=True
                if load_requested:
                    with self.cv:self.status='loading';self.error=None;self.cv.notify_all()
                    try:
                        if engine is not None:
                            previous=engine;engine=None
                            try:previous.close()
                            except Exception as exc:
                                self.close_error=exc
                                raise
                        desired=options or (35,48)
                        engine=self._load_model(desired)
                        options=desired;session=None
                        with self.cv:self.status='ready';self.error=None;self.reset_pending=False;self.cv.notify_all()
                    except Exception as exc:
                        with self.cv:
                            self.status='error'
                            self.error=('Model cleanup failed. Restart the service before loading again.'
                                        if self.close_error is not None else str(exc))
                            self.cv.notify_all()
                    load_requested=False
                with self.cv:
                    if self.closed:break
                    candidate=self.jobs.get(self.current)
                    if self.status!='ready' or engine is None:
                        self.cv.wait(.2);continue
                    if self.reset_pending and (candidate is None or candidate.state in TERMINAL):
                        try:engine.reset()
                        except Exception as exc:
                            self.status='error';self.error=str(exc)
                        self.reset_pending=False;self.cv.notify_all()
                        if self.status=='error':continue
                    if candidate is None or candidate.state in TERMINAL:
                        self.cv.wait(.2);continue
                    job=candidate;head=job.head;stop=job.stop;started=job.started;revision=self.revision
                try:
                    if job.state=='preparing':
                        source=VideoSource(self.sources[job.source_id]['path'],segment_seconds=job.segment_seconds)
                        desired=(job.max_words,job.max_tokens)
                        if desired!=options:
                            with self.cv:self.status='loading';self.error=None;self.cv.notify_all()
                            previous=engine;engine=None
                            try:previous.close()
                            except Exception as exc:
                                self.close_error=exc
                                raise
                            engine=self._load_model(desired)
                            options=desired
                        session=PlaybackSession(engine,source,job.prompt,lambda e:self.emit(job,e),segment_seconds=job.segment_seconds,
                            video_target_canvas=job.video_target_canvas,video_group_size=job.video_group_size,
                            video_images_per_group=job.video_images_per_group,prompt_mode=job.prompt_mode)
                        with self.cv:self.status='ready';self.reset_pending=False;job.windows=source.windows;job.duration_s=source.duration;job.state='ready';self.cv.notify_all()
                        self.emit(job,dict(kind='ready',duration_s=source.duration,segments=source.segment_count,windows=source.windows,segment_seconds=job.segment_seconds))
                        seen=-1;continue
                    if stop:
                        session.stop()
                        with self.cv:job.state='stopped';self.emit(job,dict(kind='state',state='stopped'))
                        continue
                    if not started:
                        with self.cv:self.cv.wait(.1)
                        continue
                    progress=session.advance(head)
                    if session.done:
                        session.save(self.runs_dir/job.id);result=session.report()
                        with self.cv:job.state='done';job.results=result;self.emit(job,dict(kind='done',stats=result['stats']))
                        continue
                    if not progress and revision==seen:
                        with self.cv:
                            if self.revision==revision:self.cv.wait(.05)
                    seen=revision
                except Exception as exc:
                    with self.cv:
                        job.state='error'
                        job.error=('Model cleanup failed. Restart the service before loading again.'
                                   if self.close_error is not None else str(exc))
                        self.status='error';self.error=job.error
                        if not job.journal_failed:
                            try:
                                self.emit(job,dict(kind='error',message=job.error))
                            except OSError:
                                pass  # Job status remains available without the journal.
                        self.cv.notify_all()
                    # Keep results and the owner alive. Explicit reload closes the
                    # failed engine before creating another one; no automatic replay.
        finally:
            if engine is not None:
                try:
                    engine.close();print(json.dumps({'model_closed':True}),flush=True)
                except Exception as exc:
                    self.close_error=exc;print(json.dumps({'model_close_failed':str(exc)}),flush=True)
    def close(self):
        with self.cv:self.closed=True;self.cv.notify_all()
        # The SDK owner must finish its in-flight call before model destruction.
        # Returning after a timeout would leave native work in a dying process.
        self.thread.join()
        if self.close_error is not None:
            raise RuntimeError('SDK model cleanup failed') from self.close_error


def make_app(service):
    app=Flask(__name__,static_folder='static',static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH']=256*1024*1024
    def get_job(job_id):
        job=service.jobs.get(job_id)
        if job is None:raise ValueError('Unknown job')
        return job
    def body():
        value=request.get_json()
        if not isinstance(value,dict):raise ValueError('Expected a JSON object')
        return value
    @app.errorhandler(ValueError)
    def bad_request(exc):return jsonify(error=str(exc)),400
    @app.errorhandler(FFmpegError)
    def invalid_media(exc):return jsonify(error='Invalid or unsupported video container'),400
    @app.errorhandler(HTTPException)
    def http_error(exc):return jsonify(error=exc.description),exc.code
    @app.get('/')
    def index():return app.send_static_file('index.html')
    @app.get('/api/ready')
    def ready():
        with service.cv:
            return jsonify(status=service.status,error=service.error),200 if service.status=='ready' else 503
    @app.get('/api/config')
    def config():
        with service.cv:
            return jsonify(status=service.status,error=service.error,reset_pending=service.reset_pending,segment_seconds=15,max_words=35,max_tokens=48,max_prompt_words=MAX_PROMPT_WORDS,max_prompt_bytes=MAX_PROMPT_BYTES,
                profiles=[dict(v,prompt=video_question(v['max_words'],v['segment_seconds'])) for v in PROFILES.values()],
                sources=[dict(id=k,**{n:v for n,v in value.items() if n!='path'}) for k,value in service.sources.items()],
                current=service.jobs[service.current].public() if service.current else None)
    @app.get('/api/prompt')
    def prompt_preview():
        try:
            profile=segment_profile(int(request.args.get('segment_seconds','15')))
            words=int(request.args.get('max_words',profile['max_words']))
        except (TypeError,ValueError) as exc:
            raise ValueError('Invalid prompt interval or word ceiling') from exc
        if not 1<=words<=120:raise ValueError('Invalid word ceiling')
        return jsonify(prompt=video_question(words,profile['segment_seconds']),max_prompt_words=MAX_PROMPT_WORDS,max_prompt_bytes=MAX_PROMPT_BYTES)
    @app.get('/media/<source_id>')
    def media(source_id):
        with service.cv:
            source=service.sources.get(source_id)
            if source is None:raise ValueError('Unknown video')
            path=source['path']
        return send_file(path,conditional=True,mimetype='video/mp4')
    @app.post('/api/uploads')
    def upload():
        # Keep two uploaded files at most, and never replace the active source.
        with service.cv:
            uploads=[k for k in service.sources if k!='cafe']
            if len(uploads)>=2:return jsonify(error='Two uploads are already stored. Remove one first.'),409
        filename=unquote(request.headers.get('X-Filename','video.mp4'))
        suffix=Path(filename).suffix.lower()
        if suffix not in ('.mp4','.mov'):raise ValueError('Upload an H.264 MP4 or MOV file')
        source_id=uuid.uuid4().hex;directory=service.media_dir/'uploads';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(source_id+suffix)
        try:
            with path.open('xb') as target:
                total=0
                while True:
                    chunk=request.stream.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>app.config['MAX_CONTENT_LENGTH']:raise ValueError('Upload exceeds 256 MiB')
                    target.write(chunk)
            source=VideoSource(path,segment_seconds=15)
            with service.cv:
                if len([k for k in service.sources if k!='cafe'])>=2:raise ValueError('Upload slots are full')
                service.sources[source_id]=dict(path=path,name=Path(filename).name[:120],**source.public())
            return jsonify(id=source_id,name=Path(filename).name[:120],**source.public()),201
        except Exception:
            path.unlink(missing_ok=True);raise
    @app.delete('/api/uploads/<source_id>')
    def remove_upload(source_id):
        with service.cv:
            current=service.jobs.get(service.current)
            if source_id=='cafe' or source_id not in service.sources:raise ValueError('Unknown upload')
            if current and current.source_id==source_id and current.state not in TERMINAL:
                return jsonify(error='Stop the active video before removing it'),409
            service.sources.pop(source_id)['path'].unlink(missing_ok=True)
        return jsonify(ok=True)
    @app.post('/api/jobs')
    def prepare():
        data=body();profile=segment_profile(data.get('segment_seconds',15))
        request_id=data.get('request_id','')
        if not isinstance(request_id,str) or (request_id and (len(request_id)!=32 or any(c not in '0123456789abcdef' for c in request_id))):raise ValueError('Invalid request identity')
        words=data.get('max_words',profile['max_words']);tokens=data.get('max_tokens',profile['max_tokens'])
        for label,value,limit in [('word',words,120),('token',tokens,512)]:
            if type(value) is not int or not 1<=value<=limit:raise ValueError(f'Invalid {label} ceiling')
        codec={key:data.get(key,default) for key,default in (
            ('video_target_canvas',12),('video_group_size',profile['sampled_frames_per_group']),('video_images_per_group',4))}
        if any(type(v) is not int or not 0<v<=0xffffffff for v in codec.values()):
            raise ValueError('Codec counts must be positive uint32 integers')
        target,group,images=(codec[k] for k in ('video_target_canvas','video_group_size','video_images_per_group'))
        if target%images or group%images:raise ValueError('Canvas and candidate counts must be divisible by images per group')
        if target*144+tokens>=4096:raise ValueError('Canvas budget and output reserve exceed model context')
        prompt=resolve_prompt(data.get('prompt'),max_words=words,segment_seconds=profile['segment_seconds'])
        prompt_mode='default' if data.get('prompt') is None else 'custom'
        with service.cv:
            if service.status!='ready':return jsonify(error=service.error or 'Models are loading'),503
            old=service.jobs.get(service.current)
            if old and old.state not in TERMINAL:return jsonify(error='Stop or reset the active session first'),409
            if data.get('source_id') not in service.sources:raise ValueError('Unknown video')
            seconds=profile['segment_seconds']
            job=Job(uuid.uuid4().hex,data['source_id'],words,tokens,seconds,prompt=prompt,prompt_mode=prompt_mode,request_id=request_id,
                    windows=service.sources[data['source_id']]['windows_by_interval'][str(seconds)],**codec)
            directory=service.runs_dir/job.id;directory.mkdir(parents=True,exist_ok=True)
            (directory/'events.jsonl').touch(exist_ok=False)
            service.jobs[job.id]=job;service.current=job.id
            while len(service.jobs)>3:service.jobs.pop(next(iter(service.jobs)))
            service.wake()
        return jsonify(job.public()),202
    @app.get('/api/jobs/<job_id>')
    def status(job_id):
        with service.cv:return jsonify(get_job(job_id).public())
    @app.post('/api/jobs/<job_id>/clock')
    def clock(job_id):
        data=body();head=data.get('time');sequence=data.get('sequence');playing=data.get('playing',False)
        if type(head) not in (float,int) or not math.isfinite(head) or type(sequence) is not int or sequence<0 or type(playing) is not bool:
            raise ValueError('Invalid playback clock')
        now=time.monotonic()
        with service.cv:
            job=get_job(job_id)
            if job.id!=service.current or job.state in TERMINAL:return jsonify(error='Session is no longer active'),409
            if job.state=='preparing':return jsonify(error='Wait until the video is ready'),409
            if sequence<=job.sequence:return jsonify(ok=True,stale=True)
            duration=job.duration_s if job.duration_s is not None else service.sources[job.source_id]['duration']
            if not 0<=head<=duration+.05 or head<job.head-.05:raise ValueError('Seeking is unsupported. Reset to restart.')
            elapsed=0 if job.clock_received is None else now-job.clock_received
            if head-job.head>elapsed*1.25+.5:raise ValueError('Playback must advance at normal speed')
            job.head=min(duration,max(job.head,float(head)));job.sequence=sequence;job.clock_received=now
            job.started=job.started or playing or head>0
            job.state='running' if playing else 'paused'
            service.wake()
        return jsonify(ok=True)
    @app.post('/api/jobs/<job_id>/stop')
    def stop(job_id):
        with service.cv:
            job=get_job(job_id)
            if job.state not in TERMINAL:job.stop=True;service.wake()
        return jsonify(ok=True),202
    @app.post('/api/reload')
    def reload_model():
        with service.cv:
            if service.close_error is not None:return jsonify(error='Model cleanup failed; restart this service before loading again'),409
            job=service.jobs.get(service.current)
            if job and job.state not in TERMINAL:return jsonify(error='Stop the active session before reloading the model'),409
            if service.status=='loading' or service.reload_pending:return jsonify(status='loading'),202
            service.reload_pending=True;service.status='loading';service.error=None;service.wake()
        return jsonify(status='loading'),202
    @app.post('/api/reset')
    def reset():
        data=body()
        with service.cv:
            if data.get('job_id') is not None and data['job_id']!=service.current:
                return jsonify(error='This session is no longer current'),409
            job=service.jobs.get(service.current)
            if job and job.state not in TERMINAL:job.stop=True
            service.reset_pending=True;service.wake()
        return jsonify(ok=True),202
    @app.get('/api/jobs/<job_id>/events')
    def events(job_id):
        with service.cv:job=get_job(job_id)
        try:cursor=int(request.headers.get('Last-Event-ID',request.args.get('after','0')))
        except ValueError:raise ValueError('Invalid event cursor')
        if not 0<=cursor<=job.event_count:raise ValueError('Invalid event cursor')
        @stream_with_context
        def stream():
            nonlocal cursor
            journal=service.runs_dir/job.id/'events.jsonl'
            # A read failure ends this connection. EventSource reconnects
            # with the last ID actually delivered to the browser.
            try:
                source=journal.open()
            except OSError:
                with service.cv:
                    # The journal can be absent if its first append failed.
                    journal_error=job.error if (job.state=='error' and job.journal_failed
                                                and cursor==job.event_count) else None
                if journal_error is not None:
                    yield f'data: {json.dumps(dict(kind="error",message=journal_error))}\n\n'
                return
            read_id=0
            with source:
                while True:
                    with service.cv:
                        pending=[]
                        read_failed=False
                        write_failed=job.state=='error' and job.journal_failed
                        already_delivered=write_failed and cursor==job.event_count
                        try:
                            # An uncommitted append can leave an incomplete line.
                            while not already_delivered and read_id<job.event_count and len(pending)<256:
                                event=json.loads(source.readline())
                                if event['event_id']!=read_id+1:
                                    raise ValueError('Invalid event sequence')
                                read_id+=1
                                if read_id>cursor:
                                    pending.append(event)
                        except (OSError,ValueError,KeyError):
                            read_failed=True
                        terminal=job.state in TERMINAL and (already_delivered or read_id>=job.event_count)
                        journal_error=job.error if terminal and write_failed else None
                        if not pending and not terminal and not read_failed:
                            service.cv.wait(10)
                    for event in pending:
                        cursor=event['event_id']
                        yield f'id: {cursor}\ndata: {json.dumps(event)}\n\n'
                    if journal_error is not None:
                        # A terminal write failure has no committed event ID.
                        yield f'data: {json.dumps(dict(kind="error",message=journal_error))}\n\n'
                    if terminal or read_failed:return
                    if not pending:yield ': keepalive\n\n'

        return Response(stream(),mimetype='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @app.post('/api/jobs/<job_id>/telemetry')
    def telemetry(job_id):
        data=body()
        if len(json.dumps(data))>16384:raise ValueError('Telemetry is too large')
        with service.cv:
            job=get_job(job_id)
            directory=service.runs_dir/job.id;directory.mkdir(parents=True,exist_ok=True)
            (directory/'browser.json').write_text(json.dumps(data,indent=2)+'\n')
        return jsonify(ok=True)
    return app

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models','--model-dir',dest='model_dir')
    p.add_argument('--protect-process',action='store_true',help='Retired; rejected without changing host policy')
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8080)
    p.add_argument('--media-dir',type=Path,default=Path(__file__).resolve().parent/'media')
    p.add_argument('--runs-dir',type=Path,default=Path('out/web'))
    a=p.parse_args()
    if a.protect_process:p.error('--protect-process is retired; SDK preserves host process policy')
    service=None;server=None;http_thread=None
    stopping=threading.Event();http_errors=[]
    previous={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    first_signal=None
    def terminate(signum,_frame):
        nonlocal first_signal
        if first_signal is None:
            first_signal=signum
            stopping.set()
    for sig in previous:signal.signal(sig,terminate)
    try:
        if stopping.is_set():return
        service=Service(a.model_dir,a.media_dir,a.runs_dir)
        from werkzeug.serving import make_server
        server=make_server(a.host,a.port,make_app(service),threaded=True)
        def serve():
            try:server.serve_forever()
            except BaseException as exc:http_errors.append(exc)
            finally:stopping.set()
        http_thread=threading.Thread(target=serve,name='http-server',daemon=False)
        http_thread.start()
        stopping.wait()
        if http_errors:raise RuntimeError('HTTP service failed') from http_errors[0]
    finally:
        try:
            if http_thread is not None:
                server.shutdown()
                http_thread.join()
            if service is not None:service.close()
        finally:
            if server is not None:server.server_close()
            for sig,handler in previous.items():signal.signal(sig,handler)
if __name__=='__main__':main()
