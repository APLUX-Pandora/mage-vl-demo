"""Finite H.264 container transport; native SDK owns codec sampling and packing."""
from dataclasses import dataclass
from fractions import Fraction
import bisect
import hashlib
from pathlib import Path
import struct
import av

@dataclass(frozen=True)
class MediaPacket:
    data: bytes
    pts: int
    dts: int
    duration: int
    flags: int
    due: float

def codec_parameters(target=None, group=None, images=None):
    values = (12 if target is None else target, 20 if group is None else group,
              4 if images is None else images)
    for name, value in zip(('video_target_canvas','video_group_size','video_images_per_group'), values):
        if type(value) is not int or not 0 < value <= 0xffffffff:
            raise ValueError(name + ' must be a positive uint32 integer (not bool)')
    target, group, images = values
    if target % images or group % images:
        raise ValueError('video_target_canvas and video_group_size must be divisible by video_images_per_group')
    return dict(target_canvas=target, group_size=group, images_per_group=images)

class VideoSource:
    """Read bounded compressed packets and real presentation times, without transcoding."""
    def __init__(self, path, max_bytes=256*1024*1024):
        path=Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
            raise ValueError('Video must be a nonempty local file up to 256 MiB')
        if path.suffix.lower() not in ('.mp4','.mov'):
            raise ValueError('Use an H.264 MP4 or MOV file; H.265 is unsupported')
        self.path=path;self.packets=[];self.keyframes=[]
        with av.open(str(path)) as container:
            self.has_audio=bool(container.streams.audio)
            if len(container.streams.video)!=1:
                raise ValueError('Exactly one video stream is required')
            s=container.streams.video[0];c=s.codec_context
            if c.name!='h264':
                raise ValueError('Only H.264 is supported; H.265 is unsupported')
            if not s.time_base or not c.extradata:
                raise ValueError('Video time base and H.264 metadata are required')
            rate=s.average_rate or s.guessed_rate
            if not rate or rate<=0:
                raise ValueError('Video needs a positive nominal frame rate')
            rate=Fraction(rate)
            sar=c.sample_aspect_ratio or Fraction(0,1)
            self.extradata=bytes(c.extradata);initial=None;total=0;key_pts=[]
            for packet in container.demux(s):
                if not packet.size:continue
                if packet.pts is None or packet.dts is None:
                    raise ValueError('Every video packet needs PTS and DTS')
                if initial is None:initial=packet.dts
                data=bytes(packet);total+=len(data)
                if total+(len(self.packets)+1)*64>max_bytes:
                    raise ValueError('Compressed packet/timing buffers exceed 256 MiB')
                due=float((packet.dts-initial)*s.time_base)
                if self.packets and due<self.packets[-1].due:
                    raise ValueError('Nonmonotonic decode timestamps are unsupported')
                self.packets.append(MediaPacket(data,packet.pts,packet.dts,packet.duration or 0,
                                               int(packet.is_keyframe),due))
                if packet.is_keyframe:key_pts.append(packet.pts)
            ordered=sorted(self.packets,key=lambda p:p.pts)
            pts=[p.pts for p in ordered]
            if not pts or any(b<=a for a,b in zip(pts,pts[1:])):
                raise ValueError('Distinct presentation timestamps are required')
            if s.frames and s.frames!=len(pts):
                raise ValueError('Container frame count disagrees with timestamped packets')
            start=pts[0]
            self.frame_times=[float((p-start)*s.time_base) for p in pts]
            self.keyframes=[bisect.bisect_left(pts,p) for p in sorted(set(key_pts))]
            if not self.keyframes or self.keyframes[0]!=0:
                raise ValueError('Video must begin with a decodable keyframe')
            tail=float(ordered[-1].duration*s.time_base) if ordered[-1].duration>0 else (
                self.frame_times[-1]-self.frame_times[-2] if len(pts)>1 else float(1/rate))
            self.duration=self.frame_times[-1]+tail
            self.metadata=dict(codec=1,width=c.width,height=c.height,
                fps_num=rate.numerator,fps_den=rate.denominator,
                time_base_num=s.time_base.numerator,time_base_den=s.time_base.denominator,
                stream_start_pts=start,frame_count=len(pts),
                color_primaries=c.color_primaries,color_transfer=c.color_trc,color_matrix=c.colorspace,
                full_range=-1 if c.color_range==0 else int(c.color_range==2),
                sample_aspect_num=sar.numerator,sample_aspect_den=sar.denominator)
    def fingerprint(self):
        h=hashlib.sha256()
        for p in self.packets:
            h.update(struct.pack('<qqqII',p.pts,p.dts,p.duration,p.flags,len(p.data)));h.update(p.data)
        return dict(metadata=self.metadata,extradata_sha256=hashlib.sha256(self.extradata).hexdigest(),
                    keyframes=self.keyframes,packets=len(self.packets),packet_stream_sha256=h.hexdigest())
