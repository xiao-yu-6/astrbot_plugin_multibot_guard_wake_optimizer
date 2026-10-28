const bridge = window.AstrBotPluginView;
const root = document.getElementById('render');
const notice = document.getElementById('notice');
let cfg;
let dirty = false;
let chatProviders = [];
let providerListError = '';
let rememberedSemanticMode = 'regex_then_semantic';
const flowDefaults = {enabled:false,context_count:6,context_max_chars:4000,empty_action:'original',followup_enabled:false,wait_seconds:60};
const fallback = { robot_setup:{enabled:false,wake_enabled:true,wake_groups:[],instances:[],groups:[],group_sessions:[]},guard_options:{bot_guard_enabled:true,gate_groups:[],inject_enabled:true,recent_count:6,related_count:8,recall_search_limit:5000,max_inject_chars:2400,max_saved_per_group:10000,verbose_log:false},semantic_options:{semantic_enabled:false,semantic_mode:'regex_only',judge_persona:'',semantic_provider_id:'',semantic_timeout_seconds:20,semantic_context_count:4,patrol_interval_seconds:15,patrol_cooldown_seconds:45,patrol_min_messages:1} };

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
 `<div class="block">${toggle('robot_setup.enabled','启用插件（安装后默认关闭，请完成配置后开启）')}</div><div class="block"><div class="subhead"><h3>本地机器人实例</h3><button class="soft small" data-action="add-instance">+ 添加实例</button></div><div class="tablewrap"><table class="data-table"><thead><tr><th>显示名称</th><th>平台实例ID</th><th>本机机器人QQ号</th><th>机器人名称</th><th></th></tr></thead><tbody>${items||'<tr><td colspan="5" class="muted">暂无实例</td></tr>'}</tbody></table></div><p class="hint">平台实例 ID 必须与 AstrBot 平台列表一致；QQ 号建议填写，便于自动识别本机其他机器人。</p></div>
 <div class="block"><div class="subhead"><h3>QQ群聊 ID</h3><button class="soft small" data-action="add-group">+ 添加群聊</button></div><div class="tablewrap"><table class="data-table"><thead><tr><th>群聊备注</th><th>QQ群号</th><th></th></tr></thead><tbody>${gr||'<tr><td colspan="3" class="muted">暂无群聊</td></tr>'}</tbody></table></div></div>`, '0');
}
function renderInstances(){
 const cards=instances().map((inst,i)=>{
 const base=`robot_setup.instances.${i}`;
 return `<article class="card"><h4>${e(inst.instance_label||inst.platform_id||'新机器人')}</h4><span class="pill">${e(inst.platform_id||'待登记实例ID')}</span>
 <div class="formgrid" style="margin-top:13px">${field(base+'.wake_regex','通用唤醒正则','例如 (机器人A|小A)','text','此实例所有群默认使用这一条正则；是否允许特定群单独覆盖，在下方设置。')}</div>
 ${toggle(base+'.keyword_enabled','允许此实例通过插件唤醒')}
 <p class="hint">使用 regex.search()，句中包含即可匹配，无需添加 .*。正则留空时不通过关键词唤醒；原生 @ 和指令不受影响。</p>${renderFlow(i)}</article>`;
 }).join('');
 return `<div class="block"><h3 class="subtitle">各机器人实例的通用唤醒正则</h3><p class="hint">先填写通用正则；未设置群专用覆盖时，所有群自动继承最新通用正则。</p><div class="rowcards">${cards||'<div class="empty">先在顶部基础参数表中添加机器人实例。</div>'}</div></div>`;
}
function renderFlow(i){
 const base=`robot_setup.instances.${i}.wake_flow`;
 return `<div class="block"><h3 class="subtitle">@ / 关键词唤醒：上下文与接话</h3>
 ${toggle(base+'.enabled','启用此实例的自定义唤醒接话','默认关闭，保留原有行为。启用后只在上方「关键词唤醒群范围」内生效，@ 同样遵守此范围。')}
 <div class="formgrid">
 ${field(base+'.context_count','附带最近群聊消息条数（0～50）','0=不额外附带','number','真人群友消息及本实例已发送的文字回复；不改已有长期记忆和会话历史。')}
 ${field(base+'.context_max_chars','额外上下文字符上限（512～12000）','默认4000','number')}
 ${select(base+'.empty_action','只 @ 或只发唤醒词时',[{id:'original',label:'保留原设置（不接管空唤醒）'},{id:'respond',label:'立即接话（走正常对话和上下文流程）'},{id:'wait',label:'不立即回复，等待同一人补充消息'}],'请选择处理方式')}
 ${field(base+'.wait_seconds','自定义等待秒数（1～300）','默认60','number','适用于「等待补充」及下方「回复后接下一条」。保留原设置时，原生空唤醒仍使用框架原有等待规则。')}
 </div>
 ${toggle(base+'.followup_enabled','唤醒消息回复后，允许同一人再接一条消息','按实例＋群号＋发言者隔离；从实际回复发送后开始计时，只接一条，不持续续期。指令、@其他机器人和仅叫其他机器人的消息不被接走。')}
 <p class="hint">上下文仅在内存缓存，最多保留30分钟；启用后开始收集，重载或保存设置会清空缓存和等待窗口。此处的条数只控制额外群聊片段，不限制 AstrBot 原有会话历史、记忆插件或群聊上下文设置。新功能不会关闭语义二次判断；它仍可能拒绝关键词唤醒。</p>
 </div>`;
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
 return `<article class="card"><div class="subhead"><h4>${e((instances().find(x=>x.platform_id===item.platform_id)?.instance_label||item.platform_id||'待选实例') + ' · ' + (groups().find(x=>x.group_id===item.group_id)?.group_label||item.group_id||'待选群聊'))}</h4><button class="small danger" data-action="rm-session" data-i="${i}">删除会话</button></div>
 <div class="formgrid">${select(base+'.platform_id','选择机器人实例',instanceOptions())}${select(base+'.group_id','选择QQ群聊',groupOptions())}</div>
 ${toggle(base+'.block_bot_replies','本会话阻止已识别机器人触发回复')}
 ${renderBots(item,i)}</article>`;
 }).join('');
 return `<div class="block"><div class="subhead"><h3>按实例和群聊管理机器人通讯录</h3><button class="soft small" data-action="add-session" ${!instances().length||!groups().length?'disabled':''}>+ 添加群会话</button></div>
 <p class="hint">先在顶部基础参数表登记实例和QQ群；在这里选择已登记的对象。每个实例＋群号只能有一条通讯录配置。别名可留空，身份只按QQ号识别。</p>
 <div class="rowcards guard-session-cards">${cards||'<div class="empty">尚未添加群会话。请先创建会话，再登记机器人通讯录和设置防互聊。</div>'}</div></div>`;
}
function renderGroupWakeOverrides(){
 const policyOptions=[{id:'shared',label:'所有群使用通用唤醒正则'},{id:'per_group',label:'允许群聊单独覆盖'}];
 const instanceCards=instances().map((inst,i)=>{
  const mode=inst.wake_mode==='per_group'?'per_group':'shared';
  const base=`robot_setup.instances.${i}`;
  const ownSessions=sessions().map((item,j)=>({item,j})).filter(x=>x.item.platform_id===inst.platform_id);
  const available=groups().some(g=>g.group_id&&!sessions().some(x=>x.platform_id===inst.platform_id&&x.group_id===g.group_id));
  const cards=ownSessions.map(({item,j})=>{
   const path=`robot_setup.group_sessions.${j}`;
   const custom=item.use_custom_wake_regex===true;
   const effective=custom?(item.wake_regex||''):(inst.wake_regex||'');
   return `<div class="wake-group-card"><div class="wake-row-heading"><strong>${e(groups().find(x=>x.group_id===item.group_id)?.group_label||item.group_id||'当前群聊')}</strong><button type="button" class="danger small" data-action="rm-session" data-i="${j}">删除会话</button></div>
   <div class="formgrid">
   ${select(path+'.group_id','选择群聊',groupOptions())}
   <div class="field"><label>当前唤醒正则（${custom?'本群专用':'继承通用'}）</label><input type="text" data-wake-regex="${j}" value="${e(effective)}" placeholder="通用正则为空，暂不启用关键词唤醒" ${custom?'':'readonly'}><span class="tiny">${custom?'修改后仅对本群生效。':'自动跟随上方通用正则；开启下方开关后可独立修改。'}</span></div>
   </div>
   ${toggle(path+'.use_custom_wake_regex','本群使用专用唤醒正则（关闭=自动继承通用正则）')}
   ${toggle(path+'.keyword_enabled','本会话允许插件唤醒（正则或语义）')}
   </div>`;
  }).join('');
  return `<article class="card wake-instance-card"><h4>${e(inst.instance_label||inst.platform_id||'新机器人')}</h4><span class="pill">${e(inst.platform_id||'待登记实例ID')}</span>
   ${select(base+'.wake_mode','群聊唤醒词覆盖规则',policyOptions,'请选择覆盖规则')}
   ${mode==='shared'?`<p class="hint">所有群统一使用上方正则：<code>${e(inst.wake_regex||'（未设置）')}</code>。已保存的群专用规则暂不生效，不会被删除。</p>`:
   `<p class="hint">允许按群单独覆盖。新建会话<strong>默认继承</strong>通用正则；只有开启「本群使用专用唤醒正则」后才能独立编辑。</p>
   <div class="subhead wake-add"><h3>本实例的群聊唤醒设置</h3><button class="soft small" data-action="add-wake-session" data-i="${i}" ${available?'':'disabled'}>+ 添加群聊唤醒设置</button></div>
   <div class="wake-group-list">${cards||'<p class="empty">还没有群聊会话。点击「添加群聊唤醒设置」选择已有QQ群。</p>'}</div>
   ${!available&&groups().length?'<p class="tiny">已登记的群聊全部建立了会话；可以直接修改上方对应群的正则。</p>':''}`}
  </article>`;
 }).join('');
 return `<div class="block"><h3 class="subtitle">群聊唤醒词覆盖规则</h3>
 <p class="hint">各实例独立选择覆盖策略。选「所有群使用通用唤醒正则」时统一继承；选「允许群聊单独覆盖」后，可在这里添加或编辑会话。会话同时显示在第1项，便于登记本群机器人通讯录。</p>
 <div class="rowcards wake-instance-cards">${instanceCards||'<div class="empty">请先在基础参数表登记机器人实例。</div>'}</div></div>`;
}
function renderHistoryOptions(){
 const numbers=['recent_count','related_count','recall_search_limit','max_inject_chars','max_saved_per_group'];
 const labels=['最近机器人历史条数','相关机器人历史条数','历史检索候选数','注入上下文字符数','每会话最多保存条数'];
 return `<div class="block"><h3 class="subtitle">关键词唤醒：历史缓存与排错选项</h3>
 <p class="hint">与上方「@ / 关键词唤醒：上下文与接话」配合使用。以下历史是已识别机器人的只读公开发言；上方实例接话参数管理普通真人群聊上下文，两者是不同来源。</p>
 ${toggle('guard_options.inject_enabled','保存已识别机器人的公开发言，并在真人唤醒时注入相关只读历史')}
 <div class="formgrid three">${numbers.map((x,i)=>field('guard_options.'+x,labels[i],'留空=使用默认值','number')).join('')}</div>
 ${toggle('guard_options.verbose_log','输出详细调试日志','启用后将增加排错日志，正式使用时建议关闭以减少消息内容暴露。')}</div>`;
}
function renderGuard(){
 return blocks('机器人防互聊与通讯录','先识别群内其他机器人，再配置拦截；机器人身份只按 QQ 号判定，不按昵称误拦截。',
 `<div class="block">${toggle('guard_options.bot_guard_enabled','启用全局机器人防互聊')}</div>
 ${renderSessions()}
 ${scope('guard_options.gate_groups','禁止机器人互相触发的群范围')}`, '1');
}
function renderWake(){return blocks('唤醒词及接话设置','先填每个实例的通用正则，再到群聊覆盖规则中选择是否允许按群独立修改。原生 @、指令不受正则设置影响。',
 `<div class="block">${toggle('robot_setup.wake_enabled','启用插件唤醒（正则或语义）')}</div>${renderInstances()}${renderGroupWakeOverrides()}${scope('robot_setup.wake_groups','允许插件唤醒的群范围')}${renderHistoryOptions()}`, '2');}

function renderSemantic(){
 const current = String(v('semantic_options.semantic_provider_id') || '');
 const options = chatProviders.map(x=>({id:x.id,label:x.label||x.id}));
 if(current && !options.some(x=>x.id===current))options.unshift({id:current,label:`⚠ 已保存但当前不可用：${current}`});
 const mode = v('semantic_options.semantic_mode') || 'regex_only';
 const enabled = mode !== 'regex_only';
 const modes = [{id:'regex_then_semantic',label:'正则 + 语义复核：仅在正则命中后分析是否指向自己'},
                {id:'semantic_only',label:'独立语义巡检：汇总近期真人消息后决定是否参与'}];
 const persona = v('semantic_options.judge_persona') || '';
 const providerPicker = `<div class="field"><label>语义判断模型（仅对话模型）</label>
 ${select('semantic_options.semantic_provider_id','',options,'跟随当前会话模型（推荐默认）')}
 <div class="provider-toolbar"><button type="button" class="soft small" data-action="refresh-providers">↻ 刷新模型列表</button><span class="tiny">${providerListError?`<span class="error">${e(providerListError)}</span>`:`已发现 ${chatProviders.length} 个对话模型；不包含向量模型`}</span></div>
 <p class="hint">不影响日常回复所用的主模型；不指定则使用当前会话模型。</p></div>`;
 const personaCards=instances().map((inst,i)=>{const base=`robot_setup.instances.${i}`;return `<article class="card"><h4>${e(inst.instance_label||inst.platform_id||'机器人实例')}</h4><div class="formgrid">
 ${field(base+'.semantic_aliases','语义识别别名（可选）','例如 小A,阿A','text','辅助模型用于识别称呼，不参与QQ号身份拦截。')}
 <div class="field"><label>该实例的参与判断人格 / 专长</label><textarea data-bind="${e(base+'.semantic_persona')}" rows="3" placeholder="例：克制发言的技术助理，擅长代码调试">${e(v(base+'.semantic_persona')||'')}</textarea><span class="tiny">仅辅助模型判断是否参与，不修改主聊天人格。</span></div>
 </div></article>`}).join('');
 return blocks('可选：语义模型辅助判断','关闭时仅使用普通正则唤醒；开启后从两种语义方式中选择。防互聊始终独立生效。',
 `<div class="block"><label class="inlinecheck"><input type="checkbox" data-semantic-enable="1" ${enabled?'checked':''}><strong>启用语义辅助判断（默认关闭）</strong></label>
 <p class="hint">关闭=仅正则唤醒，不调用辅助模型；开启后才能选择下方的两个语义模式。</p></div>
 ${enabled?`<div class="block"><div class="field"><label>语义辅助方式</label><select data-semantic-mode="1">${modes.map(x=>`<option value="${e(x.id)}" ${mode===x.id?'selected':''}>${e(x.label)}</option>`).join('')}</select></div>
 <p class="hint">正则复核仅判断是否有人在叫当前机器人；独立巡检按群固定时间窗口合并真人消息，到期只分析一次，随后进入冷却。已登记机器人仍在所有语义分析之前被拦截。</p>
 <div class="field"><label>辅助分析员通用人格 / 参与风格（可选）</label><textarea data-bind="semantic_options.judge_persona" rows="4" placeholder="留空：使用内置克制型分析员">${e(persona)}</textarea><span class="tiny">每个机器人的特殊身份与专长可以在下方分别设置。</span></div>
 <div class="formgrid">${providerPicker}${field('semantic_options.semantic_timeout_seconds','超时秒数','默认20秒','number')}${field('semantic_options.semantic_context_count','参考近期群聊条数（0～8）','默认4','number','各实例与群聊单独隔离。')}</div>
 ${mode==='semantic_only'?`<div class="formgrid three">${field('semantic_options.patrol_interval_seconds','巡检窗口（秒）','默认15；2～120','number','首次真人消息开启固定窗口，后续消息不重置计时。')}${field('semantic_options.patrol_cooldown_seconds','巡检冷却（秒）','默认45；0～3600','number','每次巡检完成后短暂休息。')}${field('semantic_options.patrol_min_messages','至少多少条真人消息','默认1；1～20','number')}</div>`:''}
 <div class="block"><h3 class="subtitle">按机器人实例设置辅助分析身份</h3><div class="rowcards">${personaCards||'<p class="empty">请先在基础参数表登记机器人实例。</p>'}</div></div>
 </div>`:''}`, '3');
}

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
function render(){if(!cfg)return;for(const inst of instances())inst.wake_flow={...flowDefaults,...(inst.wake_flow||{})};root.innerHTML=renderBase()+renderGuard()+renderWake()+renderSemantic();}

async function load(){ notice.className=''; notice.textContent='加载中…';
 try{const obj=await bridge.apiGet('config/get');cfg={robot_setup:{...fallback.robot_setup,...(obj.robot_setup||{})},guard_options:{...fallback.guard_options,...(obj.guard_options||{})},semantic_options:{...fallback.semantic_options,...(obj.semantic_options||{})}};
 for(const p of ['instances','groups','group_sessions'])if(!Array.isArray(cfg.robot_setup[p]))cfg.robot_setup[p]=[];
 if(!Object.prototype.hasOwnProperty.call(obj.semantic_options||{}, 'semantic_mode')){
   cfg.semantic_options.semantic_mode = obj.semantic_options?.semantic_enabled === true ? 'regex_then_semantic' : 'regex_only';
 }
 if(cfg.semantic_options.semantic_mode==='semantic_only'||cfg.semantic_options.semantic_mode==='regex_then_semantic')rememberedSemanticMode=cfg.semantic_options.semantic_mode;
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
   if(expands&&!window.confirm('再次确认：某个群范围将变为空列表＝所有群（包括未登记群）。仍要继续删除吗？'))return;
 s.groups.splice(i,1);s.group_sessions=s.group_sessions.filter(x=>x.group_id!==row.group_id);s.wake_groups=s.wake_groups.filter(x=>x!==row.group_id);cfg.guard_options.gate_groups=cfg.guard_options.gate_groups.filter(x=>x!==row.group_id);break;}
 case 'add-session':{
   const inst=s.instances.find(x=>s.groups.some(g=>g.group_id&&!s.group_sessions.some(row=>row.platform_id===x.platform_id&&row.group_id===g.group_id)));
   const group=s.groups.find(g=>g.group_id&&!s.group_sessions.some(row=>row.platform_id===inst?.platform_id&&row.group_id===g.group_id));
   if(!inst||!group){notice.textContent='没有可新增的会话：所有已登记的实例与群聊都已配置';return;}
   s.group_sessions.push({__template_key:'group',platform_id:inst.platform_id,group_id:group.group_id,keyword_enabled:true,use_custom_wake_regex:false,wake_regex:'',bots:[],block_bot_replies:true});break;
 }
 case 'add-wake-session':{
   const inst=s.instances[i];if(!inst)return;
   const group=s.groups.find(g=>g.group_id&&!s.group_sessions.some(x=>x.platform_id===inst.platform_id&&x.group_id===g.group_id));
   if(!group){notice.textContent='当前实例没有尚未创建会话的已登记QQ群';return;}
   s.group_sessions.push({__template_key:'group',platform_id:inst.platform_id,group_id:group.group_id,keyword_enabled:true,use_custom_wake_regex:false,wake_regex:'',bots:[],block_bot_replies:true});
   break;
 }
 case 'rm-session':{
   const row=s.group_sessions[i];if(!row)return;
   const botCount=Array.isArray(row.bots)?row.bots.filter(x=>String(x).split('|').some(part=>part.trim())).length:0;
   const related=botCount?`，并同时删除该会话的 ${botCount} 条机器人通讯录记录`:'';
   if(!window.confirm(`确定删除「${row.platform_id} · ${row.group_id}」会话${related}？\n此操作会同时删除第1项的通讯录和第2项的群聊唤醒覆盖规则，保存后生效。`))return;
   s.group_sessions.splice(i,1);break;
 }
 case 'add-bot':{const row=s.group_sessions[i];if(!row)return;row.bots??=[];row.bots.push('||');break;}
 case 'rm-bot':{const row=s.group_sessions[i];if(!row||!Array.isArray(row.bots)||j<0||j>=row.bots.length)return;row.bots.splice(j,1);break;}
 default:return;
 }dirty=true;notice.textContent='有尚未保存的修改';render();}
root.addEventListener('click',ev=>{const button=ev.target.closest('button[data-action]');if(button)trigger(button.dataset.action,button);});
root.addEventListener('change',ev=>{const t=ev.target;
 if(t.dataset.semanticEnable!==undefined){set('semantic_options.semantic_mode',t.checked?rememberedSemanticMode:'regex_only');render();return;}
 if(t.dataset.semanticMode!==undefined){rememberedSemanticMode=t.value;set('semantic_options.semantic_mode',t.value);render();return;}
 if(t.dataset.wakeRegex!==undefined){
   const j=Number(t.dataset.wakeRegex),session=sessions()[j];
   if(!session||!session.use_custom_wake_regex)return;
   set(`robot_setup.group_sessions.${j}.wake_regex`,t.value);return;
 }
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
   const sessionGroupMatch=path.match(/^robot_setup\.group_sessions\.(\d+)\.group_id$/);
   if(sessionGroupMatch && old!==val){
     const index=Number(sessionGroupMatch[1]);const current=sessions()[index];
     if(sessions().some((row,j)=>j!==index&&row.platform_id===current.platform_id&&row.group_id===val)){
       window.alert('该机器人实例已经有此群的会话，请修改现有会话，不能重复添加。');t.value=old;return;
     }
     if(current.bots?.length && !window.confirm('切换群聊将把此会话已有的机器人通讯录转移到新群，确定吗？')){
       t.value=old;return;
     }
   }
   set(path,val);
   if(path.endsWith('use_custom_wake_regex') && val===true){
     const index=Number(path.match(/group_sessions\.(\d+)\./)?.[1]);
     const row=sessions()[index];
     const owner=instances().find(x=>x.platform_id===row?.platform_id);
     if(row && !String(row.wake_regex||'').trim()){row.wake_regex=owner?.wake_regex||'';}
   }
   if(instMatch||groupMatch||path.endsWith('wake_mode')||path.endsWith('use_custom_wake_regex')||path.endsWith('wake_regex')||sessionGroupMatch)render();
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
