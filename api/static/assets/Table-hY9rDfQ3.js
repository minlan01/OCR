import{v as N,be as t,z as o,x as C,y as v,aj as _,bf as D,bg as F,d as I,p as K,C as q,D as z,W as A,L as G,k as f,M as x}from"./index-BG2_UJxV.js";const J={thPaddingSmall:"6px",thPaddingMedium:"12px",thPaddingLarge:"12px",tdPaddingSmall:"6px",tdPaddingMedium:"12px",tdPaddingLarge:"12px"};function Q(e){const{dividerColor:r,cardColor:a,modalColor:s,popoverColor:l,tableHeaderColor:b,tableColorStriped:c,textColor1:h,textColor2:g,borderRadius:n,fontWeightStrong:d,lineHeight:i,fontSizeSmall:p,fontSizeMedium:m,fontSizeLarge:u}=e;return Object.assign(Object.assign({},J),{fontSizeSmall:p,fontSizeMedium:m,fontSizeLarge:u,lineHeight:i,borderRadius:n,borderColor:t(a,r),borderColorModal:t(s,r),borderColorPopover:t(l,r),tdColor:a,tdColorModal:s,tdColorPopover:l,tdColorStriped:t(a,c),tdColorStripedModal:t(s,c),tdColorStripedPopover:t(l,c),thColor:t(a,b),thColorModal:t(s,b),thColorPopover:t(l,b),thTextColor:h,tdTextColor:g,thFontWeight:d})}const U={common:N,self:Q},X=o([C("table",`
 font-size: var(--n-font-size);
 font-variant-numeric: tabular-nums;
 line-height: var(--n-line-height);
 width: 100%;
 border-radius: var(--n-border-radius) var(--n-border-radius) 0 0;
 text-align: left;
 border-collapse: separate;
 border-spacing: 0;
 overflow: hidden;
 background-color: var(--n-td-color);
 border-color: var(--n-merged-border-color);
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 --n-merged-border-color: var(--n-border-color);
 `,[o("th",`
 white-space: nowrap;
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 text-align: inherit;
 padding: var(--n-th-padding);
 vertical-align: inherit;
 text-transform: none;
 border: 0px solid var(--n-merged-border-color);
 font-weight: var(--n-th-font-weight);
 color: var(--n-th-text-color);
 background-color: var(--n-th-color);
 border-bottom: 1px solid var(--n-merged-border-color);
 border-right: 1px solid var(--n-merged-border-color);
 `,[o("&:last-child",`
 border-right: 0px solid var(--n-merged-border-color);
 `)]),o("td",`
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 padding: var(--n-td-padding);
 color: var(--n-td-text-color);
 background-color: var(--n-td-color);
 border: 0px solid var(--n-merged-border-color);
 border-right: 1px solid var(--n-merged-border-color);
 border-bottom: 1px solid var(--n-merged-border-color);
 `,[o("&:last-child",`
 border-right: 0px solid var(--n-merged-border-color);
 `)]),v("bordered",`
 border: 1px solid var(--n-merged-border-color);
 border-radius: var(--n-border-radius);
 `,[o("tr",[o("&:last-child",[o("td",`
 border-bottom: 0 solid var(--n-merged-border-color);
 `)])])]),v("single-line",[o("th",`
 border-right: 0px solid var(--n-merged-border-color);
 `),o("td",`
 border-right: 0px solid var(--n-merged-border-color);
 `)]),v("single-column",[o("tr",[o("&:not(:last-child)",[o("td",`
 border-bottom: 0px solid var(--n-merged-border-color);
 `)])])]),v("striped",[o("tr:nth-of-type(even)",[o("td","background-color: var(--n-td-color-striped)")])]),_("bottom-bordered",[o("tr",[o("&:last-child",[o("td",`
 border-bottom: 0px solid var(--n-merged-border-color);
 `)])])])]),D(C("table",`
 background-color: var(--n-td-color-modal);
 --n-merged-border-color: var(--n-border-color-modal);
 `,[o("th",`
 background-color: var(--n-th-color-modal);
 `),o("td",`
 background-color: var(--n-td-color-modal);
 `)])),F(C("table",`
 background-color: var(--n-td-color-popover);
 --n-merged-border-color: var(--n-border-color-popover);
 `,[o("th",`
 background-color: var(--n-th-color-popover);
 `),o("td",`
 background-color: var(--n-td-color-popover);
 `)]))]),Y=Object.assign(Object.assign({},z.props),{bordered:{type:Boolean,default:!0},bottomBordered:{type:Boolean,default:!0},singleLine:{type:Boolean,default:!0},striped:Boolean,singleColumn:Boolean,size:String}),oo=I({name:"Table",props:Y,setup(e){const{mergedClsPrefixRef:r,inlineThemeDisabled:a,mergedRtlRef:s,mergedComponentPropsRef:l}=q(e),b=f(()=>{var d,i;return e.size||((i=(d=l?.value)===null||d===void 0?void 0:d.Table)===null||i===void 0?void 0:i.size)||"medium"}),c=z("Table","-table",X,U,e,r),h=A("Table",s,r),g=f(()=>{const d=b.value,{self:{borderColor:i,tdColor:p,tdColorModal:m,tdColorPopover:u,thColor:P,thColorModal:S,thColorPopover:M,thTextColor:k,tdTextColor:R,borderRadius:T,thFontWeight:B,lineHeight:y,borderColorModal:$,borderColorPopover:w,tdColorStriped:L,tdColorStripedModal:j,tdColorStripedPopover:O,[x("fontSize",d)]:E,[x("tdPadding",d)]:H,[x("thPadding",d)]:V},common:{cubicBezierEaseInOut:W}}=c.value;return{"--n-bezier":W,"--n-td-color":p,"--n-td-color-modal":m,"--n-td-color-popover":u,"--n-td-text-color":R,"--n-border-color":i,"--n-border-color-modal":$,"--n-border-color-popover":w,"--n-border-radius":T,"--n-font-size":E,"--n-th-color":P,"--n-th-color-modal":S,"--n-th-color-popover":M,"--n-th-font-weight":B,"--n-th-text-color":k,"--n-line-height":y,"--n-td-padding":H,"--n-th-padding":V,"--n-td-color-striped":L,"--n-td-color-striped-modal":j,"--n-td-color-striped-popover":O}}),n=a?G("table",f(()=>b.value[0]),g,e):void 0;return{rtlEnabled:h,mergedClsPrefix:r,cssVars:a?void 0:g,themeClass:n?.themeClass,onRender:n?.onRender}},render(){var e;const{mergedClsPrefix:r}=this;return(e=this.onRender)===null||e===void 0||e.call(this),K("table",{class:[`${r}-table`,this.themeClass,{[`${r}-table--rtl`]:this.rtlEnabled,[`${r}-table--bottom-bordered`]:this.bottomBordered,[`${r}-table--bordered`]:this.bordered,[`${r}-table--single-line`]:this.singleLine,[`${r}-table--single-column`]:this.singleColumn,[`${r}-table--striped`]:this.striped}],style:this.cssVars},this.$slots)}});export{oo as N};
