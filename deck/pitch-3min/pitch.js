// A separate 13-frame performance; the approved renderer owns all ring/disc motion.
language=new URLSearchParams(location.search).get('lang')==='en'?'en':'ru';
profiles.ru.find(profile=>profile.key==='public').title='Публичное';
copy.ru.profilesLead='Семья, друзья и коллеги — в одном аккаунте.';
copy.ru.highRisk='Высокий риск';
copy.ru.privacyAdvice='Для «Семьи» снимок может быть неуместен. Лучше выбрать «Друзья».';
copy.ru.chooseFriends='Выбрать «Друзья»';
copy.ru.publishAnyway='Всё равно опубликовать';
copy.ru.futureConcept='Концепт будущей функции';
copy.en.cover='Be yourself<br>in <span class="accent">every context</span>';
copy.en.profiles='One profile.<br><span class="accent">Different contexts</span>';
copy.en.profilesLead='Family, friends and colleagues, all in one account.';
copy.en.highRisk='High risk';
copy.en.privacyAdvice='This may not fit “Family”. “Friends” could be a better choice.';
copy.en.chooseFriends='Choose “Friends”';
copy.en.publishAnyway='Publish anyway';
copy.en.futureConcept='Future feature concept';
const pitchProfiles={
 ru:[
  {post:'pitch-family.png',bio:'Семейные фотографии и важные моменты.',explain:'Фотография с бабушкой после вручения диплома.',caption:'Бабушка приехала на вручение диплома.'},
  {post:'pitch-friends.png',bio:'Свои шутки, встречи и планы на вечер.',explain:'Празднование после защиты с друзьями.',caption:'Защитились. Теперь можно выдохнуть.'},
  {post:'pitch-project.png',bio:'Учёба, проекты и результаты работы.',explain:'Дипломный проект и то, что удалось сделать.',caption:'Дипломный проект защищён.'},
  {post:'pitch-diploma.png',bio:'Открытая часть профиля.',explain:'То, что Гриша решил показать всем.',caption:'Диплом получен. Дальше — больше.'}
 ],
 en:[
  {post:'pitch-family.png',bio:'Family photos and important moments.',explain:'A photo with his grandmother after graduation.',caption:'Grandma came to the graduation ceremony.'},
  {post:'pitch-friends.png',bio:'Inside jokes, meetups and plans for the evening.',explain:'Celebrating graduation with friends.',caption:'We made it. Time to celebrate.'},
  {post:'pitch-project.png',bio:'Studies, projects and work results.',explain:'The graduation project and what he built.',caption:'Graduation project defended.'},
  {post:'pitch-diploma.png',bio:'The public side of the profile.',explain:'What Grisha chooses to share with everyone.',caption:'Diploma in hand. On to the next chapter.'}
 ]
};
const pitchTextEn={
 secPost:'Posting · author’s view',postTitle:'One post.<br><span class="story-accent">Three circles.</span>',postBody:'A graduation photo.<br>One post for selected audiences.',postPrivacy:'Grisha decides who can see it.',eulerKey:'At the centre: <span class="story-accent">one shared post</span>.<br>Each circle is an audience.',family:'Family',friends:'Friends',colleagues:'Colleagues',oneSharedPost:'One post',eulerNote:'Audience diagram · circles chosen by the author',
 secProof:'Working today',proofTitle:'Core mechanics<br><span class="story-accent">already work.</span>',proofCircles:'Circles and profiles',proofCirclesBody:'Different bios, photos and audiences',proofPost:'Publishing',proofPostBody:'One post for selected circles',proofComments:'Discussions',proofCommentsBody:'Replies, deletion and separate threads',proofSummary:'Sign-in and sessions · following · photos · shared likes · access revocation',proofNote:'Local prototype · real screens with test accounts',
 secSuggest:'New follower',suggestTitle:'The system suggests.<br><span class="story-accent">You choose the circle.</span>',suggestBody:'A suggestion recommends a suitable circle.<br>You confirm it or choose another.',suggestNoAuto:'The decision stays <span class="story-accent">with the author.</span>',authorView:'Author’s view only',newFollower:'New follower',suggestedCircle:'Suggested circle',confirmCircle:'Confirm',chooseOther:'Choose another',futureNote:'Future feature concept'
};
const pitchTextRu={};
document.querySelectorAll('[data-t]').forEach(el=>pitchTextRu[el.dataset.t]=el.innerHTML);
const staticText=[
 ['.review-bar>div span','Питч · 13 кадров · 3 минуты','Pitch · 13 frames · 3 minutes'],
 ['#restart','Сначала','Start over'],['#fullscreen','На весь экран','Full screen'],['#tempo-label','Темп','Pace'],
 ['#speed option[value="900"]','Плавно · 0,90 с','Smooth · 0.90 s'],['#speed option[value="720"]','Быстрее · 0,72 с','Faster · 0.72 s'],['#speed option[value="1200"]','Спокойно · 1,20 с','Calm · 1.20 s'],
 ['.s-problem .eyebrow','Проблема','The problem'],['.problem-main h1','Каждой истории —<br><span class="story-accent">своя аудитория.</span>','Every story has<br><span class="story-accent">its own audience.</span>'],
 ['.thought-friends span','Это поймут<br>мои друзья','My friends<br>will get this'],['.thought-family span','Этим хочу поделиться<br>с семьёй','I want to share this<br>with my family'],['.thought-work span','Это для коллег','This is for my colleagues'],
 ['.s-conversations>.eyebrow','Комментарии под постом','Comments under the post'],['.s-conversations .heading h1','Один пост.<br><span class="story-accent">Отдельные обсуждения.</span>','One post.<br><span class="story-accent">Separate discussions.</span>'],
 ['.thread-column:nth-child(1)>h2','Семья','Family'],['.thread-column:nth-child(2)>h2','Друзья','Friends'],
 ['.thread-column:nth-child(1) .thread-post p','Защитился. Диплом получен!','Graduated. Diploma in hand!'],['.thread-column:nth-child(2) .thread-post p','Защитился. Диплом получен!','Graduated. Diploma in hand!'],
 ['.thread-column:nth-child(1) h3','Комментарии под постом','Comments under the post'],['.thread-column:nth-child(2) h3','Комментарии под постом','Comments under the post'],
 ['.thread-column:nth-child(1) .demo-comment p','Помню, как вела тебя<br>в первый класс.','I remember walking you<br>to school on your first day.'],['.thread-column:nth-child(2) .demo-comment p','Фотографии с вечеринки<br>тоже будут?','Will there be party<br>photos too?'],
 ['.discussion-summary','Семья видит своё обсуждение. Друзья — своё.','Family sees its discussion. Friends see theirs.'],
 ['.selected-audience','Выбрана аудитория: <strong>Семья</strong>','Selected audience: <strong>Family</strong>'],
 ['.s-finale .plus-phase p','Один из вариантов заработка — подписка.','One possible revenue model is a subscription.'],
 ['.ask-phase .final-copy h1','Георгий<br>Сапоговский','George<br>Sapogovsky'],['.ask-phase .founder-role','Студент ИТМО · основатель selecont','ITMO student · founder of selecont'],
 ['.ask-phase .final-copy>p:last-child','Найти первых пользователей.<br><span class="story-accent">Организовать проверку.</span>','Find the first users.<br><span class="story-accent">Run the validation.</span>'],
 ['.ask-phase .final-motto','Не выбирай одну версию себя.','Be yourself in every context.']
];
const originalRenderCopy=renderCopy;
renderCopy=function(){
 profiles[language].forEach((profile,index)=>Object.assign(profile,pitchProfiles[language][index],{final:true}));
 originalRenderCopy();
 document.querySelectorAll('[data-t]').forEach(el=>el.innerHTML=(language==='en'?pitchTextEn:pitchTextRu)[el.dataset.t]||pitchTextRu[el.dataset.t]);
 for(const [selector,ru,en] of staticText){const el=document.querySelector(selector);if(el)el.innerHTML=language==='en'?en:ru;}
 document.querySelector('.profiles-layer').setAttribute('aria-label',language==='en'?'Profile context changes':'Смена версий профиля');
 document.querySelector('.ai-layer').setAttribute('aria-label',language==='en'?'AI Privacy Check · future feature':'AI Privacy Check · будущая функция');
};
const basePaint=paintScene;
let finalProgress=0,finalPhase=0;
const slides=[...document.querySelectorAll('[data-pitch]')];
const reduce=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const revealTargets=()=>[...document.querySelectorAll('.reveal')];
function measureReveals(){
 const scale=stage.getBoundingClientRect().width/1600;
 const root=stage.getBoundingClientRect();
 for(const el of revealTargets()){
  el.style.transform='none';
  const r=el.getBoundingClientRect(),x=(r.left-root.left)/scale,y=(r.top-root.top)/scale,w=r.width/scale;
  el.dataset.travel=String(el.dataset.direction==='right'?1600-x+32:el.dataset.direction==='up'?900-y+32:x+w+32);
 }
}
function reveal(el,visibility){
 const v=clamp(visibility),offset=reduce()?0:Math.pow(1-v,3)*Number(el.dataset.travel||1000);
 el.style.opacity=String(smooth(.48,.92,v));
 el.style.transform=el.dataset.direction==='up'?`translateY(${offset}px)`:`translateX(${el.dataset.direction==='right'?offset:-offset}px)`;
}
function paintFinal(sceneVisibility=1){
 const plus=document.querySelector('.plus-phase'),ask=document.querySelector('.ask-phase');
 for(const [el,v] of [[plus,1-finalProgress],[ask,finalProgress]]){
  el.style.opacity=String(smooth(0,.85,v));el.style.visibility=v>.001?'visible':'hidden';
  el.querySelectorAll('.reveal').forEach(e=>reveal(e,v*sceneVisibility));
 }
 document.querySelector('.final-label').textContent=finalProgress<.5?(language==='en'?'Revenue model':'Модель заработка'):(language==='en'?'Founder · next step':'Основатель · следующий шаг');
 stage.dataset.final=String(finalPhase);
}
paintScene=function(position){
 const base=position<2?position/2:position<=6?position-1:5;
 basePaint(base);
 if(position<2){
  elements.cover.style.opacity=String(Number(elements.cover.style.opacity)*(1-smooth(.05,.45,position)));
  elements.logo.style.opacity=String(Number(elements.logo.style.opacity)*(1-smooth(.05,.45,position)));
  elements.intro.style.opacity=String(Number(elements.intro.style.opacity)*smooth(1.45,1.9,position));
 }
 if(position>6){const out=1-smooth(6,6.8,position);elements.profiles.style.opacity=String(Number(elements.profiles.style.opacity)*out);elements.rings.style.opacity=String(out);}
 for(const slide of slides){
  const visibility=clamp(1-Math.abs(position-Number(slide.dataset.pitch)));
  slide.style.opacity=String(smooth(0,.9,visibility));slide.style.visibility=visibility>.001?'visible':'hidden';slide.setAttribute('aria-hidden',String(visibility<.999));
  [...slide.children].forEach(el=>{el.style.opacity=String(smooth(.48,.92,visibility))});
  slide.querySelectorAll('.reveal').forEach(el=>reveal(el,visibility));
 }
 const ai=clamp(1-Math.abs(position-10));
 elements.ai.style.opacity=String(smooth(0,.9,ai));elements.ai.style.visibility=ai>.001?'visible':'hidden';elements.ai.style.transform='none';
 elements.ai.style.pointerEvents='none';
 [...elements.ai.children].forEach(el=>{el.style.opacity=String(smooth(.48,.92,ai))});
 elements.ai.querySelectorAll('.ai-photo,.ai-copy,.privacy-card,.detector').forEach(el=>{
  const off=reduce()?0:Math.pow(1-ai,3)*1100;
  el.style.transform=`translateX(${el.classList.contains('ai-copy')?-off:off}px)`;
 });
 if(position>11)paintFinal(clamp(position-11));
 document.querySelector('#page-number').style.color=position>9.5?'#dceefe':'#06182b';
 stage.dataset.position=position.toFixed(4);
};
updatePage=function(){stage.dataset.step=String(step);document.querySelector('#page-number').textContent=String(step+1).padStart(2,'0')+' / 13';};
function runTween(from,to,draw,multiplier=1){
 setBusy(true);let started;const total=reduce()?0:duration*multiplier;
 const tick=now=>{started??=now;const t=total?clamp((now-started)/total):1;draw(from+(to-from)*ease(t));if(t<1)animation=requestAnimationFrame(tick);else{setBusy(false);draw(to);}};
 animation=requestAnimationFrame(tick);
}
function changeFinal(next){finalPhase=next;runTween(finalProgress,next,v=>{finalProgress=v;paintScene(12)},.85);}
function go(next){
 if(busy)return;
 if(next>12){if(!finalPhase)changeFinal(1);return;}
 if(next<0)return;
 const from=step;step=next;updatePage();
 if(next!==12){finalProgress=0;finalPhase=0;}
 if(Math.abs(next-from)>1){paintScene(next);return;}
 runTween(from,next,paintScene,Math.min(from,next)===2?1.4:1);
}
function advance(){go(step+1)}
function back(){if(busy)return;if(step===12&&finalPhase){changeFinal(0);return;}go(step-1)}
function restart(){if(busy)return;step=0;finalPhase=0;finalProgress=0;updatePage();paintScene(0)}
for(const id of ['next','previous','restart','language']){const old=document.querySelector('#'+id),fresh=old.cloneNode(true);old.replaceWith(fresh);}
document.querySelector('#next').addEventListener('click',advance);
document.querySelector('#previous').addEventListener('click',back);
document.querySelector('#restart').addEventListener('click',restart);
document.querySelector('#language').addEventListener('click',()=>{if(busy)return;language=language==='ru'?'en':'ru';renderCopy();updatePage();paintScene(step)});
stage.addEventListener('click',e=>{if(e.target.closest('button'))return;e.stopImmediatePropagation();advance()},true);
document.addEventListener('keydown',e=>{
 if(e.target.matches('input,textarea,select'))return;
 if(!['ArrowRight','ArrowLeft',' ','Home','End','f','F','а','А','Escape'].includes(e.key))return;
 e.preventDefault();e.stopImmediatePropagation();
 if(e.key==='ArrowLeft')back();else if(e.key==='Home')restart();else if(e.key==='End'){if(!busy){step=12;finalPhase=1;finalProgress=1;updatePage();paintScene(12)}}
 else if(['f','F','а','А'].includes(e.key))toggleFullscreen();else if(e.key==='Escape'){if(document.fullscreenElement)document.exitFullscreen();document.body.classList.remove('presenting');fitPitch();}else advance();
},true);
function fitPitch(){
 const presenting=document.body.classList.contains('presenting');
 const h=presenting?innerHeight:Math.max(300,innerHeight-document.querySelector('.review-bar').offsetHeight-70);
 const w=presenting?innerWidth:innerWidth-48;
 document.querySelector('#stage-wrap').style.width=Math.min(w,h*16/9)+'px';fit();
}
async function toggleFullscreen(){
 if(document.fullscreenElement){await document.exitFullscreen();return;}
 document.body.classList.add('presenting');fitPitch();
 try{await document.documentElement.requestFullscreen()}catch{}
}
document.querySelector('#fullscreen').addEventListener('click',toggleFullscreen);
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)document.body.classList.remove('presenting');fitPitch()});
addEventListener('resize',fitPitch);
renderCopy();fitPitch();
step=clamp(Number(new URLSearchParams(location.search).get('step'))||0,0,12);
if(new URLSearchParams(location.search).get('present')==='1'){document.body.classList.add('presenting');fitPitch();}
Promise.all([ring.ready,document.fonts.ready]).then(()=>{measureReveals();updatePage();paintScene(step);document.documentElement.dataset.pitchReady='true'});
window.motionReview={ready:ring.ready,go,seek(from,to,progress){cancelAnimationFrame(animation);setBusy(false);step=progress===1?to:from;updatePage();paintScene(from+(to-from)*progress)},show(n,phase=0){cancelAnimationFrame(animation);setBusy(false);step=n;finalPhase=phase;finalProgress=phase;updatePage();paintScene(n)},get state(){return{step,busy,finalPhase,language,position:Number(stage.dataset.position)}}};
