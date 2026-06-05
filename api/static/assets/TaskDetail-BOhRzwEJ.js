import{s as ze,v as _e,x as v,y as W,z as V,A as x,d as L,C as oe,D as se,p as C,E as be,G as we,H as ne,I as le,J as ke,K as Ce,L as De,k as M,M as E,O as Se,o as u,c as T,a as h,i as g,u as e,w as t,F as te,h as ue,j as s,t as p,P as D,Q as J,S as $e,e as Ne,f as Te,g as n,l as A,T as Be,U as Re,r as b,B as w,m as H,R as Pe,N as P,V as Me,q as Fe}from"./index-BG2_UJxV.js";import{_ as F}from"./StatCard.vue_vue_type_script_setup_true_lang-PXJOdH9H.js";import{N as U}from"./Tag-BBpPNpQo.js";import{N as G,a as ee}from"./Spin-Nd-ZMpM2.js";import{u as Oe}from"./scan-qwkoyOtd.js";import{l as Le,e as je}from"./client-Cq57ZeqF.js";import{u as Ie}from"./use-message-DINtNp2f.js";import{N as We,a as k}from"./DescriptionsItem-M6-DK1gF.js";import{D as Ve}from"./DownloadOutline-Djl6y1Fb.js";import{N as Ee}from"./Alert-B6-bzrJz.js";import{N as Ke}from"./Popconfirm-DVkZk8xz.js";import{N as Ae,a as O}from"./Grid-BeYhicdc.js";import{N as He}from"./Table-hY9rDfQ3.js";import{N as Je}from"./Select-BIBirMOi.js";import"./Suffix-BZAyImEW.js";let re=!1;function Ue(){if(ze&&window.CSS&&!re&&(re=!0,"registerProperty"in window?.CSS))try{CSS.registerProperty({name:"--n-color-start",syntax:"<color>",inherits:!1,initialValue:"#0000"}),CSS.registerProperty({name:"--n-color-end",syntax:"<color>",inherits:!1,initialValue:"#0000"})}catch{}}const Ge={titleMarginMedium:"0 0 6px 0",titleMarginLarge:"-2px 0 6px 0",titleFontSizeMedium:"14px",titleFontSizeLarge:"16px",iconSizeMedium:"14px",iconSizeLarge:"14px"};function qe(o){const{textColor3:c,infoColor:d,errorColor:i,successColor:r,warningColor:f,textColor1:m,textColor2:S,railColor:N,fontWeightStrong:B,fontSize:$}=o;return Object.assign(Object.assign({},Ge),{contentFontSize:$,titleFontWeight:B,circleBorder:`2px solid ${c}`,circleBorderInfo:`2px solid ${d}`,circleBorderError:`2px solid ${i}`,circleBorderSuccess:`2px solid ${r}`,circleBorderWarning:`2px solid ${f}`,iconColor:c,iconColorInfo:d,iconColorError:i,iconColorSuccess:r,iconColorWarning:f,titleTextColor:m,contentTextColor:S,metaTextColor:c,lineColor:N})}const Qe={common:_e,self:qe},ae=1.25,Xe=v("timeline",`
 position: relative;
 width: 100%;
 display: flex;
 flex-direction: column;
 line-height: ${ae};
`,[W("horizontal",`
 flex-direction: row;
 `,[V(">",[v("timeline-item",`
 flex-shrink: 0;
 padding-right: 40px;
 `,[W("dashed-line-type",[V(">",[v("timeline-item-timeline",[x("line",`
 background-image: linear-gradient(90deg, var(--n-color-start), var(--n-color-start) 50%, transparent 50%, transparent 100%);
 background-size: 10px 1px;
 `)])])]),V(">",[v("timeline-item-content",`
 margin-top: calc(var(--n-icon-size) + 12px);
 `,[V(">",[x("meta",`
 margin-top: 6px;
 margin-bottom: unset;
 `)])]),v("timeline-item-timeline",`
 width: 100%;
 height: calc(var(--n-icon-size) + 12px);
 `,[x("line",`
 left: var(--n-icon-size);
 top: calc(var(--n-icon-size) / 2 - 1px);
 right: 0px;
 width: unset;
 height: 2px;
 `)])])])])]),W("right-placement",[v("timeline-item",[v("timeline-item-content",`
 text-align: right;
 margin-right: calc(var(--n-icon-size) + 12px);
 `),v("timeline-item-timeline",`
 width: var(--n-icon-size);
 right: 0;
 `)])]),W("left-placement",[v("timeline-item",[v("timeline-item-content",`
 margin-left: calc(var(--n-icon-size) + 12px);
 `),v("timeline-item-timeline",`
 left: 0;
 `)])]),v("timeline-item",`
 position: relative;
 `,[V("&:last-child",[v("timeline-item-timeline",[x("line",`
 display: none;
 `)]),v("timeline-item-content",[x("meta",`
 margin-bottom: 0;
 `)])]),v("timeline-item-content",[x("title",`
 margin: var(--n-title-margin);
 font-size: var(--n-title-font-size);
 transition: color .3s var(--n-bezier);
 font-weight: var(--n-title-font-weight);
 color: var(--n-title-text-color);
 `),x("content",`
 transition: color .3s var(--n-bezier);
 font-size: var(--n-content-font-size);
 color: var(--n-content-text-color);
 `),x("meta",`
 transition: color .3s var(--n-bezier);
 font-size: 12px;
 margin-top: 6px;
 margin-bottom: 20px;
 color: var(--n-meta-text-color);
 `)]),W("dashed-line-type",[v("timeline-item-timeline",[x("line",`
 --n-color-start: var(--n-line-color);
 transition: --n-color-start .3s var(--n-bezier);
 background-color: transparent;
 background-image: linear-gradient(180deg, var(--n-color-start), var(--n-color-start) 50%, transparent 50%, transparent 100%);
 background-size: 1px 10px;
 `)])]),v("timeline-item-timeline",`
 width: calc(var(--n-icon-size) + 12px);
 position: absolute;
 top: calc(var(--n-title-font-size) * ${ae} / 2 - var(--n-icon-size) / 2);
 height: 100%;
 `,[x("circle",`
 border: var(--n-circle-border);
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 width: var(--n-icon-size);
 height: var(--n-icon-size);
 border-radius: var(--n-icon-size);
 box-sizing: border-box;
 `),x("icon",`
 color: var(--n-icon-color);
 font-size: var(--n-icon-size);
 height: var(--n-icon-size);
 width: var(--n-icon-size);
 display: flex;
 align-items: center;
 justify-content: center;
 `),x("line",`
 transition: background-color .3s var(--n-bezier);
 position: absolute;
 top: var(--n-icon-size);
 left: calc(var(--n-icon-size) / 2 - 1px);
 bottom: 0px;
 width: 2px;
 background-color: var(--n-line-color);
 `)])])]),Ye=Object.assign(Object.assign({},se.props),{horizontal:Boolean,itemPlacement:{type:String,default:"left"},size:{type:String,default:"medium"},iconSize:Number}),ce=be("n-timeline"),Ze=L({name:"Timeline",props:Ye,setup(o,{slots:c}){const{mergedClsPrefixRef:d}=oe(o),i=se("Timeline","-timeline",Xe,Qe,o,d);return we(ce,{props:o,mergedThemeRef:i,mergedClsPrefixRef:d}),()=>{const{value:r}=d;return C("div",{class:[`${r}-timeline`,o.horizontal&&`${r}-timeline--horizontal`,`${r}-timeline--${o.size}-size`,!o.horizontal&&`${r}-timeline--${o.itemPlacement}-placement`]},c)}}}),et={time:[String,Number],title:String,content:String,color:String,lineType:{type:String,default:"default"},type:{type:String,default:"default"}},tt=L({name:"TimelineItem",props:et,slots:Object,setup(o){const c=ke(ce);c||Ce("timeline-item","`n-timeline-item` must be placed inside `n-timeline`."),Ue();const{inlineThemeDisabled:d}=oe(),i=M(()=>{const{props:{size:f,iconSize:m},mergedThemeRef:S}=c,{type:N}=o,{self:{titleTextColor:B,contentTextColor:$,metaTextColor:j,lineColor:I,titleFontWeight:R,contentFontSize:z,[E("iconSize",f)]:_,[E("titleMargin",f)]:q,[E("titleFontSize",f)]:K,[E("circleBorder",N)]:Q,[E("iconColor",N)]:X},common:{cubicBezierEaseInOut:Y}}=S.value;return{"--n-bezier":Y,"--n-circle-border":Q,"--n-icon-color":X,"--n-content-font-size":z,"--n-content-text-color":$,"--n-line-color":I,"--n-meta-text-color":j,"--n-title-font-size":K,"--n-title-font-weight":R,"--n-title-margin":q,"--n-title-text-color":B,"--n-icon-size":Se(m)||_}}),r=d?De("timeline-item",M(()=>{const{props:{size:f,iconSize:m}}=c,{type:S}=o;return`${f[0]}${m||"a"}${S[0]}`}),i,c.props):void 0;return{mergedClsPrefix:c.mergedClsPrefixRef,cssVars:d?void 0:i,themeClass:r?.themeClass,onRender:r?.onRender}},render(){const{mergedClsPrefix:o,color:c,onRender:d,$slots:i}=this;return d?.(),C("div",{class:[`${o}-timeline-item`,this.themeClass,`${o}-timeline-item--${this.type}-type`,`${o}-timeline-item--${this.lineType}-line-type`],style:this.cssVars},C("div",{class:`${o}-timeline-item-timeline`},C("div",{class:`${o}-timeline-item-timeline__line`}),ne(i.icon,r=>r?C("div",{class:`${o}-timeline-item-timeline__icon`,style:{color:c}},r):C("div",{class:`${o}-timeline-item-timeline__circle`,style:{borderColor:c}}))),C("div",{class:`${o}-timeline-item-content`},ne(i.header,r=>r||this.title?C("div",{class:`${o}-timeline-item-content__title`},r||this.title):null),C("div",{class:`${o}-timeline-item-content__content`},le(i.default,()=>[this.content])),C("div",{class:`${o}-timeline-item-content__meta`},le(i.footer,()=>[this.time]))))}}),it={xmlns:"http://www.w3.org/2000/svg","xmlns:xlink":"http://www.w3.org/1999/xlink",viewBox:"0 0 512 512"},nt=L({name:"ArrowBackOutline",render:function(c,d){return u(),T("svg",it,d[0]||(d[0]=[h("path",{fill:"none",stroke:"currentColor","stroke-linecap":"round","stroke-linejoin":"round","stroke-width":"48",d:"M244 400L100 256l144-144"},null,-1),h("path",{fill:"none",stroke:"currentColor","stroke-linecap":"round","stroke-linejoin":"round","stroke-width":"48",d:"M120 256h292"},null,-1)]))}}),lt=L({__name:"StepTimeline",props:{steps:{}},setup(o){function c(r){return{pending:"default",processing:"info",completed:"success",failed:"error",skipped:"warning"}[r]||"default"}function d(r){return r<1e3?`${r}ms`:r<6e4?`${(r/1e3).toFixed(1)}s`:`${(r/6e4).toFixed(1)}min`}function i(r){const f=r.completed_at||r.started_at;return f?new Date(f).toLocaleTimeString("zh-CN"):""}return(r,f)=>(u(),g(e(Ze),null,{default:t(()=>[(u(!0),T(te,null,ue(o.steps,m=>(u(),g(e(tt),{key:m.id,type:c(m.status),title:m.step_name,time:i(m),"line-type":m.status==="failed"?"dashed":void 0},{default:t(()=>[m.duration_ms?(u(),g(e(U),{key:0,type:m.status==="failed"?"error":m.status==="completed"?"success":"default",size:"small"},{default:t(()=>[s(p(d(m.duration_ms)),1)]),_:2},1032,["type"])):D("",!0),m.error_message?(u(),g(e(J),{key:1,type:"error",depth:"3",style:{display:"block","margin-top":"4px","font-size":"12px"}},{default:t(()=>[s(p(m.error_message),1)]),_:2},1024)):D("",!0)]),_:2},1032,["type","title","time","line-type"]))),128))]),_:1}))}}),rt={style:{"max-height":"600px",overflow:"auto"}},at={key:0,style:{margin:"0",padding:"16px",background:"#f8f9fa","border-radius":"8px","font-size":"13px","line-height":"1.6","white-space":"pre-wrap","word-break":"break-all"}},ot=L({__name:"JsonViewer",props:{data:{}},setup(o){const c=o,d=M(()=>{if(c.data===null||c.data===void 0)return"";try{return JSON.stringify(c.data,null,2)}catch{return String(c.data)}});return(i,r)=>(u(),T("div",rt,[o.data?(u(),T("pre",at,p(d.value),1)):(u(),g(e(G),{key:1,description:"暂无数据"}))]))}}),wt=L({__name:"TaskDetail",setup(o){const c=Re(),d=Fe(),i=Oe(),r=Ie(),f=b(!1),m=b(null),S=b(!1),N=b(!1),B=b(!1),$=b(!1),j=b(!1),I=b(!1),R=b([]),z=b(null),_=c.params.id,q=M(()=>R.value.map(a=>({label:a.name,value:a.id}))),K=M(()=>z.value&&R.value.find(l=>l.id===z.value)?.description||null),Q=M(()=>i.currentDetail?.confidence_avg==null?"—":(i.currentDetail.confidence_avg*100).toFixed(1)+"%"),X=M(()=>i.currentDetail?.structure_score==null?"—":(i.currentDetail.structure_score*100).toFixed(0)+"%");$e(f,async a=>{if(a&&!m.value){S.value=!0;try{m.value=await i.getTaskResult(_)}catch{m.value={error:"无法加载结果"}}finally{S.value=!1}}});function Y(a){return{received:"info",pending:"default",processing:"info",completed:"success",failed:"error",retrying:"warning"}[a]||"default"}function de(a){return{received:"已接收",pending:"待处理",processing:"处理中",completed:"已完成",failed:"失败",retrying:"重试中"}[a]||a}function ie(a){return a==null?"—":a<1024?a+" B":a<1024*1024?(a/1024).toFixed(1)+" KB":(a/(1024*1024)).toFixed(1)+" MB"}function Z(a){return a?new Date(a).toLocaleString("zh-CN"):"—"}async function me(){try{await i.retryTask(_),i.fetchDetail(_)}catch(a){alert("重试失败: "+a.message)}}async function fe(){try{await i.deleteTask(_),d.push("/tasks")}catch(a){alert("删除失败: "+a.message)}}async function pe(){try{await i.fetchDetail(_),r.success("已刷新")}catch(a){r.error("刷新失败: "+(a.message||"未知错误"))}}async function ge(){if(i.currentDetail){B.value=!0;try{await i.downloadWord(_,i.currentDetail.filename),r.success("Word 文档下载成功")}catch(a){r.error("下载失败: "+(a.message||"未知错误"))}finally{B.value=!1}}}async function ve(){$.value=!0,z.value=null,j.value=!0;try{R.value=await Le()}catch(a){r.error("加载模板列表失败: "+a.message)}finally{j.value=!1}}async function ye(){if(!(!z.value||!i.currentDetail)){I.value=!0;try{const l=R.value.find(xe=>xe.id===z.value)?.name||"模板",he=`${i.currentDetail.filename.replace(/\.pdf$/i,"")}_${l}.docx`;await je(_,z.value,he),r.success("模板导出成功"),$.value=!1}catch(a){r.error("模板导出失败: "+(a.message||"未知错误"))}finally{I.value=!1}}}return Ne(()=>{i.startDetailPolling(_),N.value=!0}),Te(()=>{i.stopDetailPolling(),N.value=!1}),(a,l)=>(u(),T("div",null,[n(e(A),{style:{"margin-bottom":"16px"},align:"center"},{default:t(()=>[n(e(w),{size:"small",quaternary:"",onClick:l[0]||(l[0]=y=>a.$router.back())},{icon:t(()=>[n(e(H),null,{default:t(()=>[n(e(nt))]),_:1})]),default:t(()=>[l[6]||(l[6]=s(" 返回列表 ",-1))]),_:1}),n(e(w),{size:"small",loading:e(i).detailLoading,onClick:pe},{icon:t(()=>[n(e(H),null,{default:t(()=>[n(e(Pe))]),_:1})]),default:t(()=>[l[7]||(l[7]=s(" 刷新 ",-1))]),_:1},8,["loading"]),N.value?(u(),g(e(U),{key:0,type:"info",size:"small"},{default:t(()=>[...l[8]||(l[8]=[s("自动刷新中...",-1)])]),_:1})):D("",!0)]),_:1}),n(e(ee),{show:e(i).detailLoading},{default:t(()=>[e(i).currentDetail?(u(),g(e(A),{key:0,vertical:"",size:16},{default:t(()=>[n(e(P),{title:"基本信息",size:"small"},{default:t(()=>[n(e(We),{column:2,size:"small",bordered:""},{default:t(()=>[n(e(k),{label:"文件名"},{default:t(()=>[s(p(e(i).currentDetail.filename),1)]),_:1}),n(e(k),{label:"状态"},{default:t(()=>[n(e(U),{type:Y(e(i).currentDetail.status)},{default:t(()=>[s(p(de(e(i).currentDetail.status)),1)]),_:1},8,["type"])]),_:1}),n(e(k),{label:"来源类型"},{default:t(()=>[s(p(e(i).currentDetail.source_type),1)]),_:1}),n(e(k),{label:"扫描仪"},{default:t(()=>[s(p(e(i).currentDetail.scanner_id||"—"),1)]),_:1}),n(e(k),{label:"文件大小"},{default:t(()=>[s(p(ie(e(i).currentDetail.file_size)),1)]),_:1}),n(e(k),{label:"MD5"},{default:t(()=>[n(e(J),{code:""},{default:t(()=>[s(p(e(i).currentDetail.file_md5||"—"),1)]),_:1})]),_:1}),n(e(k),{label:"创建时间"},{default:t(()=>[s(p(Z(e(i).currentDetail.created_at)),1)]),_:1}),n(e(k),{label:"开始时间"},{default:t(()=>[s(p(Z(e(i).currentDetail.started_at)),1)]),_:1}),n(e(k),{label:"完成时间"},{default:t(()=>[s(p(Z(e(i).currentDetail.completed_at)),1)]),_:1}),n(e(k),{label:"回调地址"},{default:t(()=>[s(p(e(i).currentDetail.callback_url||"—"),1)]),_:1})]),_:1}),n(e(A),{style:{"margin-top":"12px"}},{default:t(()=>[e(i).currentDetail.status==="completed"?(u(),g(e(w),{key:0,size:"small",type:"primary",onClick:l[1]||(l[1]=y=>f.value=!f.value)},{default:t(()=>[s(p(f.value?"收起结果":"查看 JSON 结果"),1)]),_:1})):D("",!0),e(i).currentDetail.status==="completed"?(u(),g(e(w),{key:1,size:"small",type:"success",loading:B.value,onClick:ge},{icon:t(()=>[n(e(H),null,{default:t(()=>[n(e(Ve))]),_:1})]),default:t(()=>[l[9]||(l[9]=s(" 下载 Word 文档 ",-1))]),_:1},8,["loading"])):D("",!0),e(i).currentDetail.status==="completed"?(u(),g(e(w),{key:2,size:"small",type:"info",onClick:ve},{icon:t(()=>[n(e(H),null,{default:t(()=>[n(e(Me))]),_:1})]),default:t(()=>[l[10]||(l[10]=s(" 按模板导出 ",-1))]),_:1})):D("",!0),e(i).currentDetail.status==="failed"?(u(),g(e(w),{key:3,size:"small",type:"warning",onClick:me},{default:t(()=>[...l[11]||(l[11]=[s(" 重试任务 ",-1)])]),_:1})):D("",!0),n(e(Ke),{onPositiveClick:fe},{trigger:t(()=>[n(e(w),{size:"small",type:"error",ghost:""},{default:t(()=>[...l[12]||(l[12]=[s("删除任务",-1)])]),_:1})]),default:t(()=>[l[13]||(l[13]=s(" 确认删除此任务？ ",-1))]),_:1})]),_:1})]),_:1}),n(e(P),{title:"统计指标",size:"small"},{default:t(()=>[n(e(Ae),{cols:6,"x-gap":12,responsive:"screen"},{default:t(()=>[n(e(O),null,{default:t(()=>[n(F,{label:"页数",value:e(i).currentDetail.page_count??"—"},null,8,["value"])]),_:1}),n(e(O),null,{default:t(()=>[n(F,{label:"置信度",value:Q.value},null,8,["value"])]),_:1}),n(e(O),null,{default:t(()=>[n(F,{label:"结构评分",value:X.value},null,8,["value"])]),_:1}),n(e(O),null,{default:t(()=>[n(F,{label:"表格",value:e(i).currentDetail.table_count},null,8,["value"])]),_:1}),n(e(O),null,{default:t(()=>[n(F,{label:"标题",value:e(i).currentDetail.heading_count},null,8,["value"])]),_:1}),n(e(O),null,{default:t(()=>[n(F,{label:"段落",value:e(i).currentDetail.paragraph_count},null,8,["value"])]),_:1})]),_:1})]),_:1}),e(i).currentDetail.error_message?(u(),g(e(P),{key:0,title:"错误信息",size:"small"},{default:t(()=>[n(e(Ee),{type:"error",title:e(i).currentDetail.error_code||"ERROR"},{default:t(()=>[s(p(e(i).currentDetail.error_message),1)]),_:1},8,["title"])]),_:1})):D("",!0),n(e(P),{title:"处理步骤",size:"small"},{default:t(()=>[n(lt,{steps:e(i).currentDetail.steps},null,8,["steps"])]),_:1}),n(e(P),{title:"文件产物",size:"small"},{default:t(()=>[e(i).currentDetail.files.length?(u(),g(e(He),{key:1,"single-line":!0,size:"small"},{default:t(()=>[l[14]||(l[14]=h("thead",null,[h("tr",null,[h("th",null,"类型"),h("th",null,"页码"),h("th",null,"Bucket"),h("th",null,"大小")])],-1)),h("tbody",null,[(u(!0),T(te,null,ue(e(i).currentDetail.files,y=>(u(),T("tr",{key:y.id},[h("td",null,[n(e(U),{size:"tiny"},{default:t(()=>[s(p(y.file_type),1)]),_:2},1024)]),h("td",null,p(y.page_no??"—"),1),h("td",null,p(y.bucket),1),h("td",null,p(ie(y.size_bytes)),1)]))),128))])]),_:1})):(u(),g(e(G),{key:0,description:"暂无文件"}))]),_:1}),f.value?(u(),g(e(P),{key:1,title:"结构化结果",size:"small"},{"header-extra":t(()=>[n(e(w),{size:"tiny",onClick:l[2]||(l[2]=y=>f.value=!1)},{default:t(()=>[...l[15]||(l[15]=[s("关闭",-1)])]),_:1})]),default:t(()=>[n(e(ee),{show:S.value},{default:t(()=>[n(ot,{data:m.value},null,8,["data"])]),_:1},8,["show"])]),_:1})):D("",!0)]),_:1})):(u(),g(e(G),{key:1,description:"任务不存在",style:{padding:"60px"}}))]),_:1},8,["show"]),n(e(Be),{show:$.value,"onUpdate:show":l[5]||(l[5]=y=>$.value=y),preset:"card",title:"按模板导出 Word",style:{"max-width":"500px"}},{action:t(()=>[n(e(A),{justify:"end"},{default:t(()=>[n(e(w),{onClick:l[4]||(l[4]=y=>$.value=!1)},{default:t(()=>[...l[17]||(l[17]=[s("取消",-1)])]),_:1}),n(e(w),{type:"primary",loading:I.value,disabled:!z.value,onClick:ye},{default:t(()=>[...l[18]||(l[18]=[s(" 确认导出 ",-1)])]),_:1},8,["loading","disabled"])]),_:1})]),default:t(()=>[n(e(ee),{show:j.value},{default:t(()=>[R.value.length?(u(),T(te,{key:1},[n(e(J),{style:{"margin-bottom":"12px",display:"block"}},{default:t(()=>[...l[16]||(l[16]=[s(" 选择模板后，系统将从识别结果中按模板 Schema 提取数据并生成 Word 文档。 ",-1)])]),_:1}),n(e(Je),{value:z.value,"onUpdate:value":l[3]||(l[3]=y=>z.value=y),options:q.value,placeholder:"请选择模板"},null,8,["value","options"]),K.value?(u(),g(e(P),{key:0,size:"small",style:{"margin-top":"12px"},embedded:""},{default:t(()=>[n(e(J),{depth:"3"},{default:t(()=>[s(p(K.value),1)]),_:1})]),_:1})):D("",!0)],64)):(u(),g(e(G),{key:0,description:"暂无可用模板，请先在「模板管理」中上传"}))]),_:1},8,["show"])]),_:1},8,["show"])]))}});export{wt as default};
