#version 330
uniform sampler2D source;uniform vec2 direction;
in vec2 uv;out vec4 color;
void main(){
    color=texture(source,uv)*.227027;
    color+=(texture(source,uv+direction*1.384615)+texture(source,uv-direction*1.384615))*.316216;
    color+=(texture(source,uv+direction*3.230769)+texture(source,uv-direction*3.230769))*.070270;
}
