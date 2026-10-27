"""Schedule glyph formation before a line, using the aligned vocal pace."""
from dataclasses import dataclass
from statistics import median


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


def line_arrivals(data,pairs,catalog,speed,intensity,lead_in):
    """Enter together within the requested lead-in, never extend it for speed.

    Slow particle motion may use the full entrance window. It must not bring
    future lyrics on screen several seconds earlier or reorder line starts.
    """
    arrivals=[]
    for line,(entrance,_) in zip(data,pairs):
        effect=catalog['entrance'].get(entrance) if intensity>0 else None
        words=line['words'];cue=words[0]['start']
        spacings=[b['start']-a['start'] for a,b in zip(words,words[1:]) if .12<=b['start']-a['start']<=2.]
        pace=median(spacings or [max(.12,words[0]['end']-cue)])
        scale=max(.8,min(1.8,pace/.5))
        base=(1.8 if effect and effect.trajectory=='grow' else .8 if effect else .24)
        duration=base*scale/max(.2,speed)
        start=max(0.,cue-lead_in)
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
                cost=score+math.log(box[2]*box[3]/max(1,boxes[index][2]*boxes[index][3]))
                current=dict(active);current[index]=box
                positions=assigned.copy();positions[index]=box
                key=tuple(sorted(current.items()))
                if key not in survivors or survivors[key][0]<cost:survivors[key]=(cost,current,positions)
        if not survivors:
            lanes,count=reading_lanes(starts,ends)
            return [(x,y+lanes[i]*(h//count),w,max(1,h//count-3)) for i,(x,y,w,h) in enumerate(boxes)]
        beam=sorted(survivors.values(),key=lambda item:item[0],reverse=True)[:48]
    return beam[0][2]
