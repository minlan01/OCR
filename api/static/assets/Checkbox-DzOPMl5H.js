import{v as be,af as ue,d as j,p as b,C as K,aI as E,r as H,aq as L,k as I,E as he,G as fe,a4 as U,ab as d,z as C,x as n,y as M,A as $,aB as ve,bf as ke,bg as xe,H as me,aE as ge,au as pe,aF as Ce,D as G,W as ye,L as ze,ay as we,J as Re,M as N}from"./index-BG2_UJxV.js";const Se={sizeSmall:"14px",sizeMedium:"16px",sizeLarge:"18px",labelPadding:"0 8px",labelFontWeight:"400"};function De(o){const{baseColor:c,inputColorDisabled:u,cardColor:y,modalColor:S,popoverColor:f,textColorDisabled:v,borderColor:i,primaryColor:k,textColor2:a,fontSizeSmall:x,fontSizeMedium:t,fontSizeLarge:r,borderRadiusSmall:m,lineHeight:h}=o;return Object.assign(Object.assign({},Se),{labelLineHeight:h,fontSizeSmall:x,fontSizeMedium:t,fontSizeLarge:r,borderRadius:m,color:c,colorChecked:k,colorDisabled:u,colorDisabledChecked:u,colorTableHeader:y,colorTableHeaderModal:S,colorTableHeaderPopover:f,checkMarkColor:c,checkMarkColorDisabled:v,checkMarkColorDisabledChecked:v,border:`1px solid ${i}`,borderDisabled:`1px solid ${i}`,borderDisabledChecked:`1px solid ${i}`,borderChecked:`1px solid ${k}`,borderFocus:`1px solid ${k}`,boxShadowFocus:`0 0 0 2px ${ue(k,{alpha:.3})}`,textColor:a,textColorDisabled:v})}const Te={name:"Checkbox",common:be,self:De},O=he("n-checkbox-group"),$e={min:Number,max:Number,size:String,value:Array,defaultValue:{type:Array,default:null},disabled:{type:Boolean,default:void 0},"onUpdate:value":[Function,Array],onUpdateValue:[Function,Array],onChange:[Function,Array]},Pe=j({name:"CheckboxGroup",props:$e,setup(o){const{mergedClsPrefixRef:c}=K(o),u=E(o),{mergedSizeRef:y,mergedDisabledRef:S}=u,f=H(o.defaultValue),v=I(()=>o.value),i=L(v,f),k=I(()=>{var t;return((t=i.value)===null||t===void 0?void 0:t.length)||0}),a=I(()=>Array.isArray(i.value)?new Set(i.value):new Set);function x(t,r){const{nTriggerFormInput:m,nTriggerFormChange:h}=u,{onChange:l,"onUpdate:value":z,onUpdateValue:w}=o;if(Array.isArray(i.value)){const s=Array.from(i.value),B=s.findIndex(P=>P===r);t?~B||(s.push(r),w&&d(w,s,{actionType:"check",value:r}),z&&d(z,s,{actionType:"check",value:r}),m(),h(),f.value=s,l&&d(l,s)):~B&&(s.splice(B,1),w&&d(w,s,{actionType:"uncheck",value:r}),z&&d(z,s,{actionType:"uncheck",value:r}),l&&d(l,s),f.value=s,m(),h())}else t?(w&&d(w,[r],{actionType:"check",value:r}),z&&d(z,[r],{actionType:"check",value:r}),l&&d(l,[r]),f.value=[r],m(),h()):(w&&d(w,[],{actionType:"uncheck",value:r}),z&&d(z,[],{actionType:"uncheck",value:r}),l&&d(l,[]),f.value=[],m(),h())}return fe(O,{checkedCountRef:k,maxRef:U(o,"max"),minRef:U(o,"min"),valueSetRef:a,disabledRef:S,mergedSizeRef:y,toggleCheckbox:x}),{mergedClsPrefix:c}},render(){return b("div",{class:`${this.mergedClsPrefix}-checkbox-group`,role:"group"},this.$slots)}}),Me=()=>b("svg",{viewBox:"0 0 64 64",class:"check-icon"},b("path",{d:"M50.42,16.76L22.34,39.45l-8.1-11.46c-1.12-1.58-3.3-1.96-4.88-0.84c-1.58,1.12-1.95,3.3-0.84,4.88l10.26,14.51  c0.56,0.79,1.42,1.31,2.38,1.45c0.16,0.02,0.32,0.03,0.48,0.03c0.8,0,1.57-0.27,2.2-0.78l30.99-25.03c1.5-1.21,1.74-3.42,0.52-4.92  C54.13,15.78,51.93,15.55,50.42,16.76z"})),Fe=()=>b("svg",{viewBox:"0 0 100 100",class:"line-icon"},b("path",{d:"M80.2,55.5H21.4c-2.8,0-5.1-2.5-5.1-5.5l0,0c0-3,2.3-5.5,5.1-5.5h58.7c2.8,0,5.1,2.5,5.1,5.5l0,0C85.2,53.1,82.9,55.5,80.2,55.5z"})),Ae=C([n("checkbox",`
 font-size: var(--n-font-size);
 outline: none;
 cursor: pointer;
 display: inline-flex;
 flex-wrap: nowrap;
 align-items: flex-start;
 word-break: break-word;
 line-height: var(--n-size);
 --n-merged-color-table: var(--n-color-table);
 `,[M("show-label","line-height: var(--n-label-line-height);"),C("&:hover",[n("checkbox-box",[$("border","border: var(--n-border-checked);")])]),C("&:focus:not(:active)",[n("checkbox-box",[$("border",`
 border: var(--n-border-focus);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),M("inside-table",[n("checkbox-box",`
 background-color: var(--n-merged-color-table);
 `)]),M("checked",[n("checkbox-box",`
 background-color: var(--n-color-checked);
 `,[n("checkbox-icon",[C(".check-icon",`
 opacity: 1;
 transform: scale(1);
 `)])])]),M("indeterminate",[n("checkbox-box",[n("checkbox-icon",[C(".check-icon",`
 opacity: 0;
 transform: scale(.5);
 `),C(".line-icon",`
 opacity: 1;
 transform: scale(1);
 `)])])]),M("checked, indeterminate",[C("&:focus:not(:active)",[n("checkbox-box",[$("border",`
 border: var(--n-border-checked);
 box-shadow: var(--n-box-shadow-focus);
 `)])]),n("checkbox-box",`
 background-color: var(--n-color-checked);
 border-left: 0;
 border-top: 0;
 `,[$("border",{border:"var(--n-border-checked)"})])]),M("disabled",{cursor:"not-allowed"},[M("checked",[n("checkbox-box",`
 background-color: var(--n-color-disabled-checked);
 `,[$("border",{border:"var(--n-border-disabled-checked)"}),n("checkbox-icon",[C(".check-icon, .line-icon",{fill:"var(--n-check-mark-color-disabled-checked)"})])])]),n("checkbox-box",`
 background-color: var(--n-color-disabled);
 `,[$("border",`
 border: var(--n-border-disabled);
 `),n("checkbox-icon",[C(".check-icon, .line-icon",`
 fill: var(--n-check-mark-color-disabled);
 `)])]),$("label",`
 color: var(--n-text-color-disabled);
 `)]),n("checkbox-box-wrapper",`
 position: relative;
 width: var(--n-size);
 flex-shrink: 0;
 flex-grow: 0;
 user-select: none;
 -webkit-user-select: none;
 `),n("checkbox-box",`
 position: absolute;
 left: 0;
 top: 50%;
 transform: translateY(-50%);
 height: var(--n-size);
 width: var(--n-size);
 display: inline-block;
 box-sizing: border-box;
 border-radius: var(--n-border-radius);
 background-color: var(--n-color);
 transition: background-color 0.3s var(--n-bezier);
 `,[$("border",`
 transition:
 border-color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 border-radius: inherit;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border: var(--n-border);
 `),n("checkbox-icon",`
 display: flex;
 align-items: center;
 justify-content: center;
 position: absolute;
 left: 1px;
 right: 1px;
 top: 1px;
 bottom: 1px;
 `,[C(".check-icon, .line-icon",`
 width: 100%;
 fill: var(--n-check-mark-color);
 opacity: 0;
 transform: scale(0.5);
 transform-origin: center;
 transition:
 fill 0.3s var(--n-bezier),
 transform 0.3s var(--n-bezier),
 opacity 0.3s var(--n-bezier),
 border-color 0.3s var(--n-bezier);
 `),ve({left:"1px",top:"1px"})])]),$("label",`
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 user-select: none;
 -webkit-user-select: none;
 padding: var(--n-label-padding);
 font-weight: var(--n-label-font-weight);
 `,[C("&:empty",{display:"none"})])]),ke(n("checkbox",`
 --n-merged-color-table: var(--n-color-table-modal);
 `)),xe(n("checkbox",`
 --n-merged-color-table: var(--n-color-table-popover);
 `))]),Be=Object.assign(Object.assign({},G.props),{size:String,checked:{type:[Boolean,String,Number],default:void 0},defaultChecked:{type:[Boolean,String,Number],default:!1},value:[String,Number],disabled:{type:Boolean,default:void 0},indeterminate:Boolean,label:String,focusable:{type:Boolean,default:!0},checkedValue:{type:[Boolean,String,Number],default:!0},uncheckedValue:{type:[Boolean,String,Number],default:!1},"onUpdate:checked":[Function,Array],onUpdateChecked:[Function,Array],privateInsideTable:Boolean,onChange:[Function,Array]}),He=j({name:"Checkbox",props:Be,setup(o){const c=Re(O,null),u=H(null),{mergedClsPrefixRef:y,inlineThemeDisabled:S,mergedRtlRef:f,mergedComponentPropsRef:v}=K(o),i=H(o.defaultChecked),k=U(o,"checked"),a=L(k,i),x=Ce(()=>{if(c){const e=c.valueSetRef.value;return e&&o.value!==void 0?e.has(o.value):!1}else return a.value===o.checkedValue}),t=E(o,{mergedSize(e){var g,p;const{size:R}=o;if(R!==void 0)return R;if(c){const{value:T}=c.mergedSizeRef;if(T!==void 0)return T}if(e){const{mergedSize:T}=e;if(T!==void 0)return T.value}const D=(p=(g=v?.value)===null||g===void 0?void 0:g.Checkbox)===null||p===void 0?void 0:p.size;return D||"medium"},mergedDisabled(e){const{disabled:g}=o;if(g!==void 0)return g;if(c){if(c.disabledRef.value)return!0;const{maxRef:{value:p},checkedCountRef:R}=c;if(p!==void 0&&R.value>=p&&!x.value)return!0;const{minRef:{value:D}}=c;if(D!==void 0&&R.value<=D&&x.value)return!0}return e?e.disabled.value:!1}}),{mergedDisabledRef:r,mergedSizeRef:m}=t,h=G("Checkbox","-checkbox",Ae,Te,o,y);function l(e){if(c&&o.value!==void 0)c.toggleCheckbox(!x.value,o.value);else{const{onChange:g,"onUpdate:checked":p,onUpdateChecked:R}=o,{nTriggerFormInput:D,nTriggerFormChange:T}=t,A=x.value?o.uncheckedValue:o.checkedValue;p&&d(p,A,e),R&&d(R,A,e),g&&d(g,A,e),D(),T(),i.value=A}}function z(e){r.value||l(e)}function w(e){if(!r.value)switch(e.key){case" ":case"Enter":l(e)}}function s(e){e.key===" "&&e.preventDefault()}const B={focus:()=>{var e;(e=u.value)===null||e===void 0||e.focus()},blur:()=>{var e;(e=u.value)===null||e===void 0||e.blur()}},P=ye("Checkbox",f,y),_=I(()=>{const{value:e}=m,{common:{cubicBezierEaseInOut:g},self:{borderRadius:p,color:R,colorChecked:D,colorDisabled:T,colorTableHeader:A,colorTableHeaderModal:V,colorTableHeaderPopover:W,checkMarkColor:q,checkMarkColorDisabled:J,border:Y,borderFocus:Q,borderDisabled:X,borderChecked:Z,boxShadowFocus:ee,textColor:oe,textColorDisabled:re,checkMarkColorDisabledChecked:ae,colorDisabledChecked:ne,borderDisabledChecked:ce,labelPadding:le,labelLineHeight:ie,labelFontWeight:de,[N("fontSize",e)]:te,[N("size",e)]:se}}=h.value;return{"--n-label-line-height":ie,"--n-label-font-weight":de,"--n-size":se,"--n-bezier":g,"--n-border-radius":p,"--n-border":Y,"--n-border-checked":Z,"--n-border-focus":Q,"--n-border-disabled":X,"--n-border-disabled-checked":ce,"--n-box-shadow-focus":ee,"--n-color":R,"--n-color-checked":D,"--n-color-table":A,"--n-color-table-modal":V,"--n-color-table-popover":W,"--n-color-disabled":T,"--n-color-disabled-checked":ne,"--n-text-color":oe,"--n-text-color-disabled":re,"--n-check-mark-color":q,"--n-check-mark-color-disabled":J,"--n-check-mark-color-disabled-checked":ae,"--n-font-size":te,"--n-label-padding":le}}),F=S?ze("checkbox",I(()=>m.value[0]),_,o):void 0;return Object.assign(t,B,{rtlEnabled:P,selfRef:u,mergedClsPrefix:y,mergedDisabled:r,renderedChecked:x,mergedTheme:h,labelId:we(),handleClick:z,handleKeyUp:w,handleKeyDown:s,cssVars:S?void 0:_,themeClass:F?.themeClass,onRender:F?.onRender})},render(){var o;const{$slots:c,renderedChecked:u,mergedDisabled:y,indeterminate:S,privateInsideTable:f,cssVars:v,labelId:i,label:k,mergedClsPrefix:a,focusable:x,handleKeyUp:t,handleKeyDown:r,handleClick:m}=this;(o=this.onRender)===null||o===void 0||o.call(this);const h=me(c.default,l=>k||l?b("span",{class:`${a}-checkbox__label`,id:i},k||l):null);return b("div",{ref:"selfRef",class:[`${a}-checkbox`,this.themeClass,this.rtlEnabled&&`${a}-checkbox--rtl`,u&&`${a}-checkbox--checked`,y&&`${a}-checkbox--disabled`,S&&`${a}-checkbox--indeterminate`,f&&`${a}-checkbox--inside-table`,h&&`${a}-checkbox--show-label`],tabindex:y||!x?void 0:0,role:"checkbox","aria-checked":S?"mixed":u,"aria-labelledby":i,style:v,onKeyup:t,onKeydown:r,onClick:m,onMousedown:()=>{pe("selectstart",window,l=>{l.preventDefault()},{once:!0})}},b("div",{class:`${a}-checkbox-box-wrapper`}," ",b("div",{class:`${a}-checkbox-box`},b(ge,null,{default:()=>this.indeterminate?b("div",{key:"indeterminate",class:`${a}-checkbox-icon`},Fe()):b("div",{key:"check",class:`${a}-checkbox-icon`},Me())}),b("div",{class:`${a}-checkbox-box__border`}))),h)}});export{He as N,Pe as a,Te as c};
