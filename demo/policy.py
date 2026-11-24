"""Application-owned question wording, segment schedule and playback stepping."""
from __future__ import annotations
import bisect
import codecs
import json
from pathlib import Path
import time

from pandora_mage_vl import WouldBlock

QUESTION = ('Summarize the visible content of this 30-second football broadcast segment. '
    'Write 2-3 concise sentences, targeting 40-50 English words and never exceeding 60 words. '
    'Describe the main actions and meaningful changes in chronological order. '
    'Cover what is actually shown, including match play, interviews, replays, or crowd scenes. '
    'Mention teams, players, scores, or outcomes only when clearly identifiable. '
    'If no major event occurs, briefly describe the ongoing activity. '
    'Return only the summary, without a heading or bullet points.')

def football_question(max_words=60):
    if max_words==60:return QUESTION
    target_high=min(50,max_words);target_low=min(40,max(1,target_high-10))
    return QUESTION.replace('40-50',f'{target_low}-{target_high}').replace('60 words',f'{max_words} words')

VIDEO_QUESTION = ('Summarize the visible content of this 30-second video segment. '
    'Write 2-3 concise sentences, targeting 40-50 English words and never exceeding 60 words. '
    'Describe the main actions and meaningful changes in chronological order. '
    'Cover people entering or leaving, movement, interactions, object handling, and meaningful changes in the surroundings. '
    'Describe only visible actions; do not infer identities, intentions, or wrongdoing. '
    'If no major event occurs, briefly describe the ongoing activity. '
    'Return only the summary, without a heading or bullet points.')

PROFILES = {
    30: dict(segment_seconds=30, sampled_frames_per_group=40, canvases_per_group=4, max_words=60, max_tokens=64),
    15: dict(segment_seconds=15, sampled_frames_per_group=20, canvases_per_group=4, max_words=35, max_tokens=48),
}

def segment_profile(seconds=30):
    if type(seconds) is not int or seconds not in PROFILES:
        raise ValueError('Segment length must be 15 or 30 seconds')
    return dict(PROFILES[seconds])

def video_question(max_words=60, segment_seconds=30):
    segment_profile(segment_seconds)
    if segment_seconds==15:
        high=min(30,max_words);low=min(20,max(1,high-10))
        return VIDEO_QUESTION.replace('30-second','15-second').replace('2-3','1-2').replace('40-50',f'{low}-{high}').replace('60 words',f'{max_words} words')
    if max_words==60:return VIDEO_QUESTION
    target_high=min(50,max_words);target_low=min(40,max(1,target_high-10))
    return VIDEO_QUESTION.replace('40-50',f'{target_low}-{target_high}').replace('60 words',f'{max_words} words')

MAX_PROMPT_WORDS = 200
MAX_PROMPT_BYTES = 2048

def resolve_prompt(prompt=None, *, max_words=60, segment_seconds=30):
    """Resolve an application prompt; custom text is passed unchanged to the SDK."""
    if prompt is None:
        return video_question(max_words, segment_seconds)
    if not isinstance(prompt, str) or not prompt.strip() or '\0' in prompt:
        raise ValueError('Prompt must be non-empty text without NUL characters')
    if len(prompt.split()) > MAX_PROMPT_WORDS:
        raise ValueError(f'Prompt exceeds {MAX_PROMPT_WORDS} words (whitespace-separated)')
    try:
        encoded = prompt.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('Prompt must contain valid UTF-8 text') from exc
    if len(encoded) > MAX_PROMPT_BYTES:
        raise ValueError(f'Prompt exceeds {MAX_PROMPT_BYTES} UTF-8 bytes')
    return prompt

class PlaybackSession:
    """Thread-free policy. One application worker owns this object and the SDK.

    advance() consumes only packets due at the supplied media time. A blocked
    packet is retried unchanged. next() can block for prefill; the caller's media
    clock must continue independently. Publish callbacks run outside the SDK.
    """
    def __init__(self, engine, source, question, publish=lambda event: None, read_capacity=4096, segment_seconds=15, video_target_canvas=None,
                 video_group_size=None, video_images_per_group=None, prompt_mode="custom"):
        self.engine=engine;self.source=source;self.publish=publish;self.question=question
        self.profile=segment_profile(segment_seconds)
        self.codec=dict(video_target_canvas=12 if video_target_canvas is None else video_target_canvas,
            video_group_size=self.profile['sampled_frames_per_group'] if video_group_size is None else video_group_size,
            video_images_per_group=4 if video_images_per_group is None else video_images_per_group)
        self.windows=source.windows;self.prompt_mode=prompt_mode
        self.read_capacity=read_capacity;self.cursor=0;self.planned=0;self.finished=0
        self.eof=False;self.cancelled=False;self.playhead=0.;self.started=None
        self.events=[];self.feed_blocks=0;self.backlog=[];self.last_sample=-1.
        self.answers=['']*len(self.windows)
        self.decoders=[codecs.getincrementaldecoder('utf-8')('strict') for _ in self.answers]
        self.segments=[dict(w,boundary_s=w['end_s'],first_text_s=None,last_text_s=None,finished_s=None) for w in self.windows]
        engine.reset();engine.open_stream(source.metadata,source.extradata,source.keyframes,
            frame_times=source.frame_times,duration=source.duration)
        self._plan()
    def _plan(self):
        while self.planned<len(self.answers) and self.engine.info()['queued_segments']<2:
            i=self.planned;w=self.windows[i];question=self.question
            if self.prompt_mode=='default' and w['duration_s']<self.profile['segment_seconds']:
                question=question.replace(f"{self.profile['segment_seconds']}-second",f"{w['duration_s']:g}-second")
            self.engine.enqueue_window(i,w['start_s'],w['end_s'],question,**self.codec)
            self.planned+=1

    def _emit(self, kind, **values):
        event=dict(kind=kind,elapsed_s=0. if self.started is None else time.monotonic()-self.started,**values)
        self.events.append(event);self.publish(event)
    def start(self):
        if self.started is None:self.started=time.monotonic()
    @property
    def done(self):return self.cancelled or self.finished==len(self.answers)
    def drain(self):
        while True:
            result=self.engine.read_text(self.read_capacity)
            if result is None:break
            i,data=result;text=self.decoders[i].decode(data)
            if text:
                self.answers[i]+=text;t=time.monotonic()-self.started
                if self.segments[i]['first_text_s'] is None and text.strip():self.segments[i]['first_text_s']=t
                self.segments[i]['last_text_s']=t
                self._emit('text',segment_id=i,text=text)
        while True:
            event=self.engine.read_event()
            if event is None:break
            if event['type']==3:
                i=event['segment_id'];tail=self.decoders[i].decode(b'',final=True)
                if tail:self.answers[i]+=tail;self._emit('text',segment_id=i,text=tail)
                self.finished+=1;self.segments[i]['finished_s']=time.monotonic()-self.started
            self._emit('sdk_event',**event)
    def advance(self, media_time):
        if self.done:return False
        self.start()
        if media_time<self.playhead or not 0<=media_time<=self.source.duration:
            raise ValueError('Playback time must advance monotonically within the video')
        self.playhead=media_time;fed=False
        elapsed=time.monotonic()-self.started
        if elapsed-self.last_sample>=.1:
            delivered=self.source.packets[self.cursor-1].due if self.cursor else 0.
            self.backlog.append(dict(elapsed_s=elapsed,playhead_s=media_time,
                closed_unfinished=max(0,bisect.bisect_right([w['end_s'] for w in self.windows],media_time)-self.finished),
                feed_lag_s=max(0.,media_time-delivered),queued_segments=self.engine.info()['queued_segments']))
            self.last_sample=elapsed
        batch=0
        while self.cursor<len(self.source.packets) and (media_time>=self.source.duration or self.source.packets[self.cursor].due<=media_time) and batch<16:
            p=self.source.packets[self.cursor]
            # Never consume packets for a window before its plan is submitted.
            frame=self.source.packet_indices[p.pts]
            planned_end=bisect.bisect_left(self.source.frame_times,self.windows[self.planned-1]['end_s'])
            if frame>=planned_end:break
            try:self.engine.feed(p.data,p.pts,p.dts,p.duration,p.flags)
            except WouldBlock:self.feed_blocks+=1;break
            self.cursor+=1;fed=True;batch+=1
        if not self.eof and self.cursor==len(self.source.packets) and media_time>=self.source.duration:
            self.engine.finish_input();self.eof=True;fed=True
        before=self.engine.stats();before_info=self.engine.info()
        try:self.engine.next(media_time=media_time)
        except WouldBlock:pass
        self.drain();self._plan()
        changed=before!=self.engine.stats() or before_info!=self.engine.info()
        return fed or changed

    def stop(self):
        if self.done:return
        self.start()
        pending={i for i in range(self.planned) if self.segments[i]['finished_s'] is None}
        for i in sorted(pending):
            self.engine.abort(i)
        while pending:
            previous=len(self.events)
            self.drain()
            pending.difference_update(e['segment_id'] for e in self.events[previous:]
                                      if e['kind']=='sdk_event' and e['type']==4)
            if pending and not self.engine.next():
                raise RuntimeError('Cancellation did not drain the pending output')
        self.engine.reset();self.cancelled=True
        self._emit('stopped')
    def report(self):
        return dict(profile=self.profile,codec=self.codec,windows=self.windows,backlog=self.backlog,segments=self.segments,events=self.events,accepted_packets=self.cursor,
                    feed_blocks=self.feed_blocks,playhead_s=self.playhead,cancelled=self.cancelled,
                    stats=self.engine.stats())
    def save(self, output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        for i,answer in enumerate(self.answers):(output/f'segment_{i:02d}.answer.txt').write_text(answer+'\n')
        (output/'timeline.json').write_text(json.dumps(self.report(),indent=2)+'\n')
