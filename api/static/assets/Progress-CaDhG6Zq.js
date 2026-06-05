import{v as G,d as B,p as r,a5 as W,k as v,bN as O,a6 as j,bM as q,bO as L,bT as M,O as k,z,x as a,y as w,C as A,D as T,L as X,M as I}from"./index-BG2_UJxV.js";function Y(e){const{infoColor:d,successColor:u,warningColor:f,errorColor:c,textColor2:i,progressRailColor:t,fontSize:n,fontWeight:g}=e;return{fontSize:n,fontSizeCircle:"28px",fontWeightCircle:g,railColor:t,railHeight:"8px",iconSizeCircle:"36px",iconSizeLine:"18px",iconColor:d,iconColorInfo:d,iconColorSuccess:u,iconColorWarning:f,iconColorError:c,textColorCircle:i,textColorLineInner:"rgb(255, 255, 255)",textColorLineOuter:i,fillColor:d,fillColorInfo:d,fillColorSuccess:u,fillColorWarning:f,fillColorError:c,lineBgProcessing:"linear-gradient(90deg, rgba(255, 255, 255, .3) 0%, rgba(255, 255, 255, .5) 100%)"}}const _={name:"Progress",common:G,self:Y},H={success:r(L,null),error:r(q,null),warning:r(j,null),info:r(O,null)},E=B({name:"ProgressCircle",props:{clsPrefix:{type:String,required:!0},status:{type:String,required:!0},strokeWidth:{type:Number,required:!0},fillColor:[String,Object],railColor:String,railStyle:[String,Object],percentage:{type:Number,default:0},offsetDegree:{type:Number,default:0},showIndicator:{type:Boolean,required:!0},indicatorTextColor:String,unit:String,viewBoxWidth:{type:Number,required:!0},gapDegree:{type:Number,required:!0},gapOffsetDegree:{type:Number,default:0}},setup(e,{slots:d}){const u=v(()=>{const i="gradient",{fillColor:t}=e;return typeof t=="object"?`${i}-${M(JSON.stringify(t))}`:i});function f(i,t,n,g){const{gapDegree:p,viewBoxWidth:h,strokeWidth:y}=e,l=50,b=0,s=l,o=0,x=2*l,C=50+y/2,m=`M ${C},${C} m ${b},${s}
      a ${l},${l} 0 1 1 ${o},${-x}
      a ${l},${l} 0 1 1 ${-o},${x}`,$=Math.PI*2*l,S={stroke:g==="rail"?n:typeof e.fillColor=="object"?`url(#${u.value})`:n,strokeDasharray:`${Math.min(i,100)/100*($-p)}px ${h*8}px`,strokeDashoffset:`-${p/2}px`,transformOrigin:t?"center":void 0,transform:t?`rotate(${t}deg)`:void 0};return{pathString:m,pathStyle:S}}const c=()=>{const i=typeof e.fillColor=="object",t=i?e.fillColor.stops[0]:"",n=i?e.fillColor.stops[1]:"";return i&&r("defs",null,r("linearGradient",{id:u.value,x1:"0%",y1:"100%",x2:"100%",y2:"0%"},r("stop",{offset:"0%","stop-color":t}),r("stop",{offset:"100%","stop-color":n})))};return()=>{const{fillColor:i,railColor:t,strokeWidth:n,offsetDegree:g,status:p,percentage:h,showIndicator:y,indicatorTextColor:l,unit:b,gapOffsetDegree:s,clsPrefix:o}=e,{pathString:x,pathStyle:C}=f(100,0,t,"rail"),{pathString:m,pathStyle:$}=f(h,g,i,"fill"),S=100+n;return r("div",{class:`${o}-progress-content`,role:"none"},r("div",{class:`${o}-progress-graph`,"aria-hidden":!0},r("div",{class:`${o}-progress-graph-circle`,style:{transform:s?`rotate(${s}deg)`:void 0}},r("svg",{viewBox:`0 0 ${S} ${S}`},c(),r("g",null,r("path",{class:`${o}-progress-graph-circle-rail`,d:x,"stroke-width":n,"stroke-linecap":"round",fill:"none",style:C})),r("g",null,r("path",{class:[`${o}-progress-graph-circle-fill`,h===0&&`${o}-progress-graph-circle-fill--empty`],d:m,"stroke-width":n,"stroke-linecap":"round",fill:"none",style:$}))))),y?r("div",null,d.default?r("div",{class:`${o}-progress-custom-content`,role:"none"},d.default()):p!=="default"?r("div",{class:`${o}-progress-icon`,"aria-hidden":!0},r(W,{clsPrefix:o},{default:()=>H[p]})):r("div",{class:`${o}-progress-text`,style:{color:l},role:"none"},r("span",{class:`${o}-progress-text__percentage`},h),r("span",{class:`${o}-progress-text__unit`},b))):null)}}}),V={success:r(L,null),error:r(q,null),warning:r(j,null),info:r(O,null)},F=B({name:"ProgressLine",props:{clsPrefix:{type:String,required:!0},percentage:{type:Number,default:0},railColor:String,railStyle:[String,Object],fillColor:[String,Object],status:{type:String,required:!0},indicatorPlacement:{type:String,required:!0},indicatorTextColor:String,unit:{type:String,default:"%"},processing:{type:Boolean,required:!0},showIndicator:{type:Boolean,required:!0},height:[String,Number],railBorderRadius:[String,Number],fillBorderRadius:[String,Number]},setup(e,{slots:d}){const u=v(()=>k(e.height)),f=v(()=>{var t,n;return typeof e.fillColor=="object"?`linear-gradient(to right, ${(t=e.fillColor)===null||t===void 0?void 0:t.stops[0]} , ${(n=e.fillColor)===null||n===void 0?void 0:n.stops[1]})`:e.fillColor}),c=v(()=>e.railBorderRadius!==void 0?k(e.railBorderRadius):e.height!==void 0?k(e.height,{c:.5}):""),i=v(()=>e.fillBorderRadius!==void 0?k(e.fillBorderRadius):e.railBorderRadius!==void 0?k(e.railBorderRadius):e.height!==void 0?k(e.height,{c:.5}):"");return()=>{const{indicatorPlacement:t,railColor:n,railStyle:g,percentage:p,unit:h,indicatorTextColor:y,status:l,showIndicator:b,processing:s,clsPrefix:o}=e;return r("div",{class:`${o}-progress-content`,role:"none"},r("div",{class:`${o}-progress-graph`,"aria-hidden":!0},r("div",{class:[`${o}-progress-graph-line`,{[`${o}-progress-graph-line--indicator-${t}`]:!0}]},r("div",{class:`${o}-progress-graph-line-rail`,style:[{backgroundColor:n,height:u.value,borderRadius:c.value},g]},r("div",{class:[`${o}-progress-graph-line-fill`,s&&`${o}-progress-graph-line-fill--processing`],style:{maxWidth:`${e.percentage}%`,background:f.value,height:u.value,lineHeight:u.value,borderRadius:i.value}},t==="inside"?r("div",{class:`${o}-progress-graph-line-indicator`,style:{color:y}},d.default?d.default():`${p}${h}`):null)))),b&&t==="outside"?r("div",null,d.default?r("div",{class:`${o}-progress-custom-content`,style:{color:y},role:"none"},d.default()):l==="default"?r("div",{role:"none",class:`${o}-progress-icon ${o}-progress-icon--as-text`,style:{color:y}},p,h):r("div",{class:`${o}-progress-icon`,"aria-hidden":!0},r(W,{clsPrefix:o},{default:()=>V[l]}))):null)}}});function D(e,d,u=100){return`m ${u/2} ${u/2-e} a ${e} ${e} 0 1 1 0 ${2*e} a ${e} ${e} 0 1 1 0 -${2*e}`}const J=B({name:"ProgressMultipleCircle",props:{clsPrefix:{type:String,required:!0},viewBoxWidth:{type:Number,required:!0},percentage:{type:Array,default:[0]},strokeWidth:{type:Number,required:!0},circleGap:{type:Number,required:!0},showIndicator:{type:Boolean,required:!0},fillColor:{type:Array,default:()=>[]},railColor:{type:Array,default:()=>[]},railStyle:{type:Array,default:()=>[]}},setup(e,{slots:d}){const u=v(()=>e.percentage.map((i,t)=>`${Math.PI*i/100*(e.viewBoxWidth/2-e.strokeWidth/2*(1+2*t)-e.circleGap*t)*2}, ${e.viewBoxWidth*8}`)),f=(c,i)=>{const t=e.fillColor[i],n=typeof t=="object"?t.stops[0]:"",g=typeof t=="object"?t.stops[1]:"";return typeof e.fillColor[i]=="object"&&r("linearGradient",{id:`gradient-${i}`,x1:"100%",y1:"0%",x2:"0%",y2:"100%"},r("stop",{offset:"0%","stop-color":n}),r("stop",{offset:"100%","stop-color":g}))};return()=>{const{viewBoxWidth:c,strokeWidth:i,circleGap:t,showIndicator:n,fillColor:g,railColor:p,railStyle:h,percentage:y,clsPrefix:l}=e;return r("div",{class:`${l}-progress-content`,role:"none"},r("div",{class:`${l}-progress-graph`,"aria-hidden":!0},r("div",{class:`${l}-progress-graph-circle`},r("svg",{viewBox:`0 0 ${c} ${c}`},r("defs",null,y.map((b,s)=>f(b,s))),y.map((b,s)=>r("g",{key:s},r("path",{class:`${l}-progress-graph-circle-rail`,d:D(c/2-i/2*(1+2*s)-t*s,i,c),"stroke-width":i,"stroke-linecap":"round",fill:"none",style:[{strokeDashoffset:0,stroke:p[s]},h[s]]}),r("path",{class:[`${l}-progress-graph-circle-fill`,b===0&&`${l}-progress-graph-circle-fill--empty`],d:D(c/2-i/2*(1+2*s)-t*s,i,c),"stroke-width":i,"stroke-linecap":"round",fill:"none",style:{strokeDasharray:u.value[s],strokeDashoffset:0,stroke:typeof g[s]=="object"?`url(#gradient-${s})`:g[s]}})))))),n&&d.default?r("div",null,r("div",{class:`${l}-progress-text`},d.default())):null)}}}),K=z([a("progress",{display:"inline-block"},[a("progress-icon",`
 color: var(--n-icon-color);
 transition: color .3s var(--n-bezier);
 `),w("line",`
 width: 100%;
 display: block;
 `,[a("progress-content",`
 display: flex;
 align-items: center;
 `,[a("progress-graph",{flex:1})]),a("progress-custom-content",{marginLeft:"14px"}),a("progress-icon",`
 width: 30px;
 padding-left: 14px;
 height: var(--n-icon-size-line);
 line-height: var(--n-icon-size-line);
 font-size: var(--n-icon-size-line);
 `,[w("as-text",`
 color: var(--n-text-color-line-outer);
 text-align: center;
 width: 40px;
 font-size: var(--n-font-size);
 padding-left: 4px;
 transition: color .3s var(--n-bezier);
 `)])]),w("circle, dashboard",{width:"120px"},[a("progress-custom-content",`
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 `),a("progress-text",`
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 display: flex;
 align-items: center;
 color: inherit;
 font-size: var(--n-font-size-circle);
 color: var(--n-text-color-circle);
 font-weight: var(--n-font-weight-circle);
 transition: color .3s var(--n-bezier);
 white-space: nowrap;
 `),a("progress-icon",`
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 display: flex;
 align-items: center;
 color: var(--n-icon-color);
 font-size: var(--n-icon-size-circle);
 `)]),w("multiple-circle",`
 width: 200px;
 color: inherit;
 `,[a("progress-text",`
 font-weight: var(--n-font-weight-circle);
 color: var(--n-text-color-circle);
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 transition: color .3s var(--n-bezier);
 `)]),a("progress-content",{position:"relative"}),a("progress-graph",{position:"relative"},[a("progress-graph-circle",[z("svg",{verticalAlign:"bottom"}),a("progress-graph-circle-fill",`
 stroke: var(--n-fill-color);
 transition:
 opacity .3s var(--n-bezier),
 stroke .3s var(--n-bezier),
 stroke-dasharray .3s var(--n-bezier);
 `,[w("empty",{opacity:0})]),a("progress-graph-circle-rail",`
 transition: stroke .3s var(--n-bezier);
 overflow: hidden;
 stroke: var(--n-rail-color);
 `)]),a("progress-graph-line",[w("indicator-inside",[a("progress-graph-line-rail",`
 height: 16px;
 line-height: 16px;
 border-radius: 10px;
 `,[a("progress-graph-line-fill",`
 height: inherit;
 border-radius: 10px;
 `),a("progress-graph-line-indicator",`
 background: #0000;
 white-space: nowrap;
 text-align: right;
 margin-left: 14px;
 margin-right: 14px;
 height: inherit;
 font-size: 12px;
 color: var(--n-text-color-line-inner);
 transition: color .3s var(--n-bezier);
 `)])]),w("indicator-inside-label",`
 height: 16px;
 display: flex;
 align-items: center;
 `,[a("progress-graph-line-rail",`
 flex: 1;
 transition: background-color .3s var(--n-bezier);
 `),a("progress-graph-line-indicator",`
 background: var(--n-fill-color);
 font-size: 12px;
 transform: translateZ(0);
 display: flex;
 vertical-align: middle;
 height: 16px;
 line-height: 16px;
 padding: 0 10px;
 border-radius: 10px;
 position: absolute;
 white-space: nowrap;
 color: var(--n-text-color-line-inner);
 transition:
 right .2s var(--n-bezier),
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `)]),a("progress-graph-line-rail",`
 position: relative;
 overflow: hidden;
 height: var(--n-rail-height);
 border-radius: 5px;
 background-color: var(--n-rail-color);
 transition: background-color .3s var(--n-bezier);
 `,[a("progress-graph-line-fill",`
 background: var(--n-fill-color);
 position: relative;
 border-radius: 5px;
 height: inherit;
 width: 100%;
 max-width: 0%;
 transition:
 background-color .3s var(--n-bezier),
 max-width .2s var(--n-bezier);
 `,[w("processing",[z("&::after",`
 content: "";
 background-image: var(--n-line-bg-processing);
 animation: progress-processing-animation 2s var(--n-bezier) infinite;
 `)])])])])])]),z("@keyframes progress-processing-animation",`
 0% {
 position: absolute;
 left: 0;
 top: 0;
 bottom: 0;
 right: 100%;
 opacity: 1;
 }
 66% {
 position: absolute;
 left: 0;
 top: 0;
 bottom: 0;
 right: 0;
 opacity: 0;
 }
 100% {
 position: absolute;
 left: 0;
 top: 0;
 bottom: 0;
 right: 0;
 opacity: 0;
 }
 `)]),Z=Object.assign(Object.assign({},T.props),{processing:Boolean,type:{type:String,default:"line"},gapDegree:Number,gapOffsetDegree:Number,status:{type:String,default:"default"},railColor:[String,Array],railStyle:[String,Array],color:[String,Array,Object],viewBoxWidth:{type:Number,default:100},strokeWidth:{type:Number,default:7},percentage:[Number,Array],unit:{type:String,default:"%"},showIndicator:{type:Boolean,default:!0},indicatorPosition:{type:String,default:"outside"},indicatorPlacement:{type:String,default:"outside"},indicatorTextColor:String,circleGap:{type:Number,default:1},height:Number,borderRadius:[String,Number],fillBorderRadius:[String,Number],offsetDegree:Number}),U=B({name:"Progress",props:Z,setup(e){const d=v(()=>e.indicatorPlacement||e.indicatorPosition),u=v(()=>{if(e.gapDegree||e.gapDegree===0)return e.gapDegree;if(e.type==="dashboard")return 75}),{mergedClsPrefixRef:f,inlineThemeDisabled:c}=A(e),i=T("Progress","-progress",K,_,e,f),t=v(()=>{const{status:g}=e,{common:{cubicBezierEaseInOut:p},self:{fontSize:h,fontSizeCircle:y,railColor:l,railHeight:b,iconSizeCircle:s,iconSizeLine:o,textColorCircle:x,textColorLineInner:C,textColorLineOuter:m,lineBgProcessing:$,fontWeightCircle:S,[I("iconColor",g)]:R,[I("fillColor",g)]:P}}=i.value;return{"--n-bezier":p,"--n-fill-color":P,"--n-font-size":h,"--n-font-size-circle":y,"--n-font-weight-circle":S,"--n-icon-color":R,"--n-icon-size-circle":s,"--n-icon-size-line":o,"--n-line-bg-processing":$,"--n-rail-color":l,"--n-rail-height":b,"--n-text-color-circle":x,"--n-text-color-line-inner":C,"--n-text-color-line-outer":m}}),n=c?X("progress",v(()=>e.status[0]),t,e):void 0;return{mergedClsPrefix:f,mergedIndicatorPlacement:d,gapDeg:u,cssVars:c?void 0:t,themeClass:n?.themeClass,onRender:n?.onRender}},render(){const{type:e,cssVars:d,indicatorTextColor:u,showIndicator:f,status:c,railColor:i,railStyle:t,color:n,percentage:g,viewBoxWidth:p,strokeWidth:h,mergedIndicatorPlacement:y,unit:l,borderRadius:b,fillBorderRadius:s,height:o,processing:x,circleGap:C,mergedClsPrefix:m,gapDeg:$,gapOffsetDegree:S,themeClass:R,$slots:P,onRender:N}=this;return N?.(),r("div",{class:[R,`${m}-progress`,`${m}-progress--${e}`,`${m}-progress--${c}`],style:d,"aria-valuemax":100,"aria-valuemin":0,"aria-valuenow":g,role:e==="circle"||e==="line"||e==="dashboard"?"progressbar":"none"},e==="circle"||e==="dashboard"?r(E,{clsPrefix:m,status:c,showIndicator:f,indicatorTextColor:u,railColor:i,fillColor:n,railStyle:t,offsetDegree:this.offsetDegree,percentage:g,viewBoxWidth:p,strokeWidth:h,gapDegree:$===void 0?e==="dashboard"?75:0:$,gapOffsetDegree:S,unit:l},P):e==="line"?r(F,{clsPrefix:m,status:c,showIndicator:f,indicatorTextColor:u,railColor:i,fillColor:n,railStyle:t,percentage:g,processing:x,indicatorPlacement:y,unit:l,fillBorderRadius:s,railBorderRadius:b,height:o},P):e==="multiple-circle"?r(J,{clsPrefix:m,strokeWidth:h,railColor:i,fillColor:n,railStyle:t,viewBoxWidth:p,percentage:g,showIndicator:f,circleGap:C},P):null)}});export{U as N,_ as p};
