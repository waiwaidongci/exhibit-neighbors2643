import {research} from '../stores/research.js';import {session} from '../stores/session.js';import {archiveApi} from '../api/research.js';import {metrics} from '../components/common/business.js';import {status} from '../components/common/status.js';import {table} from '../components/common/table.js';import {esc,localTime} from '../utils/format.js';import {bind,toast} from '../hooks/actions.js';import {fileStates,itemStates} from '../constants/enums.js';
const RESUMABLE=['copying','copied','switching','switched','reclaiming','blocked'];
const TABS=[['all','全部'],['pending','待迁移'],['copied','迁移中'],['verified','已完成'],['quarantined','已隔离']];
const KIND={run:'任务结果',note:'批准快照'};
function migrationCard(m,selected,isAdmin){
  const pct=m.total?Math.round(m.verified/m.total*100):100;
  return '<article class="note-record'+(m.id===selected?' selected':'')+'"><header><span><strong>第 '+m.generation+' 代</strong> <small>#'+m.id+' · '+esc(m.created_by)+'</small></span>'+status(m.state)+'</header>'
  +'<div class="progress" title="已核验 '+m.verified+'/'+m.total+'"><i style="--w:'+pct+'%"></i></div>'
  +'<p class="fine">已核验 '+m.verified+' / '+m.total+' 份'+(m.quarantined?' · 隔离 '+m.quarantined+' 份':'')+' · 目标 '+esc(m.target_dir)+'</p>'
  +(m.blocked_reason?'<p class="blocked-reason">阻断原因：'+esc(m.blocked_reason)+'</p>':'')
  +'<footer><small>'+esc(localTime(m.created_at))+'</small><span>'
  +'<button class="secondary" data-mig="'+m.id+'">查看文件</button>'
  +(isAdmin&&RESUMABLE.includes(m.state)?'<button data-advance="'+m.id+'">继续迁移 →</button>':'')
  +'</span></footer></article>';
}
export async function archivePage(){
  const data=await archiveApi.overview();research.archive=data;
  research.archiveActive=data.migrations.some(m=>['copying','copied','switching','switched','reclaiming'].includes(m.state));
  const isAdmin=session.user&&session.user.role==='admin';
  const ready=data.items.filter(i=>i.state==='ready'),quarantined=data.items.filter(i=>i.state==='quarantined');
  const latest=data.migrations[0];
  if(!research.archiveMigrationId||!data.migrations.some(m=>m.id===research.archiveMigrationId))research.archiveMigrationId=latest?latest.id:null;
  research.archiveTab=research.archiveTab||'all';
  const mig=data.migrations.find(m=>m.id===research.archiveMigrationId);
  const itemsById=Object.fromEntries(data.items.map(i=>[i.id,i]));
  const files=mig?data.files.filter(f=>f.migration_id===mig.id):[];
  const shown=files.filter(f=>research.archiveTab==='all'||f.state===research.archiveTab).map(f=>({filename:f.filename,kind:KIND[itemsById[f.item_id]?.kind]||'—',state:fileStates[f.state]||f.state,sha256:f.sha256.slice(0,16)+'…',error:f.error||'—'}));
  const ledger=data.items.map(i=>({filename:i.filename,kind:KIND[i.kind]||i.kind,state:itemStates[i.state]||i.state,generation:'gen-'+i.generation,sha256:i.sha256.slice(0,16)+'…',bytes:i.bytes,repairs:i.repairs,blocked_reason:i.blocked_reason||'—'}));
  return '<section class="page-heading"><p class="eyebrow">07 / ARCHIVE MIGRATION</p><h1>留档不停服迁往新目录，逐份可核验。</h1><p>历史件按冻结结果生成并逐份核对内容指纹，损坏件隔离，绝不用当前评分重算冒充原件；下载绑定开始时的完整版本，索引切换带代次围栏，旧件等在途下载结束才回收。</p></section>'
  +metrics([{label:'当前生效代次',value:'gen-'+data.pointer.generation},{label:'在途下载',value:data.open_leases},{label:'就绪留档件',value:ready.length},{label:'已隔离',value:quarantined.length}])
  +'<div class="split"><section><div class="run-title"><h2>迁移代次</h2>'+(isAdmin?'<button id="migrate">发起新一代迁移 →</button>':'')+'</div>'
  +(isAdmin?'':'<p class="fine">迁移由负责人发起；分析、阅读角色可查看进度与阻断原因。</p>')
  +(data.migrations.length?data.migrations.map(m=>migrationCard(m,research.archiveMigrationId,isAdmin)).join(''):'<div class="empty"><strong>还没有迁移。</strong><p>当前留档位于 '+esc(data.pointer.active_dir)+'，发起迁移后历史件将逐份复制、核验并切换索引。</p></div>')
  +'</section><aside class="method-sheet"><p class="eyebrow">GUARANTEES</p><h2>迁移保障</h2><ol><li>字节只来自冻结结果，逐份 SHA256 核验</li><li>损坏件移入隔离区，按冻结结果修复留痕</li><li>迁移中新任务照常完成并登记入当前目录</li><li>下载租约绑定开始时版本，切换后新请求走新目录</li><li>复制、切换、回收分段提交，中断后可继续</li><li>只有最新一代可生效，迟归旧执行者不能回切</li><li>旧件等在途下载结束才回收，共用文件不误删</li></ol><p class="fine">当前目录<br><code>'+esc(data.pointer.active_dir)+'</code></p></aside></div>'
  +(mig?'<h2>文件明细 <small>第 '+mig.generation+' 代 · 共 '+files.length+' 份</small></h2><div class="tabs">'+TABS.map(([k,label])=>'<button class="secondary'+(research.archiveTab===k?' on':'')+'" data-tab="'+k+'">'+label+(k==='all'?' '+files.length:' '+files.filter(f=>f.state===k).length)+'</button>').join('')+'</div>'
  +table(shown,[{key:'filename',label:'文件'},{key:'kind',label:'类型'},{key:'state',label:'状态'},{key:'sha256',label:'内容指纹'},{key:'error',label:'阻断原因'}],{limit:30})
  :'')
  +'<h2>留档总账 <small>全部登记件，含待迁移与隔离原因</small></h2>'
  +table(ledger,[{key:'filename',label:'文件'},{key:'kind',label:'类型'},{key:'state',label:'状态'},{key:'generation',label:'所在代次'},{key:'sha256',label:'内容指纹'},{key:'bytes',label:'字节'},{key:'repairs',label:'修复'},{key:'blocked_reason',label:'阻断原因'}],{limit:30});
}
export function bindArchive(refresh){
  bind('#migrate','click',async()=>{try{await archiveApi.migrate();await refresh();toast('新一代迁移已推进')}catch(e){toast(e.message,true)}});
  for(const b of document.querySelectorAll('[data-advance]'))b.onclick=async()=>{try{await archiveApi.advance(b.dataset.advance);await refresh();toast('已沿用登记件继续迁移')}catch(e){toast(e.message,true)}};
  for(const b of document.querySelectorAll('[data-mig]'))b.onclick=async()=>{research.archiveMigrationId=Number(b.dataset.mig);research.archiveTab='all';await refresh()};
  for(const b of document.querySelectorAll('[data-tab]'))b.onclick=async()=>{research.archiveTab=b.dataset.tab;await refresh()};
}
