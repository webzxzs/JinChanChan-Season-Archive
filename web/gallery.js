"use strict";
const $=id=>document.getElementById(id);
const TABS={units:"弈子一览",traits:"羁绊一览",augments:"海克斯强化",boards:"赛季机制",seasons:"赛季资料",patches:"补丁变更"};
const KEY={units:"棋子名称",traits:"羁绊名称",augments:"强化名称",boards:"玩法名称",seasons:"赛季名称",patches:"名称"};
// Public theme numbering is not always the same as Tencent SDK's internal S-code.
// Preserve the underlying SDK code alongside these well-known public labels.
const PUBLIC_SET={"自然之力":"S18","星神":"S17","英雄联盟传奇":"S16",
 "天下无双格斗大会":"S15","赛博城市":"S14","双城传说2":"S13",
 "魔法乱斗":"S12","画之灵":"S11","强音对决":"S10",
 "符文大陆传奇":"S9","怪兽入侵":"S8","巨龙之巢":"S7",
 "双城传说":"S6"};
const state={tab:"units",season:"",query:"",trait:"",cost:"",augment:"",version:"",status:"",page:1,items:[],total:0,pages:0,showSkills:false};
const zh=new Intl.Collator("zh-CN",{numeric:true,sensitivity:"base"});
const prior=new URLSearchParams(location.search);
let catalog=[],activeRequest=0,debounce=0;
let expanded=new Set();
function html(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function validImage(v){return /^https:\/\/game\.gtimg\.cn\/images\/[-a-zA-Z0-9_./%]+\.(png|webp|jpg|jpeg)(\?.*)?$/.test(v||"") ? v : "";}
function validLink(v){try{let u=new URL(v);return ["https:","http:"].includes(u.protocol)?u.href:"";}catch{return "";}}
function short(v,max=200){v=String(v??"");return v.length>max?v.slice(0,max)+"…":v;}
function fmt(n){return Number(n||0).toLocaleString("zh-CN");}
async function get(path){const r=await fetch(path,{cache:"no-store"});if(!r.ok)throw Error("接口返回 "+r.status);return r.json();}
function paramsForQuery(){const u=new URLSearchParams({season:state.season,q:state.query,trait:state.trait,cost:state.cost,
 category:state.tab==="augments"?state.augment:"",
 version:state.version,status:state.status,sort:state.tab==="units"?"cost":"name",
 limit:"60",page:String(state.page)});return u;}
function updateUrl(){const p=new URLSearchParams();if(state.season)p.set("season",state.season);if(state.tab!=="units")p.set("tab",state.tab);
 if(state.query)p.set("q",state.query);if(state.page>1)p.set("page",String(state.page));history.replaceState(null,"",location.pathname+(p.size?"?"+p:""));}
function loading(){ $("results").innerHTML='<div class="skeleton">正在加载国服资料…</div>'; }
function error(e){$("results").innerHTML='<div class="empty"><b>数据读取失败</b>'+html(e.message||e)+'</div>';}
function navName(e){return e.name||e.ref;}
function seasonRank(e){
 const dt=Date.parse(e.date||"");
 if(Number.isFinite(dt))return dt;
 const raw=e.season||"";const match=raw.match(/^S(\d+)$/);
 return match?Number(match[1])*1000000:0;
}
function renderNav(){
 const q=$("season-query").value.trim().toLowerCase();
 const groups=new Map();
 for(const e of catalog){
  if(q&&!((e.name+" "+e.season+" "+e.ref+" "+(PUBLIC_SET[e.name]||"")).toLowerCase().includes(q)))continue;
  const group=e.kind==="indexed"?e.name:"历史/资料补录";
  if(!groups.has(group))groups.set(group,[]);
  groups.get(group).push(e);
 }
 const arr=[...groups].sort((a,b)=>{
  const aRank=Math.max(...a[1].map(seasonRank)),bRank=Math.max(...b[1].map(seasonRank));
  return bRank-aRank||zh.compare(a[0],b[0]);
 });
 $("season-count").textContent=String(catalog.length);
 $("all-sets").classList.toggle("active",!state.season);
 $("season-nav").innerHTML=arr.map(([name,entries],i)=>{
  entries.sort((a,b)=>seasonRank(b)-seasonRank(a)||zh.compare(b.season||"",a.season||""));
  const inside=entries.some(e=>e.ref===state.season);
  const isOpen=q||inside||expanded.has(name)||i<2;
  return '<section class="set-group '+(isOpen?"":"collapsed")+'"><button class="group-title" data-toggle="'+html(name)+'">'+
    '<span>'+html(name)+'</span><small>'+entries.length+' 版本</small><i>▾</i></button>'+
    '<div class="group-items">'+entries.map(e=>
      '<button class="set-option '+(e.ref===state.season?"active":"")+'" data-set="'+html(e.ref)+'" title="'+html(e.ref)+'" aria-current="'+(e.ref===state.season)+'">'+
      '<span class="season-chip">'+html(PUBLIC_SET[e.name]||e.season||"档案")+'</span><span class="set-text">'+html(e.kind==="indexed"?((e.version||e.name)+" · 源 "+e.season):e.name)+'</span>'+
      (e.status==="unavailable"||e.status==="partial"?'<i class="incomplete" title="历史数据不完整"></i>':"")+'</button>').join("")+
    '</div></section>';
 }).join("")||'<div class="skeleton">没有找到对应赛季</div>';
}
function setHeading(){
 const e=catalog.find(e=>e.ref===state.season);
 $("breadcrumb").textContent=e?e.name:"全部赛季";
 $("season-name").textContent=e?e.name:"全赛季图鉴";
 $("season-desc").textContent=e?
  "按该模式独立版本查看弈子、羁绊及完整效果；与其他赛季和返场数值分开记录。":
  "包含从首发到当前的国服赛季、限时玩法与返场模式，支持跨赛季检索。";
 $("season-tag").textContent=e?(PUBLIC_SET[e.name]||e.season||"历史研究")+" · 源索引 "+(e.season||"—")+" · 模式 "+(e.mode||"历史"):"所有历史模式";
 $("season-version").textContent=e&&e.version?"配置 "+e.version:"官方历史资料与多版本快照";
 $("season-availability").textContent=e&&e.status==="unavailable"?"历史配置缺失":(e&&e.status==="partial"?"部分数据缺失":
  (state.tab==="augments"&&e&&e.augment_status&&e.augment_count===0?e.augment_status:""));
}
async function updateCounts(){
 const summary=await get("/api/summary?"+new URLSearchParams({season:state.season}));
 for(const key of ["units","traits","augments","boards","patches"])$("count-"+key).textContent=fmt(summary.counts[key]);
}
function closeMobile(){$("sidebar").classList.remove("open");$("mobile-overlay").hidden=true;}
async function chooseSeason(ref){
 state.season=ref;state.page=1;state.query="";state.trait="";state.cost="";state.augment="";state.version="";state.status="";
 $("search").value="";closeMobile();setHeading();renderNav();
 await updateCounts();await load();
}
function chooseTab(tab){
 if(!TABS[tab])return;
 state.tab=tab;state.page=1;state.query="";state.trait="";state.cost="";state.augment="";state.version="";state.status="";
 $("search").value="";
 for(const node of document.querySelectorAll("[data-tab]")){
  const active=node.dataset.tab===tab;
  node.classList.toggle("active",active);node.setAttribute("aria-selected",active?"true":"false");
 }
 $("costbar").hidden=tab!=="units";$("trait-filter").hidden=tab!=="units";
 $("augmentbar").hidden=tab!=="augments";
 $("search").placeholder=({
  units:"搜索弈子、技能、羁绊…",traits:"搜索羁绊名称、人数效果…",
  augments:"搜索海克斯名称、描述、强化ID…",
  boards:"搜索棋盘、奇遇、站位机制…",seasons:"搜索赛季主题、特色…",
  patches:"搜索英雄、羁绊或变更字段…"})[tab];
 $("section-title").textContent=TABS[tab];load();
 setHeading();
}
function options(id,values,title,selected){
 const el=$(id);el.replaceChildren();
 const all=document.createElement("option");all.value="";all.textContent=title;el.append(all);
 for(const s of values||[]){const o=document.createElement("option");o.value=s;o.textContent=s;el.append(o);}
 el.value=selected;
}
function fee(v){const x=Number(v||0);return x>=6?6:x||1;}
function portrait(url,name){
 const safe=validImage(url);
 return '<div class="portrait"><div class="portrait-fallback">'+html((name||"弈")[0])+'</div>'+
  (safe?'<img loading="lazy" alt="'+html(name)+'" src="'+html(safe)+'">':"")+'</div>';
}
function tierGroup(rows,kind){
 return '<section class="tier"><div class="tier-head"><span class="tier-marker">'+html(kind)+'</span><b>'+
 (kind==="6+"?"6费及以上":kind+"费")+'</b><small class="tier-count">'+rows.length+' 名</small></div>'+
 '<div class="unit-grid">'+rows.map(unitCard).join("")+'</div></section>';
}
function unitCard(r,index){
 const cost=fee(r["费用"]);const name=r["棋子名称"]||"未知";
 const traits=[r["羁绊一"],r["羁绊二"],r["羁绊三"]].filter(Boolean);
 return '<article tabindex="0" role="button" class="unit c'+cost+'" data-index="'+r._index+'" title="'+html(name)+'">'+
  '<span class="fee-corner">'+html(r["费用"]||"—")+'</span>'+
  portrait(r["头像"],name)+'<h3>'+html(name)+'</h3>'+
  '<div class="traits-mini">'+html(traits.join(" · ")||"待核实羁绊")+'</div>'+
  (state.showSkills?'<div class="skill-peek"><b>'+html(r["技能名称"]||"技能")+'</b>'+html(short(r["技能完整效果"],140))+'</div>':"")+
 '</article>';
}
function badges(effect){
 const chunks=String(effect||"").split("|").map(s=>s.trim()).filter(Boolean);
 return chunks.slice(0,5).map(x=>{
  let m=x.match(/^\(?[（]?(\d+)[)）]?/);return m?'<span>'+html(m[1])+' 人</span>':'';
 }).filter(Boolean).join("");
}
function infoCard(r,index){
 const trait=state.tab==="traits",name=r[KEY[state.tab]]||"资料未命名";
 const description=trait?[r["羁绊基础说明"],r["各档人数与效果"]].filter(Boolean).join(" "):
  state.tab==="boards"?r["实际效果"]||"":
  state.tab==="seasons"?r["核心特色"]||r["代表机制"]||"":
  ((r["差异"]||[]).slice(0,2).map(x=>x["字段"]+":"+short(x["旧值"],35)+" → "+short(x["新值"],35)).join(" · "));
 const icon=validImage(r["头像"]);
 const header=trait?'<img class="trait-icon" alt="" loading="lazy" src="'+html(icon)+'">':'<span class="trait-icon trait-fallback">'+(state.tab==="boards"?"⌗":state.tab==="patches"?"↗":"▥")+'</span>';
 const sub=trait?("羁绊 · "+(r["配置版本"]||"历史版本")):
  (r["赛季名称"]||"")+(r["配置版本"]?" · "+r["配置版本"]:"");
 return '<article class="info-card" tabindex="0" role="button" data-index="'+index+'"><div class="info-top">'+
  (icon&&trait?header:'<span class="trait-icon trait-fallback">'+(trait?"✧":state.tab==="boards"?"⌗":"▥")+'</span>')+
  '<div><strong>'+html(name)+'</strong><small>'+html(short(sub,60))+'</small></div></div>'+
  '<div class="info-desc">'+html(short(description,280))+'</div>'+
  (trait?'<div class="breakpoints">'+badges(r["各档人数与效果"])+'</div><div class="mini-members">'+html(short(r["包含棋子"],120))+'</div>':
  '<div class="mini-members">'+html(r["核验状态"]||"历史数据")+'</div>')+
  '</article>';
}
function augmentCard(r,index){
 const level=r["官方等级"],tier=r["档位分类"]||"未知等级";
 const color=level==="1"?"silver":level==="2"?"gold":level==="3"?"prismatic":"special";
 const icon=validImage(r["图标"]);
 const label=r["强化名称"]||"未命名强化";
 return '<article role="button" tabindex="0" class="augment-card '+color+'" data-index="'+index+'" aria-label="查看'+html(label)+'">'+
  '<div class="augment-icon">'+(icon?'<img loading="lazy" alt="" src="'+html(icon)+'">':'<span>✦</span>')+'</div>'+
  '<div class="augment-body"><div class="augment-title">'+html(label)+'</div>'+
  '<span class="augment-tier">'+html(tier)+'</span>'+
  '<p>'+html(short(r["强化效果"],320))+'</p>'+
  '<small>'+html(r["赛季名称"]||"")+ ' · '+html(r["配置版本"]||"")+'</small></div></article>';
}
function draw(data){
 state.items=data.items;state.total=data.total;state.pages=data.pages;state.page=data.page;
 $("result-count").textContent="共 "+fmt(data.total)+" 条记录 · 第 "+fmt(data.page)+" / "+fmt(Math.max(1,data.pages))+" 页";
 options("version-filter",data.versions||[],"全部配置版本",state.version);
 options("status-filter",data.statuses||[],"全部核验状态",state.status);
 if(state.tab==="units")options("trait-filter",data.trait_options||[],"全部羁绊",state.trait);
 $("cost-options").querySelectorAll("[data-cost]").forEach(b=>b.classList.toggle("selected",b.dataset.cost===state.cost));
 $("augment-options").querySelectorAll("[data-augment]").forEach(b=>b.classList.toggle("selected",b.dataset.augment===state.augment));
 if(!data.items.length){$("results").innerHTML='<div class="empty"><b>这个范围还没有匹配记录</b>'+
  (state.tab==="augments"?"该赛季在目前官方快照中没有可用海克斯数据；这不等于玩法里一定没有海克斯。":"试着清空筛选条件，或者切换其他历史模式查看。")+
  '<br>不同赛季的强化符文不会相互补齐。</div>'; $("pager").innerHTML="";return;}
 if(state.tab==="units"){
  const groups=new Map();
  data.items.forEach((r,i)=>{
    const cost=fee(r["费用"]);const t=cost>=6?"6+":String(cost);
    const clone={...r,_index:i};
    if(!groups.has(t))groups.set(t,[]);
    groups.get(t).push(clone);
  });
  $("results").className="results hero-groups";
  $("results").innerHTML=[...groups].sort((a,b)=>Number(a[0])-Number(b[0])).map(([tier,rows])=>tierGroup(rows,tier)).join("");
 }else if(state.tab==="augments"){
  $("results").className="results augment-grid";
  $("results").innerHTML=data.items.map(augmentCard).join("");
 }else{
  $("results").className="results "+(state.tab==="traits"?"list-grid":"feature-grid");
  $("results").innerHTML=data.items.map((r,i)=>state.tab==="traits"?infoCard(r,i):
    '<article class="feature-card" role="button" tabindex="0" data-index="'+i+'"><h3>'+html(r[KEY[state.tab]]||"资料记录")+'</h3>'+
    '<p>'+html(short(state.tab==="boards"?r["实际效果"]:
       state.tab==="seasons"?r["核心特色"]||r["代表机制"]:
       (r["差异"]||[]).slice(0,3).map(x=>x["字段"]+": "+short(x["旧值"],35)+" → "+short(x["新值"],35)).join("\n"),330))+'</p>'+
    '<small>'+html(r["赛季名称"]||"")+ ' · '+html(r["核验状态"]||"版本差异")+'</small></article>'
  ).join("");
 }
 $("pager").innerHTML=data.pages<=1?"":'<button id="prev" '+(data.page<=1?"disabled":"")+'>← 上一页</button><span>第 '+data.page+' / '+data.pages+' 页</span><button id="next" '+(data.page>=data.pages?"disabled":"")+'>下一页 →</button>';
}
async function load(){
 const id=++activeRequest;loading();updateUrl();
 try{const data=await get("/api/records/"+state.tab+"?"+paramsForQuery());
  if(id!==activeRequest)return;draw(data);
 }catch(e){if(id===activeRequest)error(e);}
}
function detailPart(title,body){return body?'<section class="detail-section"><h3>'+html(title)+'</h3><div class="body">'+html(body)+'</div></section>':"";}
function stat(label,v){return v?'<div><small>'+html(label)+'</small><strong>'+html(v)+'</strong></div>':"";}
function detailOpen(index){
 const r=state.items[index];if(!r)return;
 let title=r[KEY[state.tab]]||"详情",isUnit=state.tab==="units",isTrait=state.tab==="traits";
 const img=validImage(r["头像"]||r["图标"]);
 let head='<div class="detail-head">'+(img?'<img class="detail-pic" src="'+html(img)+'" alt="">':'<div class="detail-pic fallback">✧</div>')+
 '<div class="detail-title"><h2 id="drawer-name">'+html(title)+'</h2><p>'+html(r["赛季名称"]||"")+'<br>'+html(r["配置版本"]||r["下一补丁"]||"历史资料")+'</p></div></div>';
 let content="";
 if(isUnit){
  const parts=[r["羁绊一"],r["羁绊二"],r["羁绊三"]].filter(Boolean);
  content='<section class="detail-section"><h3>所属羁绊</h3><div class="detail-tags">'+
   parts.map(t=>'<button data-trait="'+html(t)+'">'+html(t)+'</button>').join("")+'</div></section>'+
   detailPart(r["技能名称"]||"技能效果",r["技能完整效果"])+
   '<section class="detail-section"><h3>基础属性</h3><div class="stats-grid">'+
   [stat("费用",r["费用"]),stat("生命值",r["生命值"]),stat("攻击力",r["攻击力"]),stat("护甲",r["护甲"]),stat("魔抗",r["魔抗"]),stat("攻击速度",r["攻击速度"]),stat("初始法力",r["初始法力"]),stat("最大法力",r["最大法力"])].join("")+'</div></section>';
 }else if(isTrait){
  content=detailPart("羁绊基础效果",r["羁绊基础说明"])+detailPart("各档人数与增益",String(r["各档人数与效果"]||"").replaceAll("|","\n"))+
   detailPart("包含弈子",r["包含棋子"]);
 }else if(state.tab==="augments"){
  content=detailPart("强化符文完整效果",r["强化效果"])+
   '<section class="detail-section"><h3>强化类别与标识</h3><div class="stats-grid">'+
   [stat("强化档位",r["档位分类"]),stat("官方等级",r["官方等级"]),
    stat("强化 ID",r["强化ID"]),stat("英雄强化类型",r["英雄强化类型"]),
    stat("传说强化标记",r["是否传说强化"]),stat("羁绊关联",r["羁绊关联ID"])].join("")+'</div></section>';
 }else if(state.tab==="boards")content=detailPart("机制完整效果",r["实际效果"])+detailPart("触发条件",r["触发条件"])+detailPart("影响范围",r["影响范围"]);
 else if(state.tab==="seasons")content=detailPart("赛季特色",r["核心特色"])+detailPart("代表机制",r["代表机制"]);
 else{
  content='<section class="detail-section"><h3>历史补丁</h3><div class="body">'+html((r["上一补丁"]||"初版")+" → "+r["下一补丁"])+'</div></section>'+
   (r["差异"]||[]).map(item=>'<div class="patchdiff"><b>'+html(item["字段"])+'</b><div class="diff-sides"><div><small>变更前</small>'+html(short(item["旧值"],1700))+'</div><div><small>变更后</small>'+html(short(item["新值"],1700))+'</div></div></div>').join("");
 }
 content+=detailPart("核验状态与版本说明",[r["核验状态"],r["数据说明"],r["数据完整度"],r["版本说明"]].filter(Boolean).join("\n"));
 const link=validLink(r["来源网址"]);if(link)content+='<section class="detail-section"><h3>官方或历史来源</h3><a class="source-link" href="'+html(link)+'" target="_blank" rel="noopener noreferrer">↗ '+html(short(link,250))+'</a></section>';
 $("drawer-body").innerHTML=head+content;
 $("drawer").hidden=false;$("shade").hidden=false;document.body.style.overflow="hidden";$("close").focus();
}
function closeDrawer(){$("drawer").hidden=true;$("shade").hidden=true;document.body.style.overflow="";}
function bind(){
 $("season-nav").addEventListener("click",e=>{
  const toggle=e.target.closest("[data-toggle]");
  if(toggle){const v=toggle.dataset.toggle;expanded.has(v)?expanded.delete(v):expanded.add(v);renderNav();return;}
  const option=e.target.closest("[data-set]");if(option)chooseSeason(option.dataset.set);
 });
 $("all-sets").addEventListener("click",()=>chooseSeason(""));
 $("season-query").addEventListener("input",renderNav);
 $("tabs").addEventListener("click",e=>{const tab=e.target.closest("[data-tab]");if(tab)chooseTab(tab.dataset.tab);});
 $("search").addEventListener("input",e=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.query=e.target.value;state.page=1;load();},200);});
 for(const [id,key] of [["trait-filter","trait"],["version-filter","version"],["status-filter","status"]]){
  $(id).addEventListener("change",e=>{state[key]=e.target.value;state.page=1;load();});
 }
 $("cost-options").addEventListener("click",e=>{
  const b=e.target.closest("[data-cost]");if(!b)return;
  state.cost=b.dataset.cost;state.page=1;load();
 });
 $("augment-options").addEventListener("click",e=>{
  const b=e.target.closest("[data-augment]");if(!b)return;
  state.augment=b.dataset.augment;state.page=1;load();
 });
 $("show-skills").addEventListener("change",e=>{state.showSkills=e.target.checked;load();});
 $("results").addEventListener("click",e=>{const card=e.target.closest("[data-index]");if(card)detailOpen(Number(card.dataset.index));});
 $("results").addEventListener("keydown",e=>{if((e.key==="Enter"||e.key===" ")&&e.target.matches("[data-index]")){e.preventDefault();detailOpen(Number(e.target.dataset.index));}});
 $("results").addEventListener("error",e=>{if(e.target.tagName==="IMG")e.target.remove();},true);
 $("pager").addEventListener("click",e=>{if(e.target.id==="prev"&&state.page>1)state.page--;else if(e.target.id==="next"&&state.page<state.pages)state.page++;else return;load();$("section-title").scrollIntoView({behavior:"smooth"});});
 $("close").addEventListener("click",closeDrawer);$("shade").addEventListener("click",closeDrawer);
 $("drawer-body").addEventListener("click",e=>{const x=e.target.closest("[data-trait]");if(x){closeDrawer();chooseTab("traits");state.query=x.dataset.trait;$("search").value=state.query;load();}});
 $("reload").addEventListener("click",()=>{updateCounts();load();});
 $("mobile-menu").addEventListener("click",()=>{$("sidebar").classList.add("open");$("mobile-overlay").hidden=false;});
 $("mobile-overlay").addEventListener("click",closeMobile);
 addEventListener("keydown",e=>{if(e.key==="Escape"){closeDrawer();closeMobile();}if(e.key==="/"&&!/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();$("search").focus();}});
}
async function start(){
 bind();
 try{
  const c=await get("/api/catalog");catalog=c.items||[];
  const wanted=prior.get("season");
  state.season=wanted||catalog.find(e=>e.name==="自然之力"&&e.season==="S19")?.ref||catalog.find(e=>e.kind==="indexed"&&e.status==="ok")?.ref||"";
  state.tab=TABS[prior.get("tab")]?prior.get("tab"):"units";
  state.query=prior.get("q")||"";state.page=Math.max(1,Number(prior.get("page"))||1);
  $("search").value=state.query;
  document.querySelectorAll("[data-tab]").forEach(b=>{const active=b.dataset.tab===state.tab;b.classList.toggle("active",active);b.setAttribute("aria-selected",String(active));});
  $("costbar").hidden=state.tab!=="units";$("trait-filter").hidden=state.tab!=="units";
  $("augmentbar").hidden=state.tab!=="augments";
  $("section-title").textContent=TABS[state.tab];renderNav();setHeading();await updateCounts();await load();
 }catch(e){error(e);}
}
start();
