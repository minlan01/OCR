import{v as w,x as r,A as c,d as h,p as i,H as u,C as y,D as g,W,L as P,k as p,o as d,i as b,u as v,N as V,w as x,g as m,X as B,m as E,Y as k}from"./index-BG2_UJxV.js";function O(t){const{textColor2:e,textColor3:l,fontSize:o,fontWeight:s}=t;return{labelFontSize:o,labelFontWeight:s,valueFontWeight:s,valueFontSize:"24px",labelTextColor:l,valuePrefixTextColor:e,valueSuffixTextColor:e,valueTextColor:e}}const j={common:w,self:O},A=r("statistic",[c("label",`
 font-weight: var(--n-label-font-weight);
 transition: .3s color var(--n-bezier);
 font-size: var(--n-label-font-size);
 color: var(--n-label-text-color);
 `),r("statistic-value",`
 margin-top: 4px;
 font-weight: var(--n-value-font-weight);
 `,[c("prefix",`
 margin: 0 4px 0 0;
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-prefix-text-color);
 `,[r("icon",{verticalAlign:"-0.125em"})]),c("content",`
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-text-color);
 `),c("suffix",`
 margin: 0 0 0 4px;
 font-size: var(--n-value-font-size);
 transition: .3s color var(--n-bezier);
 color: var(--n-value-suffix-text-color);
 `,[r("icon",{verticalAlign:"-0.125em"})])])]),D=Object.assign(Object.assign({},g.props),{tabularNums:Boolean,label:String,value:[String,Number]}),H=h({name:"Statistic",props:D,slots:Object,setup(t){const{mergedClsPrefixRef:e,inlineThemeDisabled:l,mergedRtlRef:o}=y(t),s=g("Statistic","-statistic",A,j,t,e),f=W("Statistic",o,e),a=p(()=>{const{self:{labelFontWeight:C,valueFontSize:z,valueFontWeight:S,valuePrefixTextColor:_,labelTextColor:T,valueSuffixTextColor:R,valueTextColor:F,labelFontSize:N},common:{cubicBezierEaseInOut:$}}=s.value;return{"--n-bezier":$,"--n-label-font-size":N,"--n-label-font-weight":C,"--n-label-text-color":T,"--n-value-font-weight":S,"--n-value-font-size":z,"--n-value-prefix-text-color":_,"--n-value-suffix-text-color":R,"--n-value-text-color":F}}),n=l?P("statistic",void 0,a,t):void 0;return{rtlEnabled:f,mergedClsPrefix:e,cssVars:l?void 0:a,themeClass:n?.themeClass,onRender:n?.onRender}},render(){var t;const{mergedClsPrefix:e,$slots:{default:l,label:o,prefix:s,suffix:f}}=this;return(t=this.onRender)===null||t===void 0||t.call(this),i("div",{class:[`${e}-statistic`,this.themeClass,this.rtlEnabled&&`${e}-statistic--rtl`],style:this.cssVars},u(o,a=>i("div",{class:`${e}-statistic__label`},this.label||a)),i("div",{class:`${e}-statistic-value`,style:{fontVariantNumeric:this.tabularNums?"tabular-nums":""}},u(s,a=>a&&i("span",{class:`${e}-statistic-value__prefix`},a)),this.value!==void 0?i("span",{class:`${e}-statistic-value__content`},this.value):u(l,a=>a&&i("span",{class:`${e}-statistic-value__content`},a)),u(f,a=>a&&i("span",{class:`${e}-statistic-value__suffix`},a))))}}),L=h({__name:"StatCard",props:{label:{},value:{},icon:{},color:{},precision:{}},setup(t){const e=t,l=p(()=>typeof e.value=="number"&&e.precision!==void 0?e.value.toFixed(e.precision):String(e.value));return(o,s)=>(d(),b(v(V),{size:"small",bordered:!1,style:{"text-align":"center"}},{default:x(()=>[m(v(H),{label:t.label,value:l.value},B({_:2},[t.icon?{name:"prefix",fn:x(()=>[m(v(E),{color:t.color,size:20},{default:x(()=>[(d(),b(k(t.icon)))]),_:1},8,["color"])]),key:"0"}:void 0]),1032,["label","value"])]),_:1}))}});export{L as _};
