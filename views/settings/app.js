const bridge = window.AstrBotPluginView;
const root = document.getElementById('render');
const notice = document.getElementById('notice');
let cfg;
let dirty = false;
let chatProviders = [];
let providerListError = '';
const fallback = { robot_setup:{enabled:false,wake_enabled:true,wake_groups:[],instances:[],groups:[],group_sessions:[]},guard_options:{bot_guard_enabled:true,gate_groups:[],inject_enabled:true,recent_count:6,related_count:8,recall_search_limit:5000,max_inject_chars:2400,max_saved_per_group:10000,verbose_log:false},semantic_options:{semantic_enabled:false,semantic_provider_id:'',semantic_timeout_seconds:20} };

const e = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const v = (path) => path.split('.').reduce((obj,key) => obj?.[key], cfg);
const set = (path,val) => { const parts=path.split('.');let at=cfg; for (let i=0;i<parts.length-1;i++)at=at[parts[i]];at[parts.at(-1)]=val; dirty=true;notice.textContent='有尚未保存的修改'; };
const toggle = (path,label,hint='')=> `<div class="inlinecheck"><input type="checkbox" data-bind="${e(path)}" ${v(path)?'checked':''} id="${e(path)}"><label for="${e(path)}">${e(label)}</label></div>${hint?`<p class="hint">${e(hint)}</p>`:''}`;
const field = (path,label,placeholder='',type='text',desc='')=>`<div class="field"><label>${e(label)}</label><input data-bind="${e(path)}" type="${e(type)}" value="${e(v(path))}" placeholder="${e(placeholder)}" ${type==='number'?'min="0"':''}>${desc?`<span class="tiny">${e(desc)}</span>`:''}</div>`;
const select = (path,label,options,emptyLabel='先在基础表登记') => `<div class="field">${label?`<label>${e(label)}</label>`:''}<select data-bind="${e(path)}"><option value="">${e(emptyLabel)}</option>${options.map(x=>`<option value="${e(x.id)}" ${v(path)===x.id?'selected':''}>${e(x.label)}</option>`).join('')}</select></div>`;
const blocks=(title,desc,content,index)=>`<section class="section"><div class="sec-head"><div><h2 class="sec-title"><span class="step">${index}</span>${e(title)}</h2><p class="sec-desc">${e(desc)}</p></div></div>${content}</section>`;
const groups=()=>cfg.robot_setup.groups||[];
const instances=()=>cfg.robot_setup.instances||[];
const sessions=()=>cfg.robot_setup.group_sessions||[];
const instanceOptions=()=>instances().filter(x=>x.platform_id).map(x=>({id:x.platform_id,label:`${x.instance_label||x.platform_id} · ${x.platform_id}`}));
const groupOptions=()=>groups().filter(x=>x.group_id).map(x=>({id:x.group_id,label:`${x.group_label||x.group_id} · ${x.group_id}`}));
const scope=(path,title)=>`<div class="block"><h3 class="subtitle">${e(title)}</h3><p class="hint">不勾选任何群 = 所有群（包含未登记的群）。若取消最后一个勾选项，范围会扩大到所有群，需要二次确认。</p><div class="scope-items">${groupOptions().length?groupOptions().map(g=>`<label><input type="checkbox" data-scope="${e(path)}" data-id="${e(g.id)}" ${(v(path)||[]).includes(g.id)?'checked':''}> ${e(g.label)}</label>`).join(''):'<span class="muted">请先在基础表登记QQ群</span>'}</div></div>`;

function renderBase(){
 let items=instances().map((entry,i)=>`<tr><td>${field(`robot_setup.instances.${i}.instance_label`,'','机器人A')}</td><td>${field(`robot_setup.instances.${i}.platform_id`,'','bot-a')}</td><td>${field(`robot_setup.instances.${i}.self_qq`,'','可留空')}</td><td>${field(`robot_setup.instances.${i}.bot_name`,'','机器人A')}</td><td><button class="danger small" data-action="rm-instance" data-i="${i}">删除</button></td></tr>`).join('');
 let gr=groups().map((item,i)=>`<tr><td>${field(`robot_setup.groups.${i}.group_label`,'','示例群A')}</td><td>${field(`robot_setup.groups.${i}.group_id`,'','123456789')}</td><td><button class="danger small" data-action="rm-group" data-i="${i}">删除</button></td></tr>`).join('');
 return blocks('基础参数表','后续实例和群聊选择器只引用这里登记的数据。新增或修改后先保存。',
 `<div class="block"><div class="subhead"><h3>本地机器人实例</h3><button class="soft small" data-action="add-instance">+ 添加实例</button></div><div class="tablewrap"><table class="data-table"><thead><tr><th>显示名称</th><th>平台实例ID</th><th>本机机器人QQ号</th><th>机器人名称</th><th></th></tr></thead><tbody>${items||'<tr><td colspan="5" class="muted">暂无实例</td></tr>'}</tbody></table></div><p class="hint">平台实例 ID 必须与 AstrBot 平台列表一致；QQ 号建议填写，便于自动识别本机其他机器人。</p></div>
 <div class="block"><div class="subhead"><h3>QQ群聊 ID</h3><button class="soft small" data-action="add-group">+ 添加群聊</button></div><div class="tablewrap"><table class="data-table"><thead><tr><th>群聊备注</th><th>QQ群号</th><th></th></tr></thead><tbody>${gr||'<tr><td colspan="3" class="muted">暂无群聊</td></tr>'}</tbody></table></div></div>`, '0');
}
function renderInstances(){
 const cards=instances().map((inst,i)=>{
 const base=`robot_setup.instances.${i}`;
 return `<article class="card"><h4>${e(inst.instance_label||inst.platform_id||'新机器人')}</h4><span class="pill">${e(inst.platform_id||'待登记实例ID')}</span>
 <div class="formgrid" style="margin-top:13px">${select(base+'.wake_mode','唤醒正则作用模式',[{id:'shared',label:'所有群使用同一条正则'},{id:'per_group',label:'允许群聊单独覆盖'}],'请选择模式')}${field(base+'.wake_regex','默认唤醒正则','例如 (机器人A|小A)')}</div>
 ${toggle(base+'.keyword_enabled','启用这个机器人的正则唤醒')}
 <p class="hint">使用 Python re.search，句中包含即可匹配；默认正则留空=不通过该正则唤醒（原生@和指令不受影响）。</p></article>`;
 }).join('');
 return `<div class="block"><h3 class="subtitle">机器人实例的默认唤醒规则</h3><div class="rowcards">${cards||'<div class="empty">先在顶部基础参数表中添加机器人实例。</div>'}</div></div>`;
}
function renderBots(session,i){
 const bots=Array.isArray(session.bots)?session.bots:[];
 return `<div class="block"><div class="subhead"><h3 class="subtitle">本会话群机器人通讯录</h3><button class="soft small" data-action="add-bot" data-i="${i}">+ 添加机器人</button></div>
 <div class="tiny">逐条登记其他机器人的 QQ 号与代号。别名可以留空；QQ号与代号必须填写。只按QQ号判定机器人身份；未填完的条目请继续填写或移除。</div>
 ${bots.map((s,j)=>{const parts=String(s).split('|');return `<div class="botrows">
 <input data-bot="${i}" data-idx="${j}" data-part="0" value="${e(parts[0]||'')}" placeholder="机器人QQ号">
 <input data-bot="${i}" data-idx="${j}" data-part="1" value="${e(parts[1]||'')}" placeholder="代号，如小助手">
 <input data-bot="${i}" data-idx="${j}" data-part="2" value="${e(parts[2]||'')}" placeholder="可不填：别名1,别名2">
 <button class="danger small" data-action="rm-bot" data-i="${i}" data-j="${j}">移除</button></div>`}).join('')||'<p class="empty">通讯录为空，当前群无法按 QQ 号识别未登记的第三方机器人。</p>'}</div>`;
}
function renderSessions(){
 const cards=sessions().map((item,i)=>{
 const base=`robot_setup.group_sessions.${i}`;
 const inst=instances().find(x=>x.platform_id===item.platform_id);
 const showCustom=inst?.wake_mode==='per_group';
 return `<article class="card"><div class="subhead"><h4>${e((instances().find(x=>x.platform_id===item.platform_id)?.instance_label||item.platform_id||'待选实例') + ' · ' + (groups().find(x=>x.group_id===item.group_id)?.group_label||item.group_id||'待选群聊'))}</h4><button class="small danger" data-action="rm-session" data-i="${i}">删除会话</button></div>
 <div class="formgrid">${select(base+'.platform_id','选择机器人实例',instanceOptions())}${select(base+'.group_id','选择QQ群聊',groupOptions())}</div>
 ${toggle(base+'.keyword_enabled','本群允许关键词唤醒')}
 ${showCustom?`${toggle(base+'.use_custom_wake_regex','本群使用独立于实例的唤醒正则')}${item.use_custom_wake_regex?field(base+'.wake_regex','本群专用正则','例如 机器人A在吗','开启专用开关后必须填写正则，或关闭此开关以继承默认'):'<p class="tiny">当前继承该实例的默认正则。</p>'}`:'<p class="hint">当前实例选择了「所有群使用同一条正则」，此群自动继承默认唤醒正则。</p>'}
 ${renderBots(item,i)}</article>`;
 }).join('');
 return `<div class="block"><div class="subhead"><h3>不同机器人实例下的QQ群会话</h3><button class="soft small" data-action="add-session" ${!instances().length||!groups().length?'disabled':''}>+ 添加群会话</button></div>
 <p class="hint">每个会话只选择上方登记过的实例与群聊；相同实例 + 群号不允许重复。</p>
 <div class="rowcards">${cards||'<div class="empty">暂无群专用会话。默认使用各机器人实例的统一唤醒词。</div>'}</div></div>`;
}
function renderWake(){return blocks('机器人通讯录及唤醒词','配置默认唤醒规则，按需为不同群聊单独设置，并登记其他机器人身份。',
 `<div class="block">${toggle('robot_setup.enabled','启用插件（安装后默认关闭；请先完成基础表和群规则再开启）')}${toggle('robot_setup.wake_enabled','启用全局关键词正则唤醒')}</div>${renderInstances()}${renderSessions()}${scope('robot_setup.wake_groups','关键词唤醒群范围')}`, '1');}
function renderGuard(){
 const cards=sessions().map((item,i)=>`<label class="inlinecheck card"><input type="checkbox" data-bind="robot_setup.group_sessions.${i}.block_bot_replies" ${item.block_bot_replies?'checked':''}><span><strong>${e((instances().find(x=>x.platform_id===item.platform_id)?.instance_label||item.platform_id||'待选实例') + ' · ' + (groups().find(x=>x.group_id===item.group_id)?.group_label||item.group_id||'待选群聊'))}</strong><br><span class="tiny">${e(item.platform_id)} · ${e(item.group_id)} · 已登记 ${(item.bots||[]).length} 个机器人</span></span></label>`).join('');
 const numbers=['recent_count','related_count','recall_search_limit','max_inject_chars','max_saved_per_group'];
 const labels=['最近历史条数','相关历史条数','历史检索候选数','注入上下文字符数','每会话最多保存条数'];
 return blocks('机器人防互聊','从已登记的会话中选择要保护的对象；被拦截的消息可进入只读历史，但绝不触发模型回复。',
 `<div class="block">${toggle('guard_options.bot_guard_enabled','启用全局机器人防互聊')}
 ${toggle('guard_options.inject_enabled','记录被拦截的机器人公开发言，并在真人唤醒时注入只读历史')}</div>
 <div class="block"><h3 class="subtitle">按群会话开启 / 关闭防互聊</h3><div class="rowcards">${cards||'<div class="empty">尚无独立群会话。请在第一部分添加后配置防互聊开关。</div>'}</div></div>
 ${scope('guard_options.gate_groups','禁止机器人互相触发的群范围')}
 <div class="block"><h3 class="subtitle">历史缓存与排错选项</h3><div class="formgrid three">${numbers.map((x,i)=>field('guard_options.'+x,labels[i],'留空=使用默认值','number')).join('')}</div>${toggle('guard_options.verbose_log','输出详细调试日志')}</div>`, '2');
}
function renderSemantic(){
 const current = String(v('semantic_options.semantic_provider_id') || '');
 const options = chatProviders.map(x=>({id:x.id,label:x.label||x.id}));
 // Preserve a selected provider that disappeared after a gateway/model change.
 if(current && !options.some(x=>x.id===current))options.unshift({id:current,label:`⚠ 已保存但当前不可用：${current}`});
 const providerPicker = `<div class="field"><label>语义判断模型（仅对话模型）</label>
 ${select('semantic_options.semantic_provider_id','',options,'跟随当前会话模型（推荐默认）')}
 <div class="provider-toolbar"><button type="button" class="soft small" data-action="refresh-providers">↻ 刷新模型列表</button><span class="tiny">${providerListError?`<span class="error">${e(providerListError)}</span>`:`已发现 ${chatProviders.length} 个已配置对话模型；向量模型不在列表中`}</span></div>
 <p class="hint">默认使用此 QQ 会话已经绑定的对话模型；指定后仅语义判断调用该提供商，不更改日常聊天模型。旧模型失效时请重新选择。</p></div>`;
 return blocks('可选的语义模型辅助判断','仅在真人消息命中正则后判断“是否真的在呼叫当前机器人”，不用于识别 QQ 身份。',
 `<div class="block">${toggle('semantic_options.semantic_enabled','启用语义判断（默认关闭）','关闭后仅依据正则规则唤醒；开启后调用模型判断意图。失败和超时默认不唤醒。')}
 <div class="formgrid">${providerPicker}${field('semantic_options.semantic_timeout_seconds','超时秒数','留空=默认20秒','number')}</div></div>`, '3');}
async function fetchChatProviders(){
 try{
  const response=await bridge.apiGet('models/list');
  if(!response || !Array.isArray(response.providers))throw new Error('服务器返回的模型列表格式无效');
  chatProviders=response.providers.filter(x=>x && typeof x.id==='string' && x.id.trim() && typeof x.label==='string');
  providerListError='';
 }catch(err){
  // Never erase a persisted choice simply because the providers API is down.
  chatProviders=[];
  providerListError='模型列表读取失败，请检查插件日志后刷新。';
 }
}
function render(){if(!cfg)return;root.innerHTML=renderBase()+renderWake()+renderGuard()+renderSemantic();}

async function load(){ notice.className=''; notice.textContent='加载中…';
 try{const obj=await bridge.apiGet('config/get');cfg={robot_setup:{...fallback.robot_setup,...(obj.robot_setup||{})},guard_options:{...fallback.guard_options,...(obj.guard_options||{})},semantic_options:{...fallback.semantic_options,...(obj.semantic_options||{})}};
 for(const p of ['instances','groups','group_sessions'])if(!Array.isArray(cfg.robot_setup[p]))cfg.robot_setup[p]=[];
 await fetchChatProviders();dirty=false;notice.textContent='配置已读取'; render();}
 catch(err){notice.className='error';notice.textContent='读取失败：'+(err?.message||String(err));root.innerHTML='<div class="empty">请在插件详情页重新打开配置中心，或检查插件后端是否成功加载。</div>'}}

function trigger(action,button){const i=Number(button.dataset.i),j=Number(button.dataset.j), s=cfg.robot_setup;
 switch(action){
 case 'refresh-providers':fetchChatProviders().then(()=>{render();notice.textContent=dirty?'模型列表已刷新；仍有未保存修改':'模型列表已刷新';});return;
 case 'add-instance':s.instances.push({__template_key:'instance',instance_label:'新机器人',platform_id:'',bot_name:'',self_qq:'',keyword_enabled:true,wake_mode:'shared',wake_regex:''});break;
 case 'rm-instance':{const row=s.instances[i];const linked=s.group_sessions.filter(x=>x.platform_id===row.platform_id).length;
 if(!window.confirm(`删除实例「${row.instance_label||row.platform_id}」${linked?`及其 ${linked} 条会话规则`:''}？此操作在保存后生效。`))return;
 s.instances.splice(i,1);s.group_sessions=s.group_sessions.filter(x=>x.platform_id!==row.platform_id);break;}
 case 'add-group':s.groups.push({__template_key:'group',group_label:'新群聊',group_id:''});break;
 case 'rm-group':{const row=s.groups[i];const linked=s.group_sessions.filter(x=>x.group_id===row.group_id).length;
 const expands=(s.wake_groups.length===1&&s.wake_groups.includes(row.group_id))||(cfg.guard_options.gate_groups.length===1&&cfg.guard_options.gate_groups.includes(row.group_id));
 const warning=expands?'\n⚠ 删除后某个群范围将清空，代表开启到所有群！请保存后立即核对两个范围。':'';
 if(!window.confirm(`删除群「${row.group_label||row.group_id}」${linked?`及其 ${linked} 条会话规则`:''}？${warning}`))return;
 s.groups.splice(i,1);s.group_sessions=s.group_sessions.filter(x=>x.group_id!==row.group_id);s.wake_groups=s.wake_groups.filter(x=>x!==row.group_id);cfg.guard_options.gate_groups=cfg.guard_options.gate_groups.filter(x=>x!==row.group_id);break;}
 case 'add-session':s.group_sessions.push({__template_key:'group',platform_id:s.instances[0]?.platform_id||'',group_id:s.groups[0]?.group_id||'',keyword_enabled:true,use_custom_wake_regex:false,wake_regex:'',bots:[],block_bot_replies:true});break;
 case 'rm-session':s.group_sessions.splice(i,1);break;
 case 'add-bot':s.group_sessions[i].bots.push('||');break;
 case 'rm-bot':s.group_sessions[i].bots.splice(j,1);break;
 default:return;
 }dirty=true;notice.textContent='有尚未保存的修改';render();}
root.addEventListener('click',ev=>{const button=ev.target.closest('button[data-action]');if(button)trigger(button.dataset.action,button);});
root.addEventListener('change',ev=>{const t=ev.target;
 if(t.dataset.bot!==undefined){const i=Number(t.dataset.bot),j=Number(t.dataset.idx),n=Number(t.dataset.part);const arr=String(sessions()[i].bots[j]).split('|');while(arr.length<3)arr.push('');arr[n]=t.value.trim().replace(/\|/g,'');sessions()[i].bots[j]=arr.join('|');dirty=true;notice.textContent='有尚未保存的修改';render();return;}
 if(t.dataset.scope){let a=v(t.dataset.scope)||[];let next=t.checked?[...a.filter(x=>x!==t.dataset.id),t.dataset.id]:a.filter(x=>x!==t.dataset.id);
   if(a.length&&next.length===0&&!window.confirm('⚠ 当前范围将从指定群改为所有群（包含未登记群），确定吗？')){t.checked=true;return;}
   set(t.dataset.scope,next);return;}
 if(t.dataset.bind){
   const path=t.dataset.bind, old=v(path);
   // Blank numeric fields use backend defaults. Never coerce '' to 0.
   let val=t.type==='checkbox'?t.checked:t.type==='number'?(t.value.trim()===''?'':Number(t.value)):t.value;
   const instMatch=path.match(/^robot_setup\.instances\.(\d+)\.platform_id$/);
   const groupMatch=path.match(/^robot_setup\.groups\.(\d+)\.group_id$/);
   if(instMatch&&old&&old!==val){
     const count=sessions().filter(x=>x.platform_id===old).length;
     if(count&&!window.confirm(`修改实例ID会将关联的 ${count} 条会话规则转移到新实例ID，确定吗？`)){t.value=old;return;}
     sessions().forEach(x=>{if(x.platform_id===old)x.platform_id=val});
   }
   if(groupMatch&&old&&old!==val){
     const count=sessions().filter(x=>x.group_id===old).length;
     if(count&&!window.confirm(`修改群号会将关联的 ${count} 条会话规则（包括通讯录）转移到新群号，确定吗？`)){t.value=old;return;}
     sessions().forEach(x=>{if(x.group_id===old)x.group_id=val});
     for(const k of ['wake_groups'])cfg.robot_setup[k]=cfg.robot_setup[k].map(x=>x===old?val:x);
     cfg.guard_options.gate_groups=cfg.guard_options.gate_groups.map(x=>x===old?val:x);
   }
   set(path,val);
   if(instMatch||groupMatch||path.endsWith('wake_mode')||path.endsWith('use_custom_wake_regex'))render();
 }
});

document.getElementById('save').addEventListener('click',async()=>{
 const btn=document.getElementById('save');btn.disabled=true;notice.className='';notice.textContent='正在保存…';
 try{const answer=await bridge.apiPost('config/save',cfg);if(!answer?.saved)throw new Error('服务器未确认保存');dirty=false;notice.className='ok';notice.textContent='保存成功，配置已生效';await load();}
 catch(err){notice.className='error';notice.textContent='保存失败：'+(err?.message||String(err));}
 finally{btn.disabled=false}
});
document.getElementById('reload').addEventListener('click',()=>{if(!dirty||window.confirm('存在未保存的修改，确定放弃这些修改并重新读取吗？'))load()});
window.addEventListener('beforeunload',ev=>{if(dirty){ev.preventDefault();ev.returnValue='';}});
try{await bridge.ready();await load();}catch(err){notice.className='error';notice.textContent=String(err)}
