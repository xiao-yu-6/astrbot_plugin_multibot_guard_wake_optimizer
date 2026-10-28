const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert/strict');
const nodes={};for(const id of ['render','notice','save','reload'])nodes[id]={innerHTML:'',textContent:'',className:'',listeners:{},addEventListener(k,f){this.listeners[k]=f;}};
let confirmations=0;
let stored={robot_setup:{enabled:true,wake_enabled:true,wake_groups:['234567890'],instances:[
 {platform_id:'bot-a',instance_label:'机器人A',bot_name:'机器人A',self_qq:'1000000001',keyword_enabled:true,wake_mode:'per_group',wake_regex:'小A'},
 {platform_id:'bot-b',instance_label:'机器人B',bot_name:'机器人B',self_qq:'1000000002',keyword_enabled:true,wake_mode:'shared',wake_regex:'小B'},
],groups:[{group_id:'123456789',group_label:'示例群A'},{group_id:'234567890',group_label:'示例群B'}],group_sessions:[
 {platform_id:'bot-a',group_id:'123456789',keyword_enabled:true,use_custom_wake_regex:false,wake_regex:'',block_bot_replies:true,bots:['1000000002|机器人B|小B']}
]},guard_options:{gate_groups:['234567890']},semantic_options:{semantic_enabled:false}};
const bridge={ready:async()=>{},apiGet:async k=>k==='models/list'?{providers:[]}:structuredClone(stored),apiPost:async(k,data)=>{
 assert.equal(k,'config/save');stored=structuredClone(data);return {saved:true};}};
const window={AstrBotPluginView:bridge,addEventListener(){},confirm(){confirmations++;return true;},alert(msg){throw Error(msg);}};
const source=fs.readFileSync(path.join(__dirname,'../views/settings/app.js'),'utf8');
function click(action,i=0,j=0){const button={dataset:{action,i:String(i),j:String(j)}};nodes.render.listeners.click({target:{closest:()=>button}});}
function change(bind,value,type='text'){nodes.render.listeners.change({target:{dataset:{bind},value:String(value),type,checked:value}});}
async function save(){await nodes.save.listeners.click();assert(!nodes.notice.textContent.includes('失败'));}
(async()=>{
 await vm.runInNewContext('(async()=>{'+source+'\n})()',{window,document:{getElementById:id=>nodes[id]},console});
 assert(nodes.render.innerHTML.indexOf('机器人防互聊与通讯录')<nodes.render.innerHTML.indexOf('唤醒词及接话设置'));
 assert(nodes.render.innerHTML.includes('data-action="rm-session"'));
 click('add-instance');click('rm-instance',2);click('add-group');click('rm-group',2);await save();
 assert.equal(stored.robot_setup.instances.length,2);assert.equal(stored.robot_setup.groups.length,2);
 click('add-wake-session',0);await save();
 assert.equal(stored.robot_setup.group_sessions.length,2);
 assert.equal(stored.robot_setup.group_sessions[1].use_custom_wake_regex,false);
 change('robot_setup.group_sessions.1.use_custom_wake_regex',true,'checkbox');await save();
 assert.equal(stored.robot_setup.group_sessions[1].wake_regex,'小A');
 nodes.render.listeners.change({target:{dataset:{wakeRegex:'1'},value:'群专用'}});await save();
 change('robot_setup.group_sessions.1.use_custom_wake_regex',false,'checkbox');
 change('robot_setup.group_sessions.1.use_custom_wake_regex',true,'checkbox');await save();
 assert.equal(stored.robot_setup.group_sessions[1].wake_regex,'群专用');
 assert(nodes.render.innerHTML.includes('value="群专用"'));
 click('add-bot',1);click('rm-bot',1,0);await save();
 assert.deepEqual(stored.robot_setup.group_sessions[1].bots,[]);
 click('rm-session',1);await save();
 assert.equal(stored.robot_setup.group_sessions.length,1);
 assert.equal(stored.robot_setup.groups.length,2);assert.equal(stored.robot_setup.instances.length,2);
 click('add-wake-session',0);await save();
 const count=confirmations;click('rm-group',1);await save();
 assert.equal(confirmations-count,2,'Deleting the last scoped group must be confirmed twice');
 assert.equal(stored.robot_setup.group_sessions.length,1);
 assert.equal(stored.robot_setup.groups.length,1);
 assert.deepEqual(stored.robot_setup.wake_groups,[]);assert.deepEqual(stored.guard_options.gate_groups,[]);
 click('rm-instance',0);await save();
 assert.equal(stored.robot_setup.instances.length,1);assert.equal(stored.robot_setup.instances[0].platform_id,'bot-b');
 assert.equal(stored.robot_setup.group_sessions.length,0);assert.equal(stored.robot_setup.groups.length,1);
 await nodes.reload.listeners.click();
 assert(!nodes.render.innerHTML.includes('data-action="rm-session"'));
 console.log('FRONTEND PASS: draft add/delete; session add/delete; roster deletion; cascade removal; two confirmations; saved override retained; save/reload');
})().catch(e=>{console.error(e);process.exitCode=1;});
