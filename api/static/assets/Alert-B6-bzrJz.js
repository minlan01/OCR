import{v as O,be as v,af as u,x as m,A as i,y as P,aA as F,z as N,d as V,p as l,aT as D,b2 as K,I as q,H as G,aC as J,C as Q,D as $,W as U,L as X,k as H,a5 as Y,bM as Z,a6 as oo,bN as eo,bO as ro,r as no,bC as so,M as c}from"./index-BG2_UJxV.js";const lo={iconMargin:"11px 8px 0 12px",iconMarginRtl:"11px 12px 0 8px",iconSize:"24px",closeIconSize:"16px",closeSize:"20px",closeMargin:"13px 14px 0 0",closeMarginRtl:"13px 0 0 14px",padding:"13px"};function to(r){const{lineHeight:o,borderRadius:d,fontWeightStrong:f,baseColor:t,dividerColor:C,actionColor:T,textColor1:g,textColor2:s,closeColorHover:h,closeColorPressed:b,closeIconColor:p,closeIconColorHover:x,closeIconColorPressed:n,infoColor:e,successColor:I,warningColor:z,errorColor:S,fontSize:y}=r;return Object.assign(Object.assign({},lo),{fontSize:y,lineHeight:o,titleFontWeight:f,borderRadius:d,border:`1px solid ${C}`,color:T,titleTextColor:g,iconColor:s,contentTextColor:s,closeBorderRadius:d,closeColorHover:h,closeColorPressed:b,closeIconColor:p,closeIconColorHover:x,closeIconColorPressed:n,borderInfo:`1px solid ${v(t,u(e,{alpha:.25}))}`,colorInfo:v(t,u(e,{alpha:.08})),titleTextColorInfo:g,iconColorInfo:e,contentTextColorInfo:s,closeColorHoverInfo:h,closeColorPressedInfo:b,closeIconColorInfo:p,closeIconColorHoverInfo:x,closeIconColorPressedInfo:n,borderSuccess:`1px solid ${v(t,u(I,{alpha:.25}))}`,colorSuccess:v(t,u(I,{alpha:.08})),titleTextColorSuccess:g,iconColorSuccess:I,contentTextColorSuccess:s,closeColorHoverSuccess:h,closeColorPressedSuccess:b,closeIconColorSuccess:p,closeIconColorHoverSuccess:x,closeIconColorPressedSuccess:n,borderWarning:`1px solid ${v(t,u(z,{alpha:.33}))}`,colorWarning:v(t,u(z,{alpha:.08})),titleTextColorWarning:g,iconColorWarning:z,contentTextColorWarning:s,closeColorHoverWarning:h,closeColorPressedWarning:b,closeIconColorWarning:p,closeIconColorHoverWarning:x,closeIconColorPressedWarning:n,borderError:`1px solid ${v(t,u(S,{alpha:.25}))}`,colorError:v(t,u(S,{alpha:.08})),titleTextColorError:g,iconColorError:S,contentTextColorError:s,closeColorHoverError:h,closeColorPressedError:b,closeIconColorError:p,closeIconColorHoverError:x,closeIconColorPressedError:n})}const io={common:O,self:to},ao=m("alert",`
 line-height: var(--n-line-height);
 border-radius: var(--n-border-radius);
 position: relative;
 transition: background-color .3s var(--n-bezier);
 background-color: var(--n-color);
 text-align: start;
 word-break: break-word;
`,[i("border",`
 border-radius: inherit;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 transition: border-color .3s var(--n-bezier);
 border: var(--n-border);
 pointer-events: none;
 `),P("closable",[m("alert-body",[i("title",`
 padding-right: 24px;
 `)])]),i("icon",{color:"var(--n-icon-color)"}),m("alert-body",{padding:"var(--n-padding)"},[i("title",{color:"var(--n-title-text-color)"}),i("content",{color:"var(--n-content-text-color)"})]),F({originalTransition:"transform .3s var(--n-bezier)",enterToProps:{transform:"scale(1)"},leaveToProps:{transform:"scale(0.9)"}}),i("icon",`
 position: absolute;
 left: 0;
 top: 0;
 align-items: center;
 justify-content: center;
 display: flex;
 width: var(--n-icon-size);
 height: var(--n-icon-size);
 font-size: var(--n-icon-size);
 margin: var(--n-icon-margin);
 `),i("close",`
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 position: absolute;
 right: 0;
 top: 0;
 margin: var(--n-close-margin);
 `),P("show-icon",[m("alert-body",{paddingLeft:"calc(var(--n-icon-margin-left) + var(--n-icon-size) + var(--n-icon-margin-right))"})]),P("right-adjust",[m("alert-body",{paddingRight:"calc(var(--n-close-size) + var(--n-padding) + 2px)"})]),m("alert-body",`
 border-radius: var(--n-border-radius);
 transition: border-color .3s var(--n-bezier);
 `,[i("title",`
 transition: color .3s var(--n-bezier);
 font-size: 16px;
 line-height: 19px;
 font-weight: var(--n-title-font-weight);
 `,[N("& +",[i("content",{marginTop:"9px"})])]),i("content",{transition:"color .3s var(--n-bezier)",fontSize:"var(--n-font-size)"})]),i("icon",{transition:"color .3s var(--n-bezier)"})]),co=Object.assign(Object.assign({},$.props),{title:String,showIcon:{type:Boolean,default:!0},type:{type:String,default:"default"},bordered:{type:Boolean,default:!0},closable:Boolean,onClose:Function,onAfterLeave:Function,onAfterHide:Function}),ho=V({name:"Alert",inheritAttrs:!1,props:co,slots:Object,setup(r){const{mergedClsPrefixRef:o,mergedBorderedRef:d,inlineThemeDisabled:f,mergedRtlRef:t}=Q(r),C=$("Alert","-alert",ao,io,r,o),T=U("Alert",t,o),g=H(()=>{const{common:{cubicBezierEaseInOut:n},self:e}=C.value,{fontSize:I,borderRadius:z,titleFontWeight:S,lineHeight:y,iconSize:E,iconMargin:R,iconMarginRtl:A,closeIconSize:W,closeBorderRadius:w,closeSize:B,closeMargin:M,closeMarginRtl:_,padding:k}=e,{type:a}=r,{left:L,right:j}=so(R);return{"--n-bezier":n,"--n-color":e[c("color",a)],"--n-close-icon-size":W,"--n-close-border-radius":w,"--n-close-color-hover":e[c("closeColorHover",a)],"--n-close-color-pressed":e[c("closeColorPressed",a)],"--n-close-icon-color":e[c("closeIconColor",a)],"--n-close-icon-color-hover":e[c("closeIconColorHover",a)],"--n-close-icon-color-pressed":e[c("closeIconColorPressed",a)],"--n-icon-color":e[c("iconColor",a)],"--n-border":e[c("border",a)],"--n-title-text-color":e[c("titleTextColor",a)],"--n-content-text-color":e[c("contentTextColor",a)],"--n-line-height":y,"--n-border-radius":z,"--n-font-size":I,"--n-title-font-weight":S,"--n-icon-size":E,"--n-icon-margin":R,"--n-icon-margin-rtl":A,"--n-close-size":B,"--n-close-margin":M,"--n-close-margin-rtl":_,"--n-padding":k,"--n-icon-margin-left":L,"--n-icon-margin-right":j}}),s=f?X("alert",H(()=>r.type[0]),g,r):void 0,h=no(!0),b=()=>{const{onAfterLeave:n,onAfterHide:e}=r;n&&n(),e&&e()};return{rtlEnabled:T,mergedClsPrefix:o,mergedBordered:d,visible:h,handleCloseClick:()=>{var n;Promise.resolve((n=r.onClose)===null||n===void 0?void 0:n.call(r)).then(e=>{e!==!1&&(h.value=!1)})},handleAfterLeave:()=>{b()},mergedTheme:C,cssVars:f?void 0:g,themeClass:s?.themeClass,onRender:s?.onRender}},render(){var r;return(r=this.onRender)===null||r===void 0||r.call(this),l(J,{onAfterLeave:this.handleAfterLeave},{default:()=>{const{mergedClsPrefix:o,$slots:d}=this,f={class:[`${o}-alert`,this.themeClass,this.closable&&`${o}-alert--closable`,this.showIcon&&`${o}-alert--show-icon`,!this.title&&this.closable&&`${o}-alert--right-adjust`,this.rtlEnabled&&`${o}-alert--rtl`],style:this.cssVars,role:"alert"};return this.visible?l("div",Object.assign({},D(this.$attrs,f)),this.closable&&l(K,{clsPrefix:o,class:`${o}-alert__close`,onClick:this.handleCloseClick}),this.bordered&&l("div",{class:`${o}-alert__border`}),this.showIcon&&l("div",{class:`${o}-alert__icon`,"aria-hidden":"true"},q(d.icon,()=>[l(Y,{clsPrefix:o},{default:()=>{switch(this.type){case"success":return l(ro,null);case"info":return l(eo,null);case"warning":return l(oo,null);case"error":return l(Z,null);default:return null}}})])),l("div",{class:[`${o}-alert-body`,this.mergedBordered&&`${o}-alert-body--bordered`]},G(d.header,t=>{const C=t||this.title;return C?l("div",{class:`${o}-alert-body__title`},C):null}),d.default&&l("div",{class:`${o}-alert-body__content`},d))):null}})}});export{ho as N};
