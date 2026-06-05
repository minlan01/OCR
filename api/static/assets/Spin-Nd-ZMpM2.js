import{d as b,p as r,v as L,x as v,A as h,z,a5 as H,C as R,D as g,L as w,k as p,M as x,ah as V,y as S,b7 as E,an as I,az as _,r as O,bW as P,b8 as j,bi as k}from"./index-BG2_UJxV.js";import{k as B}from"./client-Cq57ZeqF.js";const D=b({name:"Empty",render(){return r("svg",{viewBox:"0 0 28 28",fill:"none",xmlns:"http://www.w3.org/2000/svg"},r("path",{d:"M26 7.5C26 11.0899 23.0899 14 19.5 14C15.9101 14 13 11.0899 13 7.5C13 3.91015 15.9101 1 19.5 1C23.0899 1 26 3.91015 26 7.5ZM16.8536 4.14645C16.6583 3.95118 16.3417 3.95118 16.1464 4.14645C15.9512 4.34171 15.9512 4.65829 16.1464 4.85355L18.7929 7.5L16.1464 10.1464C15.9512 10.3417 15.9512 10.6583 16.1464 10.8536C16.3417 11.0488 16.6583 11.0488 16.8536 10.8536L19.5 8.20711L22.1464 10.8536C22.3417 11.0488 22.6583 11.0488 22.8536 10.8536C23.0488 10.6583 23.0488 10.3417 22.8536 10.1464L20.2071 7.5L22.8536 4.85355C23.0488 4.65829 23.0488 4.34171 22.8536 4.14645C22.6583 3.95118 22.3417 3.95118 22.1464 4.14645L19.5 6.79289L16.8536 4.14645Z",fill:"currentColor"}),r("path",{d:"M25 22.75V12.5991C24.5572 13.0765 24.053 13.4961 23.5 13.8454V16H17.5L17.3982 16.0068C17.0322 16.0565 16.75 16.3703 16.75 16.75C16.75 18.2688 15.5188 19.5 14 19.5C12.4812 19.5 11.25 18.2688 11.25 16.75L11.2432 16.6482C11.1935 16.2822 10.8797 16 10.5 16H4.5V7.25C4.5 6.2835 5.2835 5.5 6.25 5.5H12.2696C12.4146 4.97463 12.6153 4.47237 12.865 4H6.25C4.45507 4 3 5.45507 3 7.25V22.75C3 24.5449 4.45507 26 6.25 26H21.75C23.5449 26 25 24.5449 25 22.75ZM4.5 22.75V17.5H9.81597L9.85751 17.7041C10.2905 19.5919 11.9808 21 14 21L14.215 20.9947C16.2095 20.8953 17.842 19.4209 18.184 17.5H23.5V22.75C23.5 23.7165 22.7165 24.5 21.75 24.5H6.25C5.2835 24.5 4.5 23.7165 4.5 22.75Z",fill:"currentColor"}))}}),M={iconSizeTiny:"28px",iconSizeSmall:"34px",iconSizeMedium:"40px",iconSizeLarge:"46px",iconSizeHuge:"52px"};function N(e){const{textColorDisabled:i,iconColor:n,textColor2:t,fontSizeTiny:u,fontSizeSmall:a,fontSizeMedium:m,fontSizeLarge:c,fontSizeHuge:s}=e;return Object.assign(Object.assign({},M),{fontSizeTiny:u,fontSizeSmall:a,fontSizeMedium:m,fontSizeLarge:c,fontSizeHuge:s,textColor:i,iconColor:n,extraTextColor:t})}const W={name:"Empty",common:L,self:N},Z=v("empty",`
 display: flex;
 flex-direction: column;
 align-items: center;
 font-size: var(--n-font-size);
`,[h("icon",`
 width: var(--n-icon-size);
 height: var(--n-icon-size);
 font-size: var(--n-icon-size);
 line-height: var(--n-icon-size);
 color: var(--n-icon-color);
 transition:
 color .3s var(--n-bezier);
 `,[z("+",[h("description",`
 margin-top: 8px;
 `)])]),h("description",`
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
 `),h("extra",`
 text-align: center;
 transition: color .3s var(--n-bezier);
 margin-top: 12px;
 color: var(--n-extra-text-color);
 `)]),K=Object.assign(Object.assign({},g.props),{description:String,showDescription:{type:Boolean,default:!0},showIcon:{type:Boolean,default:!0},size:{type:String,default:"medium"},renderIcon:Function}),Q=b({name:"Empty",props:K,slots:Object,setup(e){const{mergedClsPrefixRef:i,inlineThemeDisabled:n,mergedComponentPropsRef:t}=R(e),u=g("Empty","-empty",Z,W,e,i),{localeRef:a}=B("Empty"),m=p(()=>{var o,d,f;return(o=e.description)!==null&&o!==void 0?o:(f=(d=t?.value)===null||d===void 0?void 0:d.Empty)===null||f===void 0?void 0:f.description}),c=p(()=>{var o,d;return((d=(o=t?.value)===null||o===void 0?void 0:o.Empty)===null||d===void 0?void 0:d.renderIcon)||(()=>r(D,null))}),s=p(()=>{const{size:o}=e,{common:{cubicBezierEaseInOut:d},self:{[x("iconSize",o)]:f,[x("fontSize",o)]:y,textColor:C,iconColor:$,extraTextColor:T}}=u.value;return{"--n-icon-size":f,"--n-font-size":y,"--n-bezier":d,"--n-text-color":C,"--n-icon-color":$,"--n-extra-text-color":T}}),l=n?w("empty",p(()=>{let o="";const{size:d}=e;return o+=d[0],o}),s,e):void 0;return{mergedClsPrefix:i,mergedRenderIcon:c,localizedDescription:p(()=>m.value||a.value.description),cssVars:n?void 0:s,themeClass:l?.themeClass,onRender:l?.onRender}},render(){const{$slots:e,mergedClsPrefix:i,onRender:n}=this;return n?.(),r("div",{class:[`${i}-empty`,this.themeClass],style:this.cssVars},this.showIcon?r("div",{class:`${i}-empty__icon`},e.icon?e.icon():r(H,{clsPrefix:i},{default:this.mergedRenderIcon})):null,this.showDescription?r("div",{class:`${i}-empty__description`},e.default?e.default():this.localizedDescription):null,e.extra?r("div",{class:`${i}-empty__extra`},e.extra()):null)}});function A(e){const{opacityDisabled:i,heightTiny:n,heightSmall:t,heightMedium:u,heightLarge:a,heightHuge:m,primaryColor:c,fontSize:s}=e;return{fontSize:s,textColor:c,sizeTiny:n,sizeSmall:t,sizeMedium:u,sizeLarge:a,sizeHuge:m,color:c,opacitySpinning:i}}const F={common:L,self:A},X=z([z("@keyframes spin-rotate",`
 from {
 transform: rotate(0);
 }
 to {
 transform: rotate(360deg);
 }
 `),v("spin-container",`
 position: relative;
 `,[v("spin-body",`
 position: absolute;
 top: 50%;
 left: 50%;
 transform: translateX(-50%) translateY(-50%);
 `,[V()])]),v("spin-body",`
 display: inline-flex;
 align-items: center;
 justify-content: center;
 flex-direction: column;
 `),v("spin",`
 display: inline-flex;
 height: var(--n-size);
 width: var(--n-size);
 font-size: var(--n-size);
 color: var(--n-color);
 `,[S("rotate",`
 animation: spin-rotate 2s linear infinite;
 `)]),v("spin-description",`
 display: inline-block;
 font-size: var(--n-font-size);
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 margin-top: 8px;
 `),v("spin-content",`
 opacity: 1;
 transition: opacity .3s var(--n-bezier);
 pointer-events: all;
 `,[S("spinning",`
 user-select: none;
 -webkit-user-select: none;
 pointer-events: none;
 opacity: var(--n-opacity-spinning);
 `)])]),Y={small:20,medium:18,large:16},q=Object.assign(Object.assign(Object.assign({},g.props),{contentClass:String,contentStyle:[Object,String],description:String,size:{type:[String,Number],default:"medium"},show:{type:Boolean,default:!0},rotate:{type:Boolean,default:!0},spinning:{type:Boolean,validator:()=>!0,default:void 0},delay:Number}),P),U=b({name:"Spin",props:q,slots:Object,setup(e){const{mergedClsPrefixRef:i,inlineThemeDisabled:n}=R(e),t=g("Spin","-spin",X,F,e,i),u=p(()=>{const{size:s}=e,{common:{cubicBezierEaseInOut:l},self:o}=t.value,{opacitySpinning:d,color:f,textColor:y}=o,C=typeof s=="number"?j(s):o[x("size",s)];return{"--n-bezier":l,"--n-opacity-spinning":d,"--n-size":C,"--n-color":f,"--n-text-color":y}}),a=n?w("spin",p(()=>{const{size:s}=e;return typeof s=="number"?String(s):s[0]}),u,e):void 0,m=k(e,["spinning","show"]),c=O(!1);return _(s=>{let l;if(m.value){const{delay:o}=e;if(o){l=window.setTimeout(()=>{c.value=!0},o),s(()=>{clearTimeout(l)});return}}c.value=m.value}),{mergedClsPrefix:i,active:c,mergedStrokeWidth:p(()=>{const{strokeWidth:s}=e;if(s!==void 0)return s;const{size:l}=e;return Y[typeof l=="number"?"medium":l]}),cssVars:n?void 0:u,themeClass:a?.themeClass,onRender:a?.onRender}},render(){var e,i;const{$slots:n,mergedClsPrefix:t,description:u}=this,a=n.icon&&this.rotate,m=(u||n.description)&&r("div",{class:`${t}-spin-description`},u||((e=n.description)===null||e===void 0?void 0:e.call(n))),c=n.icon?r("div",{class:[`${t}-spin-body`,this.themeClass]},r("div",{class:[`${t}-spin`,a&&`${t}-spin--rotate`],style:n.default?"":this.cssVars},n.icon()),m):r("div",{class:[`${t}-spin-body`,this.themeClass]},r(E,{clsPrefix:t,style:n.default?"":this.cssVars,stroke:this.stroke,"stroke-width":this.mergedStrokeWidth,radius:this.radius,scale:this.scale,class:`${t}-spin`}),m);return(i=this.onRender)===null||i===void 0||i.call(this),n.default?r("div",{class:[`${t}-spin-container`,this.themeClass],style:this.cssVars},r("div",{class:[`${t}-spin-content`,this.active&&`${t}-spin-content--spinning`,this.contentClass],style:this.contentStyle},n),r(I,{name:"fade-in-transition"},{default:()=>this.active?c:null})):c}});export{Q as N,U as a,W as e};
