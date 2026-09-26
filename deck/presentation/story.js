// Extends the approved T08.2A motion sequence without altering its first six states.
profiles.ru[1].explain='Встречи и шутки, которые Гриша оставляет для друзей.';
profiles.ru[2].explain='Проекты и рабочие новости без семейных публикаций.';
profiles.ru[3].explain='Эту часть профиля увидит любой посетитель.';
profiles.en[1].explain='Meetups and jokes Grigory keeps between friends.';
profiles.en[2].explain='Projects and work updates without family posts.';
profiles.en[3].explain='Anyone can see this part of his profile.';
profiles.ru.forEach(item=>item.final=true);
profiles.en.forEach(item=>item.final=true);


const storyRu={};
document.querySelectorAll('[data-t]').forEach(e=>storyRu[e.dataset.t]=e.innerHTML);
const storyEn={"secProblem": "The problem", "problemTitle": "Not everything<br>is for <span class=\"story-accent\">everyone.</span>", "problemBody": "Jokes with friends, family news and work projects are meant for different people. When those audiences meet, a personal moment may feel right for some and wrong for others.", "exampleFriends": "“My friends will get this”", "exampleFamily": "“I want to share this with my family”", "exampleWork": "“This is for my colleagues”", "problemAnswer": "With selecont, you choose <span class=\"story-accent\">the right context</span> for every post.", "secPost": "Posting · author’s view", "postTitle": "One post.<br><span class=\"story-accent\">Three circles.</span>", "postBody": "Grigory selects family, friends and colleagues. He publishes once — members of all three selected circles see the same post.", "postPrivacy": "The post is hidden from everyone else: <span class=\"story-accent\">Public is not selected.</span>", "chooseAudience": "Who can see this", "family": "Family", "friends": "Friends", "notSelected": "not selected", "postCaption": "We finally got together at home and looked through old photos.", "conceptNote": "Interface illustration", "cm1": "What a lovely day!", "cm2": "Let’s do it again.", "deletedReply": "Reply deleted", "cm3": "Is that the old photo album?", "deletedComment": "Comment deleted", "cm4": "Yes! We found it this weekend.", "secDiscuss": "Discussion", "discussTitle": "One post. <span class=\"story-accent\">Separate conversations.</span>", "discussBody": "Family and friends see one photo, but comments and replies stay within their own audience.", "viewFamily": "What family sees", "samePhoto": "The same post", "commentsLabel": "Comments on the post", "viewFriends": "What friends see", "deletionNote": "<span class=\"story-accent\">The text is removed. The thread stays.</span> Other people’s replies remain.", "likeNote": "One shared like count for the post.", "anonymous": "Anonymous", "registered": "Registered", "outside": "Follower outside the circle", "inside": "Follower in the circle", "author": "Author", "publicProfile": "Public profile and post", "publicComment": "Comment on a Public post", "privateProfile": "Private profile and post", "privateDiscuss": "Private discussion", "manageCircles": "Manage circles", "secRights": "Five access roles", "rightsTitle": "Who can see <span class=\"story-accent\">your context</span>", "rightsLead": "Following is not enough. The author grants access to a private circle.", "rightsNote": "Circle names and membership are hidden from viewers. The author manages all their circles.", "secControl": "Access control", "controlTitle": "You decide <span class=\"story-accent\">who stays in a circle.</span>", "controlBody": "Add someone to a circle and they see its profile and posts. Remove them and access closes.", "inCircle": "In “Friends”", "beforeTitle": "Sees the private side of your profile", "privatePosts": "Posts for friends", "privateComments": "Discussions with friends", "removePerson": "Remove<br>from circle", "publicOnly": "Sees Public", "afterTitle": "Sees only the public part", "noPrivatePosts": "Private posts are unavailable", "noPrivateComments": "Private threads are unavailable", "controlNote": "You manage the circles. Only you see their names and members.", "proofCircles": "Circles and profiles", "proofCirclesBody": "Different bios, photos and audiences", "proofPost": "Publishing", "proofPostBody": "One post for selected circles", "proofComments": "Discussions", "proofCommentsBody": "Replies, deletion and separate threads", "secProof": "Working today", "proofTitle": "From profile to conversation — <span class=\"story-accent\">in a working demo.</span>", "proofSummary": "Sign-in and sessions · following · photos · shared likes · access revocation", "checks": "checks passed", "proofNote": "Actual local product screens · test accounts · 25 September 2026", "secCompare": "What a context connects", "compareTitle": "One context. <span class=\"story-accent\">Three parts of sharing.</span>", "accounts": "Separate accounts", "accountsBody": "Profiles and conversations are separate, but each account needs its own upkeep.", "perPost": "Per-post settings", "perPostBody": "Choose who sees a post. The profile and its discussion remain separate questions.", "profileTerm": "Profile", "postTerm": "Post", "discussionTerm": "Discussion", "selecontBody": "One account. A context connects the profile variant, access to a post and its discussion.", "compareNote": "A circle’s access rules connect the profile, post and discussion.", "secSuggest": "Context Suggestions · future feature", "suggestTitle": "The system suggests.<br><span class=\"story-accent\">You choose the circle.</span>", "suggestBody": "A recommendation appears for a new follower. Only you see it: confirm the suggested circle or choose another.", "suggestNoAuto": "Without your decision, the person <span class=\"story-accent\">does not enter a private circle.</span>", "authorView": "Author’s view only", "newFollower": "New follower", "suggestedCircle": "Suggested circle", "colleagues": "Colleagues", "confirmCircle": "Confirm", "chooseOther": "Choose another", "futureNote": "Future feature concept", "secPilot": "Next stage", "pilotTitle": "From a working demo — <span class=\"story-accent\">to the first users.</span>", "pilotBody": "In the accelerator, we will find first users, observe real use and decide what to improve next.", "pilotOneTitle": "Find first users", "pilotOneBody": "Invite people who want to share different things with different groups.", "pilotTwoTitle": "Watch it in use", "pilotTwoBody": "Can people set up circles and publish a post with ease?", "pilotThreeTitle": "Learn what to improve", "pilotThreeBody": "What was useful and what should change first?", "pilotNote": "The next step: recruitment and results are still ahead.", "secAsk": "Founder · ITMO Accelerator application", "askTitle": "Georgy<br>Sapogovsky", "askBody": "Seeking a place in the ITMO Accelerator, <span class=\"story-accent\">a mentor and help finding selecont’s first users</span>.", "askNote": "Autumn 2026", "eulerKey": "At the centre: <span class=\"story-accent\">one shared post</span>.<br>Each circle is an audience.", "oneSharedPost": "One post", "eulerNote": "Audience diagram · circles chosen by the author", "compareLead": "The author chooses a circle once. It connects a profile version, access to a post and a separate conversation.", "journeyProfile": "A personal side", "journeyProfileBody": "One photo and bio for friends; another for family or colleagues.", "journeyPost": "The right people", "journeyPostBody": "One post can be shared with several selected circles at once.", "journeyTalk": "A separate conversation", "journeyTalkBody": "Each circle has its own reply thread under the shared post.", "journeyIndexProfile": "01 / PROFILE", "journeyIndexPost": "02 / POST", "journeyIndexTalk": "03 / DISCUSSION", "journeyComment": "What a lovely day!", "journeyReply": "Let’s get together again."};
// The founder's preferred English spelling is George Sapogovsky.
storyEn.askTitle = "George<br>Sapogovsky";
const originalRenderCopy=renderCopy;
renderCopy=function(){originalRenderCopy();const source=language==='ru'?storyRu:storyEn;document.querySelectorAll('[data-t]').forEach(e=>e.innerHTML=source[e.dataset.t]||storyRu[e.dataset.t]);};
const originalPaintScene=paintScene;
paintScene=function(position){
  // The problem is an interlude between the cover and approved ring introduction.
  // The ring→disc morph and all four physical sectors keep their original timeline.
  let base=position<2?position/2:position<=6?position-1:position<13?5:position<14?5+smooth(13,14,position):6;
  originalPaintScene(base);
  // Let outgoing text clear before the next message appears over the moving art.
  if(position<2){
    elements.cover.style.opacity=String(Number(elements.cover.style.opacity)*(1-smooth(.05,.45,position)));
    elements.logo.style.opacity=String(Number(elements.logo.style.opacity)*(1-smooth(.05,.45,position)));
    elements.intro.style.opacity=String(Number(elements.intro.style.opacity)*smooth(1.45,1.9,position));
  }
  if(position>6){
    const exit=1-smooth(6,6.6,position);
    elements.profiles.style.opacity=String(Number(elements.profiles.style.opacity)*exit);
    elements.rings.style.opacity=String(Number(elements.rings.style.opacity)*exit);
  }
  document.querySelectorAll('.story-slide').forEach(slide=>{
    const index=Number(slide.dataset.story),delta=position-index;
    const visibility=clamp(1-Math.abs(delta));
    const opacity=smooth(0,.82,visibility);
    slide.style.opacity=String(opacity);slide.style.visibility=opacity>.001?'visible':'hidden';
    slide.setAttribute('aria-hidden',String(opacity<.99));
    for(const child of slide.children)child.style.opacity=String(smooth(.45,.85,visibility));
    slide.querySelectorAll('.reveal').forEach((el,i)=>{
      const amount=(1-smooth(.1+Math.min(i,3)*.035,1,visibility))*55;
      const dir=el.dataset.direction;
      el.style.transform=dir==='up'?`translateY(${amount}px)`:`translateX(${dir==='right'?amount:-amount}px)`;
    });
  });
  // Page color is set per rendered state, without a delayed CSS transition.
  document.querySelector('#page-number').style.color=[10,13,14,16].includes(Math.round(position))?'#dceefe':'#06182b';
  stage.dataset.position=position.toFixed(4);
};
updatePage=function(){stage.dataset.step=String(step);document.querySelector('#page-number').textContent=String(step+1).padStart(2,'0')+' / 17';};
function fullSetStep(next){
  if(busy)return;
  next=clamp(next,0,16);
  if(next===step)return;
  const from=step;
  step=next;
  updatePage();
  if(Math.abs(next-from)>1){paintScene(next);return}
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const total=reduced?0:duration*(Math.min(from,next)===2?1.4:.92);
  setBusy(true);
  let started;
  const frame=now=>{
    if(started===undefined)started=now;
    const t=total?clamp((now-started)/total):1;
    paintScene(from+(next-from)*ease(t));
    if(t<1)animation=requestAnimationFrame(frame);
    else{setBusy(false);paintScene(next)}
  };
  animation=requestAnimationFrame(frame);
}

// The original handlers are bound to a seven-state proof. Replace only the controls;
// the original artwork and its rendering functions remain the source of truth.
for(const id of ['next','previous','restart','language']){
  const old=document.querySelector('#'+id);
  const fresh=old.cloneNode(true);
  old.replaceWith(fresh);
}
document.querySelector('#next').addEventListener('click',()=>fullSetStep(step===16?0:step+1));
document.querySelector('#previous').addEventListener('click',()=>fullSetStep(step===0?16:step-1));
document.querySelector('#restart').addEventListener('click',()=>{if(busy)return;step=0;updatePage();paintScene(0)});
document.querySelector('#language').addEventListener('click',()=>{if(busy)return;language=language==='ru'?'en':'ru';renderCopy();paintScene(step)});
stage.addEventListener('click',event=>{
  if(event.target.closest('button'))return;
  event.stopImmediatePropagation();
  fullSetStep(step===16?0:step+1);
},true);
document.addEventListener('keydown',event=>{
  if(event.target.matches('select,input,textarea'))return;
  const key=event.key;
  if(!['ArrowRight','ArrowLeft',' ','Home','End'].includes(key))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(key==='Home')fullSetStep(0);
  else if(key==='End')fullSetStep(16);
  else if(key==='ArrowRight'||key===' ')fullSetStep(step===16?0:step+1);
  else fullSetStep(step===0?16:step-1);
},true);

step=clamp(Number(new URLSearchParams(location.search).get('step'))||0,0,16);
function fitPresentation(){
  const wrapper=document.querySelector('#stage-wrap');
  const main=document.querySelector('main');
  const availableHeight=Math.max(300,innerHeight-document.querySelector('.review-bar').offsetHeight-90);
  const availableWidth=main.clientWidth-48;
  wrapper.style.width=Math.min(availableWidth,availableHeight*16/9)+'px';
  fit();
}
addEventListener('resize',fitPresentation);
fitPresentation();
renderCopy();
updatePage();
paintScene(step);
window.motionReview={ready:ring.ready,seek(from,to,progress){cancelAnimationFrame(animation);setBusy(false);step=progress===1?to:from;updatePage();paintScene(from+(to-from)*progress)},go:fullSetStep,get state(){return{step,busy,language,position:Number(stage.dataset.position)}}};
