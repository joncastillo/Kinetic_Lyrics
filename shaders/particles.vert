#version 330
uniform vec2 resolution;
uniform vec2 anchors[16];
uniform int anchor_count;
uniform float time;
uniform float duration;
uniform float scene_seed;
uniform int effect;
uniform vec3 ink;
uniform vec3 accent;
out vec2 uv;
out vec3 tint;
out float opacity;
out float blur;
const float PI=3.14159265;
float hash(float p){return fract(sin(p*127.1+scene_seed*311.7)*43758.5453);}
vec3 flow(float id,float t){
    float a=hash(id+1.)*6.28318;
    float life=fract(t*(.16+hash(id+3.)*.12)+hash(id+4.));
    float r=life*(3.+hash(id+5.)*4.);
    vec2 anchor=anchors[int(mod(id,float(anchor_count)))];
    float aspect=resolution.x/resolution.y;
    vec3 origin=vec3((anchor.x/resolution.x*2.-1.)*aspect*2.33,(1.-anchor.y/resolution.y*2.)*2.33,0.);
    vec3 p;
    if(effect==0){ // spherical ignition / turbulence
        float z=hash(id+7.)*2.-1.;float radial=sqrt(1.-z*z);
        p=origin+vec3(cos(a)*radial,sin(a)*radial,z)*r;
        p.y-=life*life*1.8;
        p+=.18*vec3(sin(t*2.+id),cos(t*1.7+id),sin(t+id));
    }else if(effect==1){ // layered drifting volume
        p=vec3((hash(id+2.)*2.-1.)*aspect*4.,(life*2.-1.)*4.,hash(id+8.)*7.-3.5);
        p.x+=sin(t*.4+id)*.5;p.z+=cos(t*.3+id)*.3;
    }else if(effect==2){ // helical ribbons in 3D, attached to lyric origins
        float angle=a+t*(.5+hash(id+2.)*.5);
        p=origin+vec3(cos(angle)*r,sin(angle*1.3)*r*.65,sin(angle*.7)*2.4);
    }else if(effect==3){ // crystalline burst with gravity
        p=origin+vec3(cos(a)*r,sin(a)*r-life*life*2.,(hash(id+8.)*2.-1.)*r*.65);
    }else if(effect==4){ // elliptical orbital constellation
        float angle=a+t*(.25+hash(id+3.)*.4);float r2=.7+hash(id+2.)*3.5;
        p=vec3(cos(angle)*r2*aspect,sin(angle)*r2*.6,sin(angle+id)*2.4);
        p.y+=sin(t*.35+id)*.25;
    }else{ // tumbling confetti through a deep volume
        p=vec3((hash(id+2.)*2.-1.)*aspect*3.7,(1.-life*2.)*4.,hash(id+8.)*6.-3.);
        p.x+=sin(t+id)*.65;p.z+=sin(t*.6+id)*.4;
    }
    p.z=clamp(p.z,-4.,3.1);
    return p;
}
mat3 rotate3(vec3 a){
    float cx=cos(a.x),sx=sin(a.x),cy=cos(a.y),sy=sin(a.y),cz=cos(a.z),sz=sin(a.z);
    return mat3(cz,-sz,0,sz,cz,0,0,0,1)*mat3(cy,0,sy,0,1,0,-sy,0,cy)*mat3(1,0,0,0,cx,-sx,0,sx,cx);
}
void main(){
    vec2 corners[6]=vec2[6](vec2(-1,-1),vec2(1,-1),vec2(1,1),vec2(-1,-1),vec2(1,1),vec2(-1,1));
    uv=corners[gl_VertexID];
    float raw=float(gl_InstanceID);float segment=effect==2?mod(raw,16.):0.;
    float id=effect==2?floor(raw/16.):raw;
    float t=max(0.,time-segment*.028);
    vec3 p=flow(id,t);float depth=5.-p.z;
    float life=fract(t*(.16+hash(id+3.)*.12)+hash(id+4.));
    float envelope=smoothstep(0.,.3,time)*smoothstep(0.,.5,duration-time);
    opacity=pow(max(0.,sin(PI*life)),.7)*envelope;
    tint=mix(accent,ink,hash(id+12.)*.75);
    float size=.009+hash(id+13.)*.021;
    blur=0.;
    if(effect==1){blur=abs(p.z)*.45;size*=2.+blur*2.;opacity*=.4;}
    if(effect==2){size*=.8;opacity*=pow(1.-segment/16.,1.5);}
    if(effect==3||effect==5){
        size*=effect==3?2.2:1.8;
        mat3 rot=rotate3(vec3(id*.7+t,id+t*1.7,id*.4+t*.8));
        p+=rot*vec3(uv*size,0.);
        vec3 n=rot*vec3(0,0,1);
        float light=.3+.7*abs(dot(n,normalize(vec3(-.4,.7,1.))));
        tint*=light;
        if(effect==5)tint=mix(tint,vec3(.95,.65,.35),hash(id+14.)*.45);
    }else{
        vec3 velocity=flow(id,t+.01)-flow(id,t);
        vec2 dir=normalize(velocity.xy+vec2(.0001));
        if(effect==0||effect==2){
            float stretch=effect==0?3.:2.;
            p.xy+=dir*uv.x*size*stretch+vec2(-dir.y,dir.x)*uv.y*size;
        }else p.xy+=uv*size;
    }
    depth=5.-p.z;
    float f=2.144507;float near=.1,far=30.;
    gl_Position=vec4(p.x*f/(resolution.x/resolution.y),p.y*f,(far+near)/(far-near)*depth-2.*far*near/(far-near),depth);
}
