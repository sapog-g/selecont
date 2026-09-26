/* Approved B artwork mapped onto two deformable annular meshes.
 * Rounded shading comes from the original rendered material, not an SVG stroke.
 * Both meshes persist through the move; the pale one follows and joins the blue.
 * The final boundary is mathematically circular: inner 866, outer 986, centre 0,0.
 */
class RingMorph {
  constructor(canvas) {
    this.canvas=canvas;
    this.gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:true,preserveDrawingBuffer:true});
    this.ready=this.initialize();
  }
  async initialize(){
    if(!this.gl)throw new Error('Для перехода колец нужен WebGL.');
    const gl=this.gl;
    const vertex=`attribute vec2 a_uv; attribute vec2 a_start; attribute vec2 a_polar;
      uniform float u_progress; uniform float u_angle; uniform float u_pale;
      varying vec2 v_uv; varying float v_radial; varying float v_theta;
      void main(){
        float t=u_progress;
        float theta=a_polar.x+u_angle;
        float r=mix(866.0,986.0,a_polar.y);
        vec2 target=vec2(cos(theta),sin(theta))*r;
        vec2 p=mix(a_start,target,t);
        gl_Position=vec4(p.x/800.0-1.0,1.0-p.y/450.0,0.,1.);
        v_uv=a_uv; v_radial=a_polar.y; v_theta=a_polar.x;
      }`;
    const fragment=`precision highp float; uniform sampler2D u_texture; uniform float u_alpha; uniform float u_part;
      varying vec2 v_uv; varying float v_radial; varying float v_theta;
      void main(){
        // The pale front arc stays over the blue at the reference crossing.
        // Feather the arc ends away from intersections; never switch whole-ring order.
        float front=u_part>.5?smoothstep(-.12,.12,cos(v_theta+.5)):1.0;
        vec4 tex=texture2D(u_texture,v_uv);
        float edge=smoothstep(0.,.015,v_radial)*smoothstep(0.,.015,1.-v_radial);
        float alpha=u_alpha*edge*front; gl_FragColor=vec4(tex.rgb*alpha,alpha);
      }`;
    const compile=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s};
    this.program=gl.createProgram();gl.attachShader(this.program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(this.program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(this.program);if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(this.program));
    gl.useProgram(this.program);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
    this.uniforms={};for(const k of ['progress','angle','pale','alpha','part','texture'])this.uniforms[k]=gl.getUniformLocation(this.program,'u_'+k);
    this.attributes={};for(const k of ['uv','start','polar'])this.attributes[k]=gl.getAttribLocation(this.program,'a_'+k);
    const geometry=await fetch('ring-geometry.json?v=20260923-r4').then(r=>r.json());this.meshes={};
    await Promise.all(['blue','pale'].map(async(name)=>{
      const img=new Image();img.src=`assets/ring-${name}.png`;await img.decode();
      const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      const data=[];const g=geometry[name];const N=g.radii.length,M=24;
      const add=(i,j)=>{
        const theta=i/N*Math.PI*2,v=j/M,rr=g.radii[i%N],r=rr[0]*(1-v)+rr[1]*v;
        const sx=g.center[0]+Math.cos(theta)*r,sy=g.center[1]+Math.sin(theta)*r;
        // Register the isolated B surfaces with the approved open composition.
        const start=g.start[i%N];
        const x=start[0][0]*(1-v)+start[1][0]*v,y=start[0][1]*(1-v)+start[1][1]*v;
        data.push(sx/1254,sy/1254,165+x*1270/1254,-245+y*1270/1254,theta,v);
      };
      for(let i=0;i<N;i++)for(let j=0;j<M;j++){add(i,j);add(i+1,j);add(i,j+1);add(i,j+1);add(i+1,j);add(i+1,j+1)}
      const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.STATIC_DRAW);
      this.meshes[name]={buffer,texture,count:data.length/6};
    }));
    this.loaded=true;this.draw(0,0);
  }
  draw(progress,angle=0){
    if(!this.loaded)return;
    if(this.lastProgress===progress && this.lastAngle===angle)return;
    this.lastProgress=progress;this.lastAngle=angle;
    const gl=this.gl;gl.viewport(0,0,1600,900);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(this.program);
    const paleProgress=Math.max(0,progress-.12*Math.sin(Math.PI*progress));
    const paleAlpha=.9;
    const draw=(name,p,alpha,part)=>{
      const mesh=this.meshes[name];gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);
      ['uv','start','polar'].forEach((k,i)=>{const a=this.attributes[k];gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,2,gl.FLOAT,false,24,i*8)});
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,mesh.texture);gl.uniform1i(this.uniforms.texture,0);
      gl.uniform1f(this.uniforms.progress,p);gl.uniform1f(this.uniforms.angle,angle);gl.uniform1f(this.uniforms.pale,name==='pale'?1:0);gl.uniform1f(this.uniforms.alpha,alpha);gl.uniform1f(this.uniforms.part,part);gl.drawArrays(gl.TRIANGLES,0,mesh.count);
    };
    const join=Math.max(0,Math.min(1,(progress-.32)/.6));
    const frontAlpha=.52*(1-join*join*(3-2*join));
    draw('pale',paleProgress,paleAlpha,0);
    draw('blue',progress,1,0);
    if(frontAlpha>0)draw('pale',paleProgress,frontAlpha,1);
  }
}
window.RingMorph=RingMorph;
