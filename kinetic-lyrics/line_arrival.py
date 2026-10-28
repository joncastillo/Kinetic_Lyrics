"""Schedule glyph formation before a line with one consistent arrival length."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Arrival:
    start: float
    finish: float

    def progress(self, time):
        if time < self.start:
            return 0.
        if self.finish <= self.start:
            return 1.
        fraction = max(0., min(1., (time-self.start)/(self.finish-self.start)))
        return fraction*fraction*(3-2*fraction)


MOTION_ARRIVAL={'directed':.9,'slide':.9,'fade':.9,'highlight':.9,'karaoke':.9,'none':0.}
PARTICLE_ARRIVAL=.9
MAX_LEAD=2.


def line_arrivals(data,pairs,catalog,speed,intensity,lead_in,motions=None):
    """Enter together within the requested lead-in, never extend it for speed.

    Slow particle motion may use the full entrance window. It must not bring
    future lyrics on screen several seconds earlier or reorder line starts.
    Every particle recipe gets the same window (audited pacing aligns their
    milestones inside it); without one, the line's word motion sets the length.
    """
    arrivals=[]
    for index,(line,(entrance,_)) in enumerate(zip(data,pairs)):
        effect=catalog['entrance'].get(entrance) if intensity>0 else None
        cue=line['words'][0]['start']
        motion=max((MOTION_ARRIVAL.get(m,.24) for m in motions[index]),default=.24) if motions else .24
        line_speed=speed[index] if isinstance(speed,(list,tuple)) else speed
        duration=(PARTICLE_ARRIVAL if effect else motion)/max(.2,line_speed)
        previous_end=data[index-1]['words'][-1]['end'] if index else 0.
        allowance=max(lead_in,min(MAX_LEAD,duration+.04)) if lead_in>0 else 0.
        start=max(0.,cue-allowance)
        if allowance>lead_in:start=max(start,min(previous_end,cue-lead_in))
        available=max(0.,cue-.04-start)
        arrivals.append(Arrival(start,start+min(duration,available)))
    return arrivals


def reading_lanes(starts, ends):
    """Keep overlapping incoming, sung and outgoing lines in separate bands."""
    occupied = []
    lanes = [0]*len(starts)
    for index in sorted(range(len(starts)),key=lambda i:(starts[i],i)):
        available = next((lane for lane,end in enumerate(occupied) if end <= starts[index]),None)
        if available is None:
            available = len(occupied)
            occupied.append(ends[index])
        else:
            occupied[available] = ends[index]
        lanes[index] = available
    return lanes,max(1,len(occupied))


def floral_word_progress(time,word,next_start,speed):
    """Only the sung word grows; finish before the next word can start growing."""
    start=word['start']
    end=max(start+.01,min(word['end'],next_start))
    duration=min(end-start,max(.15,(end-start)*.65/max(.2,speed)))
    return Arrival(start,start+duration).progress(time)


def reading_regions(starts,ends,boxes):
    """Reserve large static regions; split only where concurrent text overlaps.

    A bounded beam keeps alternate placements for an upcoming line, avoiding a
    full-height block that leaves its neighbor nowhere readable to appear.
    """
    import math
    if not boxes:return []
    def overlaps(a,b):
        return a[0]<b[0]+b[2]+2 and a[0]+a[2]+2>b[0] and a[1]<b[1]+b[3]+2 and a[1]+a[3]+2>b[1]
    def candidates(box):
        x,y,w,h=box
        result=[box]
        for count in (2,3):
            gap=max(4,round(min(w,h)*.025))
            bh=max(1,(h-gap*(count-1))//count)
            bw=max(1,(w-gap*(count-1))//count)
            result.extend((x,y+slot*(bh+gap),w,bh) for slot in range(count))
            result.extend((x+slot*(bw+gap),y,bw,h) for slot in range(count))
        return list(dict.fromkeys(result))
    beam=[(0.,{},[None]*len(boxes))]
    for index in sorted(range(len(starts)),key=lambda i:(starts[i],i)):
        survivors={}
        for score,active,assigned in beam:
            active={i:b for i,b in active.items() if ends[i]>starts[index]}
            for box in candidates(boxes[index]):
                if any(overlaps(box,other) for other in active.values()):continue
                behind=sum(1 for other in active.values() if not (box[1]>=other[1]+other[3]-4 or box[0]>=other[0]+other[2]-4))
                cost=score+math.log(box[2]*box[3]/max(1,boxes[index][2]*boxes[index][3]))-.6*behind
                current=dict(active);current[index]=box
                positions=assigned.copy();positions[index]=box
                key=tuple(sorted(current.items()))
                if key not in survivors or survivors[key][0]<cost:survivors[key]=(cost,current,positions)
        if not survivors:
            lanes,count=reading_lanes(starts,ends)
            return [(x,y+lanes[i]*(h//count),w,max(1,h//count-3)) for i,(x,y,w,h) in enumerate(boxes)]
        beam=sorted(survivors.values(),key=lambda item:item[0],reverse=True)[:48]
    return beam[0][2]
