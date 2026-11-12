import * as THREE from './vendor/three.module.js';

export function createScene(stage) {
  const ascii = stage.querySelector('#ascii');
  const ctx = ascii.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let renderer, scene, camera, knot, halo, stars, ribbon, width=600, height=550;
  let mode='space', theme='dark', inView=true, disposed=false, lastAscii=-1, lastTime=-1;
  const resources=[];
  const pointer={x:0,y:0};
  const view={zoom:1,x:0,y:0,inspecting:false};
  const touches=new Map();
  let visualTime=null,lastInputTime=null;
  const rng=(()=>{let s=91241;return()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};})();
  const uniforms={uTime:{value:0},uLight:{value:0},uMode:{value:0},uReveal:{value:0},uPointer:{value:new THREE.Vector2()},uDpr:{value:1.5}};
  const track=r=>{resources.push(r);return r;};

  function center(a) {
    return new THREE.Vector3((1.07+.34*Math.cos(3*a))*Math.cos(2*a), (1.07+.34*Math.cos(3*a))*Math.sin(2*a),.57*Math.sin(3*a));
  }
  function onTube(a,b,r=.19) {
    const p=center(a),t=center(a+.001).sub(p).normalize();
    const n=new THREE.Vector3(p.x,p.y,p.z*.5).normalize();
    const side=new THREE.Vector3().crossVectors(t,n).normalize();
    const normal=new THREE.Vector3().crossVectors(side,t).normalize();
    return p.addScaledVector(normal,Math.cos(b)*r).addScaledVector(side,Math.sin(b)*r*.8);
  }

  const asciiPoints=[];
  for(let i=0;i<5100;i++) {
    const a=rng()*Math.PI*2,b=rng()*Math.PI*2;
    asciiPoints.push(onTube(a,b,.20));
  }
  function init() {
    try {
      renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});
      renderer.setPixelRatio(Math.min(devicePixelRatio,1.6));
      renderer.setClearColor(0x000000,0);
      renderer.outputColorSpace=THREE.SRGBColorSpace;
      renderer.domElement.className='webgl';
      renderer.domElement.setAttribute('aria-hidden','true');
      stage.prepend(renderer.domElement);
      renderer.domElement.addEventListener('webglcontextlost',onLost);
      renderer.domElement.addEventListener('webglcontextrestored',onRestored);
      scene=new THREE.Scene();
      camera=new THREE.PerspectiveCamera(36,width/height,.1,40);
      camera.position.set(0,0,6.3);
      knot=new THREE.Group();scene.add(knot);

      // Silken bands around a deterministic knot. No lights, shadows or postprocessing passes.
      const count=19200, positions=new Float32Array(count*3), seeds=new Float32Array(count);
      for(let i=0;i<count;i++) {
        const a=rng()*Math.PI*2,b=rng()*Math.PI*2;
        const p=onTube(a,b,.19+(rng()-.5)*.035);
        positions.set([p.x,p.y,p.z],i*3);seeds[i]=rng();
      }
      const geometry=track(new THREE.BufferGeometry());
      geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));
      geometry.setAttribute('aSeed',new THREE.BufferAttribute(seeds,1));
      const material=track(new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,blending:THREE.NormalBlending,
        vertexShader:`uniform float uTime;uniform float uDpr;uniform float uMode;uniform vec2 uPointer;attribute float aSeed;varying float vSeed;varying float vDepth;varying float vFlow;
          void main(){vec3 p=position;float phase=aSeed*6.283+uTime*(.85+uMode*.65);float flow=fract(phase/6.283);float wave=sin(phase+p.x*3.2+p.y*2.1);p+=normalize(p)*(wave*.032+flow*flow*.08);vec2 pull=uPointer*mix(.18,.55,uMode);p.xy+=pull*(.35+sin(phase)*.35);float spread=uMode;p+=vec3(sin(aSeed*73.+uTime*.55),cos(aSeed*91.+uTime*.72),sin(aSeed*21.+uTime*.4))*spread*.42;vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;gl_PointSize=(.7+aSeed*1.8+smoothstep(.72,1.,flow)*2.4)*uDpr*(5.6/-mv.z);vSeed=aSeed;vDepth=clamp((-mv.z-4.)/4.,0.,1.);vFlow=flow;}`,
        fragmentShader:`uniform float uLight;uniform float uReveal;varying float vSeed;varying float vDepth;varying float vFlow;
          void main(){vec2 q=gl_PointCoord-.5;float d=length(q);float core=1.-smoothstep(.02,.18,d);float halo=1.-smoothstep(.12,.5,d);float alpha=(core*.85+halo*.42)*(.34+vSeed*.62)*(1.-vDepth*.58);float pulse=smoothstep(.68,1.,vFlow);vec3 color=mix(vec3(.28,.72,.76),vec3(.86,.98,.58),pow(vFlow,.65));color+=vec3(.55,.95,.42)*pulse*.55;color=mix(color,vec3(.16,.42,.32),uLight*.72);gl_FragColor=vec4(color,alpha*(1.-uReveal));}`
      }));
      ribbon=new THREE.Points(geometry,material);knot.add(ribbon);

      // Fine continuous filaments make the shape legible even on small screens.
      for(let j=0;j<24;j++) {
        const pts=[];
        for(let k=0;k<=620;k++) pts.push(onTube(k/620*Math.PI*2,j/24*Math.PI*2,.194));
        const g=track(new THREE.BufferGeometry().setFromPoints(pts));
        const m=track(new THREE.LineBasicMaterial({color:j%5===0?0xcdf78b:0x80d6cf,transparent:true,opacity:j%5===0?.27:.13,depthWrite:false}));
        const line=new THREE.Line(g,m);line.userData.filament=true;knot.add(line);
      }
      // Dim constellations support the sculpture without covering the text.
      const starPos=new Float32Array(180*3);
      for(let i=0;i<180;i++){starPos[i*3]=(rng()-.5)*7;starPos[i*3+1]=(rng()-.5)*6;starPos[i*3+2]=-1.5-rng()*3;}
      stars=new THREE.Points(track(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(starPos,3))),track(new THREE.PointsMaterial({size:.014,color:0xadc7bd,transparent:true,opacity:.25,depthWrite:false})));
      scene.add(stars);

      const haloMaterial=track(new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,
        vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
        fragmentShader:`varying vec2 vUv;uniform float uTime;uniform float uLight;
          float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
          float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+vec2(1.,1.)),f.x),f.y);}
          void main(){vec2 p=(vUv-.5)*2.;float t=uTime*.045;float n=noise(p*2.4+vec2(t,-t));float q=noise(p*4.6+n*1.4-t);float a=exp(-dot(p,p)*3.1)*(.12+.13*q);vec3 c=mix(vec3(.12,.42,.39),vec3(.40,.51,.20),n);gl_FragColor=vec4(c,a*(1.-uLight*.65));}`
      }));
      halo=new THREE.Mesh(track(new THREE.PlaneGeometry(7,7)),haloMaterial);halo.position.z=-2;scene.add(halo);
      stage.dataset.renderer='webgl';
    }catch(err){stage.dataset.renderer='fallback';stage.dataset.fallbackReason=String(err.message);renderer?.dispose();renderer=null;}
  }
  function onLost(event){event.preventDefault();stage.dataset.renderer='fallback';}
  function onRestored(){stage.dataset.renderer='webgl';}
  function getView(){return{...view,logCount:logs.length,revealed:revealAmount()>.4};}
  let focusPoint=null;
  function clampView(){
    if(view.zoom<=1){view.zoom=1;view.x=0;view.y=0;return;}
    const maxX=Math.max(0,width-width/view.zoom),maxY=Math.max(0,height-height/view.zoom);
    view.x=Math.max(-maxX,Math.min(0,view.x));view.y=Math.max(-maxY,Math.min(0,view.y));
  }
  function applyView(){
    clampView();
    if(camera){if(view.zoom===1&&view.x===0&&view.y===0)camera.clearViewOffset();else camera.setViewOffset(width,height,Math.round(-view.x),Math.round(-view.y),Math.round(width/view.zoom),Math.round(height/view.zoom));camera.updateProjectionMatrix();}
    const fallback=stage.querySelector('.stage-fallback');
    if(fallback){fallback.style.transformOrigin='0 0';fallback.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.zoom})`;}
    stage.dataset.inspecting=String(view.inspecting);stage.dataset.zoom=view.zoom.toFixed(3);stage.dataset.zoomed=view.zoom>1.08?'true':'false';lastAscii=-1;
    stage.dispatchEvent(new CustomEvent('sceneviewchange',{detail:getView()}));
    draw(window.__previewClock||0,true);
  }
  function pointInStage(clientX,clientY){
    const b=stage.getBoundingClientRect();
    return {screenX:clientX-b.left,screenY:clientY-b.top};
  }
  function contentAt(screenX,screenY){
    return {x:screenX/view.zoom-view.x,y:screenY/view.zoom-view.y};
  }
  function zoomAt(next,clientX,clientY,previousAnchor){
    const zoom=Math.max(1,Math.min(4,next));
    if(zoom<=1.001){resetView();return;}
    const b=stage.getBoundingClientRect();
    const origin=previousAnchor||(clientX==null?null:{x:clientX,y:clientY});
    const focus=origin?pointInStage(origin.x,origin.y):{screenX:width/2,screenY:height/2};
    const dest=clientX==null?focus:pointInStage(clientX,clientY);
    const content=contentAt(focus.screenX,focus.screenY);
    focusPoint=content;
    view.zoom=zoom;view.x=dest.screenX/zoom-content.x;view.y=dest.screenY/zoom-content.y;view.inspecting=true;
    applyView();
  }
  function focusAt(clientX,clientY,next){
    const zoom=Math.max(1,Math.min(4,next||2.2));
    if(zoom<=1.001){resetView();return;}
    const screen=pointInStage(clientX,clientY);
    const content=contentAt(screen.screenX,screen.screenY);
    focusPoint=content;
    view.zoom=zoom;view.x=width/2/zoom-content.x;view.y=height/2/zoom-content.y;view.inspecting=true;
    applyView();
    stage.focus({preventScroll:true});
  }
  function resetView(){view.zoom=1;view.x=0;view.y=0;view.inspecting=false;focusPoint=null;touches.clear();stage.dataset.dragging='false';applyView();}
  function toggleInspection(){if(view.inspecting){resetView();return;}view.inspecting=true;applyView();stage.focus({preventScroll:true});}
  function resize(){
    const b=stage.getBoundingClientRect(),nextWidth=Math.max(1,b.width),nextHeight=Math.max(1,b.height);view.x*=nextWidth/width;view.y*=nextHeight/height;width=nextWidth;height=nextHeight;
    if(renderer){renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();}
    const dpr=Math.min(devicePixelRatio,1.6);ascii.width=Math.round(width*dpr);ascii.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);lastAscii=-1;
    applyView();
  }
  function drawAscii(t) {
    const frame=Math.floor(t*18);if(frame===lastAscii)return;lastAscii=frame;
    ctx.clearRect(0,0,width,height);const cell=7.1,row=11,cols=Math.floor(width/cell),rows=Math.floor(height/row);
    const lum=new Float32Array(cols*rows),depths=new Float32Array(cols*rows).fill(-1e5);
    const ay=.32+t*.035,az=-.38,ax=.64;
    const a=new THREE.Vector3(),matrix=new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(ax,ay,az));
    const scale=Math.min(width,height)*.235;
    for(const p of asciiPoints){a.copy(p).applyMatrix4(matrix);const k=5/(5-a.z);const x=Math.floor((width*.5+a.x*scale*k+view.x)*view.zoom/cell),y=Math.floor((height*.5+a.y*-scale*k-height*.04+view.y)*view.zoom/row);if(x<0||x>=cols||y<0||y>=rows)continue;const i=y*cols+x;if(a.z>depths[i]){depths[i]=a.z;lum[i]=Math.min(.99,.28+(a.z+1.7)*.23);}}
    const ramp=' .:-=+*#%@';ctx.font='11px Consolas,monospace';ctx.textBaseline='top';
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){const v=lum[y*cols+x];if(!v)continue;ctx.fillStyle=theme==='light'?`rgba(34,93,72,${.3+v*.7})`:`rgba(${Math.round(112+v*90)},${Math.round(176+v*70)},${Math.round(151-v*24)},${.25+v*.75})`;ctx.fillText(ramp[Math.floor(v*(ramp.length-1))],x*cell,y*row);}
  }
  const logLayer=document.createElement('div');
  logLayer.className='log-points';
  logLayer.hidden=true;
  stage.append(logLayer);
  const logTip=document.createElement('div');
  logTip.className='log-tip';
  logTip.hidden=true;
  logLayer.append(logTip);
  const logCount=document.createElement('p');
  logCount.className='log-count';
  logLayer.append(logCount);
  const projector=new THREE.Vector3();
  let logs=[],logItems=[],hoveredId='';
  const outcomeLabel={pass:'通过',fail:'未通过',untested:'没测',unmarked:'未标注'};
  function revealAmount(){return Math.min(1,Math.max(0,(view.zoom-1.15)/.65));}
  function hashId(id){let s=2166136261;const value=String(id);for(let i=0;i<value.length;i++){s^=value.charCodeAt(i);s=Math.imul(s,16777619);}return (s>>>0)/4294967296;}
  function placeOnRibbon(index,count,id){
    const a=((index+.5)/Math.max(1,count))*Math.PI*2;
    return onTube(a,hashId(id)*Math.PI*2,.198);
  }
  let frozenTime=null;
  function poseKnot(t){
    if(!knot)return;
    if(view.inspecting){if(frozenTime==null)frozenTime=t;}
    else frozenTime=null;
    const time=frozenTime==null?t:frozenTime;
    knot.rotation.set(.62+pointer.y*.12,.18+time*.075+pointer.x*.18,-.34+Math.sin(time*.35)*.04);
    knot.position.y=Math.sin(time*.55)*.045;
    knot.scale.setScalar(mode==='particles'?1.08+Math.sin(time*.8)*.025:1+Math.sin(time*.45)*.012);
    knot.updateMatrixWorld(true);
  }
  function screenOf(local,useCamera){
    if(!knot)return null;
    projector.copy(local).applyMatrix4(knot.matrixWorld);
    if(useCamera&&camera){
      const depth=projector.z;
      projector.project(camera);
      if(projector.z<-1||projector.z>1)return null;
      return {x:(projector.x*.5+.5)*width,y:(-projector.y*.5+.5)*height,depth,behind:depth<-.35};
    }
    const scale=Math.min(width,height)*.22;
    return {x:(width*.5+projector.x*scale+view.x)*view.zoom,y:(height*.5-projector.y*scale+view.y)*view.zoom,depth:-projector.z,behind:projector.z<-.35};
  }
  function hideTip(){hoveredId='';logTip.hidden=true;}
  logTip.addEventListener('pointerdown',event=>event.stopPropagation());
  logTip.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();});
  logTip.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();if(hoveredId)window.openHomeLog?.(hoveredId);});
  function showTip(item){
    const log=item.log;
    hoveredId=log.id;
    logTip.hidden=false;
    logTip.dataset.outcome=log.outcome||'unmarked';
    logTip.replaceChildren();
    const when=document.createElement('time');
    when.textContent=[log.date,log.time&&log.end?log.time+'–'+log.end:log.time].filter(Boolean).join(' ');
    const title=document.createElement('strong');
    title.textContent=log.title||'未命名记录';
    const meta=document.createElement('em');
    meta.textContent=[log.workspace,outcomeLabel[log.outcome]||'未标注','点击打开'].filter(Boolean).join(' · ');
    logTip.append(when,title,meta);
    const tipW=200,tipH=74;
    let left=(item.x||0)+16,top=(item.y||0)-12;
    if(left+tipW>width-8)left=Math.max(8,(item.x||0)-tipW-12);
    if(top+tipH>height-8)top=Math.max(8,height-tipH-8);
    if(top<28)top=28;
    logTip.style.transform=`translate(${left}px,${top}px)`;
  }
  function setLogs(items){
    const next=(Array.isArray(items)?items:[]).filter(item=>item&&item.id&&item.date).slice().sort((a,b)=>(a.date+' '+(a.time||'')).localeCompare(b.date+' '+(b.time||'')));
    logs=next;
    hoveredId='';
    logTip.hidden=true;
    logLayer.querySelectorAll('.log-dot').forEach(node=>node.remove());
    logItems=logs.map((log,index)=>{
      const button=document.createElement('button');
      button.type='button';
      button.className='log-dot';
      button.dataset.outcome=log.outcome||'unmarked';
      button.setAttribute('aria-label',log.date+' '+(log.title||'未命名记录'));
      const mark=document.createElement('i');
      const label=document.createElement('span');
      label.textContent=log.date.slice(5)+' '+(log.title||'');
      button.append(mark,label);
      const item={log,button,position:placeOnRibbon(index,logs.length,log.id),x:0,y:0};
      button.addEventListener('pointerdown',event=>event.stopPropagation());
      button.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();});
      button.addEventListener('pointerenter',()=>showTip(item));
      button.addEventListener('focus',()=>showTip(item));
      button.addEventListener('pointerleave',hideTip);
      button.addEventListener('blur',hideTip);
      button.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();window.openHomeLog?.(log.id);});
      logLayer.append(button);
      return item;
    });
    logCount.textContent=logs.length?logs.length+' 条周历 · 一个点一条':'还没有周历记录';
    stage.dispatchEvent(new CustomEvent('sceneviewchange',{detail:getView()}));
    layoutLogs(!!camera);
  }
  function layoutLogs(useCamera){
    const reveal=revealAmount();
    const on=reveal>.4&&logs.length>0;
    uniforms.uReveal.value=reveal;
    if(ribbon)ribbon.visible=reveal<.94;
    if(stars)stars.visible=reveal<.8;
    knot?.children.forEach(node=>{if(node.userData.filament)node.material.opacity=(theme==='light'?.22:.16)*(1-reveal*.6);});
    logLayer.hidden=!on;
    stage.dataset.logs=on?'on':'off';
    if(!on){logTip.hidden=true;return;}
    const showNames=view.zoom>=2.45;
    const placed=[];
    let hovered=null;
    for(const item of logItems){
      const pos=screenOf(item.position,useCamera);
      const outside=!pos||pos.x<-30||pos.y<-30||pos.x>width+30||pos.y>height+30;
      item.button.hidden=outside;item.button.style.opacity=pos&&pos.behind?".38":"1";
      if(outside)continue;
      item.x=pos.x;item.y=pos.y;
      item.button.style.transform=`translate(${pos.x}px,${pos.y}px)`;
      item.button.style.zIndex=String((item.log.id===hoveredId?6000:2000)-Math.round(pos.depth*100));
      const box={x:pos.x-8,y:pos.y-10,w:128,h:22};
      const clear=showNames&&!placed.some(other=>Math.abs(other.x-box.x)<box.w&&Math.abs(other.y-box.y)<box.h);
      item.button.classList.toggle('named',clear);
      if(clear)placed.push(box);
      if(item.log.id===hoveredId)hovered=item;
    }
    if(hovered)showTip(hovered);
  }
  function draw(t,force=false){
    if(disposed||(!inView&&!force))return;
    if(t===lastTime&&!force)return;
    lastTime=t;
    if(visualTime===null||lastInputTime===null)visualTime=t;
    else visualTime+=Math.max(0,t-lastInputTime);
    lastInputTime=t;t=visualTime;
    stage.dataset.frameTime=t.toFixed(3);
    poseKnot(t);
    if(mode==='ascii'){drawAscii(t);layoutLogs(!!camera);return;}
    if(!renderer||stage.dataset.renderer!=='webgl'){layoutLogs(false);return;}
    uniforms.uTime.value=t;
    uniforms.uPointer.value.lerp(new THREE.Vector2(pointer.x, pointer.y), .12);
    if(stars)stars.rotation.z=t*.012;
    renderer.render(scene,camera);
    layoutLogs(true);
  }
  function setMode(value){mode=value;stage.dataset.mode=value;uniforms.uMode.value=value==='particles'?1:0;knot?.children.forEach(o=>{if(o.userData.filament)o.visible=value!=='particles';});lastAscii=-1;draw(window.__previewClock||0,true);}
  function setTheme(value){theme=value;uniforms.uLight.value=value==='light'?1:0;knot?.children.forEach(o=>{if(o.userData.filament){o.material.color.set(value==='light'?0x2e8779:0x9fe1c5);o.material.opacity=value==='light'?.22:.16;}});if(stars)stars.material.color.set(value==='light'?0x51877b:0xadc7bd);lastAscii=-1;draw(window.__previewClock||0,true);}
  const buttonHeld=e=>e.pointerType==='touch'||e.pointerType==='pen'||(e.buttons&1)===1;
  const onPointer=e=>{
    beginDrag(e);
    if(touches.has(e.pointerId)){
      if(!buttonHeld(e)){endPress(e);return;}
      const previous=[...touches.values()];touches.set(e.pointerId,{x:e.clientX,y:e.clientY});const current=[...touches.values()];
      if(current.length>1){const dist=p=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y),mid=p=>({x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2}),oldMid=mid(previous),newMid=mid(current);zoomAt(view.zoom*dist(current)/Math.max(1,dist(previous)),newMid.x,newMid.y,oldMid);}
      else{view.x+=current[0].x-previous[0].x;view.y+=current[0].y-previous[0].y;applyView();}return;
    }
    if(view.inspecting||reduced||document.documentElement.hasAttribute('data-paused'))return;const b=stage.getBoundingClientRect();pointer.x=(e.clientX-b.left)/b.width-.5;pointer.y=(e.clientY-b.top)/b.height-.5;
  };
  let press=null,clickTimer=0,suppressClick=false;
  const onDown=e=>{if(e.button>0)return;press={id:e.pointerId,x:e.clientX,y:e.clientY,dragging:false};};
  const beginDrag=e=>{if(!view.inspecting||!buttonHeld(e)||!press||press.id!==e.pointerId||press.dragging)return;if(Math.hypot(e.clientX-press.x,e.clientY-press.y)<=5)return;press.dragging=true;stage.focus({preventScroll:true});stage.setPointerCapture(e.pointerId);touches.set(e.pointerId,{x:e.clientX,y:e.clientY});stage.dataset.dragging='true';};
  const endPress=e=>{if(press?.id===e.pointerId&&press.dragging)suppressClick=true;touches.delete(e.pointerId);if(press?.id===e.pointerId)press=null;if(stage.hasPointerCapture?.(e.pointerId))stage.releasePointerCapture(e.pointerId);if(!touches.size)stage.dataset.dragging='false';};
  const onUp=e=>endPress(e);
  const onWheel=e=>{e.preventDefault();const pixels=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?height:1);zoomAt(view.zoom*Math.exp(-pixels*.0015),e.clientX,e.clientY);};
  const onLog=e=>e.target.closest?.('.log-dot,.log-tip');
  const onClick=e=>{if(suppressClick){suppressClick=false;return;}if(e.button!==0||press?.dragging||onLog(e))return;clearTimeout(clickTimer);if(e.detail>1)return;const x=e.clientX,y=e.clientY;clickTimer=setTimeout(()=>{if(revealAmount()>.4&&logs.length)return;zoomAt(view.zoom<1.2?2.2:Math.min(4,view.zoom*1.35),x,y);},240);};
  const onDouble=e=>{e.preventDefault();clearTimeout(clickTimer);if(onLog(e))return;zoomAt(view.zoom<1.2?2.6:Math.min(4,view.zoom*1.45),e.clientX,e.clientY);};

  const onKey=e=>{if(['+','=','-','0','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='0'||e.key==='Escape')resetView();else if(e.key==='+'||e.key==='=')zoomAt(view.zoom*1.25);else if(e.key==='-')zoomAt(view.zoom/1.25);else{const step=30;view.x+=e.key==='ArrowLeft'?step:e.key==='ArrowRight'?-step:0;view.y+=e.key==='ArrowUp'?step:e.key==='ArrowDown'?-step:0;applyView();}}};
  stage.addEventListener('pointermove',onPointer,{passive:true});
  stage.addEventListener('pointerdown',onDown);stage.addEventListener('pointerup',onUp);stage.addEventListener('pointercancel',onUp);stage.addEventListener('lostpointercapture',onUp);stage.addEventListener('wheel',onWheel,{passive:false});stage.addEventListener('click',onClick);stage.addEventListener('dblclick',onDouble);stage.addEventListener('keydown',onKey);
  const observer=new ResizeObserver(resize),intersection=new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;if(inView)draw(window.__previewClock||0,true);},{rootMargin:'80px'});
  init();observer.observe(stage);intersection.observe(stage);resize();setMode('space');
  function dispose(){disposed=true;observer.disconnect();intersection.disconnect();stage.removeEventListener('pointermove',onPointer);for(const[type,fn]of [['pointerdown',onDown],['pointerup',onUp],['pointercancel',onUp],['lostpointercapture',onUp],['wheel',onWheel],['click',onClick],['dblclick',onDouble],['keydown',onKey]])stage.removeEventListener(type,fn);renderer?.domElement.removeEventListener('webglcontextlost',onLost);renderer?.domElement.removeEventListener('webglcontextrestored',onRestored);resources.forEach(r=>r.dispose());renderer?.dispose();}
  return{draw,setMode,setTheme,dispose,getView,zoomAt,focusAt,resetView,toggleInspection,setLogs};
}
