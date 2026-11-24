"""Application window scheduling over the public SDK container transport."""
import bisect
import math
from pandora_mage_vl import VideoSource as ContainerSource

class VideoSource(ContainerSource):
    def __init__(self,path,max_bytes=256*1024*1024,segment_seconds=15):
        if type(segment_seconds) is not int or segment_seconds not in (15,30):
            raise ValueError('Segment length must be 15 or 30 seconds')
        super().__init__(path,max_bytes=max_bytes)
        self.windows=self.windows_for(segment_seconds)
        self.segment_count=len(self.windows)
        # Packet display order is independent from DTS delivery order (B frames).
        pts=sorted(p.pts for p in self.packets)
        self.packet_indices={p:i for i,p in enumerate(pts)}

    def windows_for(self,seconds):
        windows=[]
        for i in range(math.ceil(self.duration/seconds)):
            start=float(i*seconds);end=min(float((i+1)*seconds),self.duration)
            first=bisect.bisect_left(self.frame_times,start);last=bisect.bisect_left(self.frame_times,end)
            if first==last:raise ValueError('A selected time window contains no video frames')
            windows.append(dict(id=i,start_s=start,end_s=end,duration_s=end-start))
        return windows

    def public(self):
        return dict(duration=self.duration,segments=self.segment_count,has_audio=self.has_audio,
                    windows_by_interval={str(n):self.windows_for(n) for n in (15,30)})
