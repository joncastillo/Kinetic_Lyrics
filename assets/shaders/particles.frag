#version 330
in vec2 uv;in vec3 tint;in float opacity;in float blur;
uniform int effect;uniform vec2 resolution;uniform vec2 anchors[16];uniform int anchor_count;
out vec4 color;
void main(){
    float r=length(uv);float shape;
    if(effect==3){if(uv.y>1.-abs(uv.x)*2.)discard;shape=.9;}
    else if(effect==5){shape=smoothstep(1.,.8,abs(uv.x))*smoothstep(1.,.85,abs(uv.y));}
    else if(effect==4){shape=exp(-r*r*7.)+.3*exp(-pow((r-.65)*12.,2.));}
    else{shape=exp(-r*r*(5.+blur));}
    if(r>1.4)discard;
    float distance_to_lyric=10.;
    for(int i=0;i<16;i++){if(i>=anchor_count)break;vec2 a=vec2(anchors[i].x,resolution.y-anchors[i].y);distance_to_lyric=min(distance_to_lyric,length(gl_FragCoord.xy-a)/resolution.y);}
    float readable=.15+.85*smoothstep(.035,.14,distance_to_lyric);
    float energy=readable*shape*opacity*(effect==1?1.1:2.2);
    color=vec4(tint*energy,energy);
}
