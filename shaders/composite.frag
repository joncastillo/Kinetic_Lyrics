#version 330
uniform sampler2D source;uniform sampler2D glow;
in vec2 uv;out vec4 color;
void main(){
    vec3 hdr=texture(source,uv).rgb+texture(glow,uv).rgb*.85;
    vec3 rgb=vec3(1.)-exp(-hdr*1.15);
    float alpha=clamp(max(rgb.r,max(rgb.g,rgb.b)),0.,1.);
    color=vec4(alpha>.0001?rgb/alpha:vec3(0.),alpha);
}
