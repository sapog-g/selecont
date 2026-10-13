const copy={
  ru:{cover:'Не выбирай<br><span class="accent">одну версию</span><br>себя',profilesSection:'Профили',profiles:'Один профиль.<br><span class="accent">Разные контексты</span>',profilesLead:'Показывай разным людям ту сторону жизни, которую выбираешь сам.',ai:'ИИ замечает<br>детали.<br><span class="accent">Ты задаёшь границы.</span>',beforePublish:'До публикации',advises:'Советует, не решает',noAutoChange:'Не меняет аудиторию сам',yourDecision:'Решение остаётся за тобой',bottleDetected:'Обнаружена бутылка',highRisk:'Высокий риск',privacyAdvice:'Для «Семьи» снимок может быть неуместен. Лучше выбрать «Друзья».',chooseFriends:'Выбрать «Друзья»',publishAnyway:'Всё равно опубликовать',futureConcept:'КОНЦЕПТ БУДУЩЕЙ ФУНКЦИИ'},
  en:{cover:'Be yourself<br>in <span class="accent">every context</span>',profilesSection:'Profiles',profiles:'Be different,<br><span class="accent">still be you</span>',profilesLead:'Show each audience the side of life you choose.',ai:'Smart suggestions.<br><span class="accent">Your choice.</span>',beforePublish:'Before publishing',advises:'Advises, never decides',noAutoChange:'Never changes the audience itself',yourDecision:'The final choice stays yours',bottleDetected:'Bottle detected',highRisk:'High risk',privacyAdvice:'This may not fit “Family”. “Friends” could be a better choice.',chooseFriends:'Choose “Friends”',publishAnyway:'Publish anyway',futureConcept:'FUTURE FEATURE CONCEPT'}
};
const profiles={
  ru:[
    {key:'family',title:'Семья',avatar:'grisha-family-avatar.png',post:'grisha-family-post.png',bio:'Люблю спокойные вечера дома и семейные истории.',explain:'Домашние фотографии, семейные события и новости, которыми Гриша делится только со своими.',caption:'Собрались дома и наконец разобрали старые фотографии.',final:true},
    {key:'friends',title:'Друзья',avatar:'grisha-friends.png',post:'grisha-friends-post-v3.png',bio:'Свои шутки, музыка и планы на вечер.',explain:'Вечерние встречи и разговоры, которые остаются между друзьями.',caption:'Наконец-то собрались все вместе.'},
    {key:'colleagues',title:'Коллеги',avatar:'grisha-colleagues.png',post:'grisha-colleagues-post-v3.png',bio:'Проекты, учёба и работа в одной ленте.',explain:'Проекты и рабочие новости без личных семейных публикаций.',caption:'Подготовили новую версию проекта.'},
    {key:'public',title:'Public',avatar:'grisha-public.png',post:'grisha-public-post-v3.png',bio:'Открытая часть профиля.',explain:'Только публикации, которые Гриша решил открыть всем.',caption:'Вечерняя прогулка после насыщенного дня.'}
  ],
  en:[
    {key:'family',title:'Family',avatar:'grisha-family-avatar.png',post:'grisha-family-post.png',bio:'Quiet evenings at home and family stories.',explain:'Home photos, family events and news Grisha shares only with those closest to him.',caption:'Finally got together and looked through our old photos.',final:true},
    {key:'friends',title:'Friends',avatar:'grisha-friends.png',post:'grisha-friends-post-v3.png',bio:'Inside jokes, music and plans for the evening.',explain:'Evenings and conversations that stay among friends.',caption:'Everyone finally made it tonight.'},
    {key:'colleagues',title:'Colleagues',avatar:'grisha-colleagues.png',post:'grisha-colleagues-post-v3.png',bio:'Projects, study and work in one place.',explain:'Projects and work updates without private family posts.',caption:'Prepared the new project version.'},
    {key:'public',title:'Public',avatar:'grisha-public.png',post:'grisha-public-post-v3.png',bio:'The open part of the profile.',explain:'Only the posts Grisha chooses to share with everyone.',caption:'An evening walk after a busy day.'}
  ]
};

let language=new URLSearchParams(location.search).get('lang')==='en'?'en':'ru';
let step=Math.max(0,Math.min(6,Number(new URLSearchParams(location.search).get('step'))||0));
let busy=false,animation=0,duration=900;
const stage=document.querySelector('#stage');
const stack=document.querySelector('#profile-stack');
const contextStack=document.querySelector('#context-stack');
const ring=new RingMorph(document.querySelector('#ring-canvas'));
const elements={cover:document.querySelector('.cover-copy'),intro:document.querySelector('.transition-copy'),logo:stage.querySelector(':scope > .logo'),coverRings:document.querySelector('.approved-cover-rings'),introRings:document.querySelector('.approved-transition-rings'),canvas:document.querySelector('#ring-canvas'),profiles:document.querySelector('.profiles-layer'),ai:document.querySelector('.ai-layer'),rings:document.querySelector('.ring-system')};
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const smooth=(a,b,x)=>{x=clamp((x-a)/(b-a));return x*x*(3-2*x)};
const ease=x=>x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2;
function profileMarkup(item,index){return `<div class="disc-sector" data-sector="${index}" style="transform:rotate(${index*90}deg)"><article class="profile-state" data-profile="${index}"><div class="profile-head"><div class="avatar"><img src="assets/${item.avatar}" alt=""></div><div class="identity"><strong>@grisha</strong><p>${item.bio}</p></div></div><article class="post"><header><img src="assets/${item.avatar}" alt=""><div><strong>@grisha</strong><span>${language==='ru'?'сегодня':'today'}</span></div><b>•••</b></header><img class="post-photo" src="assets/${item.post}" alt=""><div class="post-actions" aria-hidden="true"><span>♡</span><span>◯</span><span>↗</span></div><p class="post-caption">${item.caption}</p></article></article></div>`}
function contextMarkup(item,index){return `<article class="context-state" data-context="${index}"><h2>${item.title}</h2><p>${item.explain}</p>${item.final?'':'<p class="working-copy">'+(language==='ru'?'Рабочая подпись':'Working copy')+'</p>'}</article>`}
function renderCopy(){
  document.documentElement.lang=language;
  document.querySelectorAll('[data-copy]').forEach(el=>el.innerHTML=copy[language][el.dataset.copy]);
  stack.innerHTML=profiles[language].map(profileMarkup).join('');contextStack.innerHTML=profiles[language].map(contextMarkup).join('');
  document.querySelector('#language').textContent=language==='ru'?'EN':'RU';
  document.querySelector('#instruction').textContent=language==='ru'?'Клик по кадру или → — следующий шаг. ← — назад.':'Click the frame or press → to continue. Press ← to go back.';
}
function paintScene(position){
  const opening=clamp(position),merge=clamp(position-1),rotor=clamp(position-2,0,3),ai=clamp(position-5);
  elements.cover.style.opacity=1-smooth(0,.65,opening);
  elements.logo.style.opacity=1-smooth(0,.65,opening);
  elements.cover.style.transform=`translateX(${-45*opening}px)`;
  // Register both artworks in the same moving frame before mixing their surfaces.
  // Their centres travel together, so the cover cannot dissolve into a stationary slide.
  const artworkBlend=smooth(.62,.98,opening),artworkScale=1+.505*opening;
  elements.coverRings.style.opacity=1-artworkBlend;
  elements.coverRings.style.transform=`translate(${-390*opening}px,${-58*opening}px) scale(${artworkScale})`;
  elements.intro.style.opacity=smooth(.5,1,opening)*(1-smooth(0,.35,merge));
  elements.introRings.style.opacity=.9*artworkBlend*(1-smooth(0,.012,merge));
  elements.introRings.style.transform=`translate(${390*(1-opening)-790*merge}px,${58*(1-opening)-388*merge}px) scale(${artworkScale/1.505})`;
  elements.canvas.style.opacity=smooth(0,.012,merge);
  elements.rings.style.opacity=1-ai;
  // All four quadrants stay mounted and opaque; only the common parent rotates.
  stack.style.transform=`rotate(${-90*rotor}deg)`;
  stack.dataset.angle=String(-90*rotor);
  elements.profiles.style.opacity=smooth(.48,.94,merge)*(1-ai);
  elements.profiles.style.pointerEvents=position>=2&&position<6?'auto':'none';
  ring.draw(merge,-rotor*Math.PI/2);
  document.querySelectorAll('.context-state').forEach((el,i)=>{
    const delta=i-rotor,visibility=clamp(1-Math.abs(delta)/.46);
    el.style.opacity=visibility*smooth(.74,1,merge);
    el.style.transform=`translateX(${delta>=0?180*(1-visibility):-70*(1-visibility)}px)`;
    el.setAttribute('aria-hidden',String(Math.abs(delta)>.01));
  });
  elements.ai.style.opacity=ai;elements.ai.style.transform=`translateY(${32*(1-ai)}px)`;
  elements.ai.style.pointerEvents=ai===1?'auto':'none';
  stage.dataset.position=position.toFixed(4);
}
function setBusy(value){busy=value;stage.dataset.moving=String(value);['next','previous','restart','language'].forEach(id=>document.querySelector('#'+id).disabled=value)}
function updatePage(){stage.dataset.step=String(step);document.querySelector('#page-number').textContent=step===0?'01':step===1?'02':step<6?'03':'04'}
function setStep(next){
  if(busy)return;next=clamp(next,0,6);if(next===step)return;
  const from=step;step=next;updatePage();
  if(Math.abs(next-from)>1){paintScene(next);return;}
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const total=reduced?0:duration*((from===1&&next===2)||(from===2&&next===1)?1.4:Math.min(from,next)===0?1.25:1);
  setBusy(true);let start;
  const frame=now=>{start??=now;const t=total?clamp((now-start)/total):1;paintScene(from+(next-from)*ease(t));if(t<1)animation=requestAnimationFrame(frame);else{setBusy(false);paintScene(next)}};
  animation=requestAnimationFrame(frame);
}
function fit(){stage.style.transform=`scale(${document.querySelector('#stage-wrap').clientWidth/1600})`}
stage.addEventListener('click',event=>{if(!event.target.closest('button'))setStep(step===6?0:step+1)});
document.querySelector('#next').addEventListener('click',()=>setStep(step===6?0:step+1));
document.querySelector('#previous').addEventListener('click',()=>setStep(step===0?6:step-1));
document.querySelector('#restart').addEventListener('click',()=>{if(busy)return;step=0;updatePage();paintScene(0)});
document.querySelector('#language').addEventListener('click',()=>{if(busy)return;language=language==='ru'?'en':'ru';renderCopy();paintScene(step)});
document.querySelector('#speed').addEventListener('change',event=>{duration=Number(event.target.value);document.documentElement.style.setProperty('--motion',`${duration}ms`)});
document.addEventListener('keydown',event=>{if(event.target.matches('select,input,textarea'))return;if(event.key==='ArrowRight'||event.key===' '){event.preventDefault();setStep(step===6?0:step+1)}if(event.key==='ArrowLeft'){event.preventDefault();setStep(step===0?6:step-1)}if(event.key==='Home')document.querySelector('#restart').click()});
new ResizeObserver(fit).observe(document.querySelector('#stage-wrap'));
renderCopy();fit();
ring.ready.then(()=>{updatePage();paintScene(step);document.documentElement.dataset.ready='true'}).catch(error=>{document.querySelector('#instruction').textContent=error.message;console.error(error)});
// Deterministic review hooks: inspect geometry and intermediate frames without timing guesses.
window.motionReview={ready:ring.ready,seek(from,to,progress){cancelAnimationFrame(animation);setBusy(false);step=progress===1?to:from;updatePage();paintScene(from+(to-from)*progress)},go:setStep,get state(){return{step,busy,language,position:Number(stage.dataset.position)}}};
