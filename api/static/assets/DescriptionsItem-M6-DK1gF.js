import{v as H,be as C,z as h,x as e,aj as N,y as M,A as k,bf as W,bg as G,d as E,b3 as K,p as l,bh as q,b4 as J,C as Q,D as V,L as U,k as T,bi as X,M as I}from"./index-BG2_UJxV.js";function _(t,c="default",p=[]){const{children:i}=t;if(i!==null&&typeof i=="object"&&!Array.isArray(i)){const n=i[c];if(typeof n=="function")return n()}return p}const Y={thPaddingBorderedSmall:"8px 12px",thPaddingBorderedMedium:"12px 16px",thPaddingBorderedLarge:"16px 24px",thPaddingSmall:"0",thPaddingMedium:"0",thPaddingLarge:"0",tdPaddingBorderedSmall:"8px 12px",tdPaddingBorderedMedium:"12px 16px",tdPaddingBorderedLarge:"16px 24px",tdPaddingSmall:"0 0 8px 0",tdPaddingMedium:"0 0 12px 0",tdPaddingLarge:"0 0 16px 0"};function Z(t){const{tableHeaderColor:c,textColor2:p,textColor1:i,cardColor:n,modalColor:b,popoverColor:m,dividerColor:a,borderRadius:s,fontWeightStrong:d,lineHeight:S,fontSizeSmall:r,fontSizeMedium:v,fontSizeLarge:u}=t;return Object.assign(Object.assign({},Y),{lineHeight:S,fontSizeSmall:r,fontSizeMedium:v,fontSizeLarge:u,titleTextColor:i,thColor:C(n,c),thColorModal:C(b,c),thColorPopover:C(m,c),thTextColor:i,thFontWeight:d,tdTextColor:p,tdColor:n,tdColorModal:b,tdColorPopover:m,borderColor:C(n,a),borderColorModal:C(b,a),borderColorPopover:C(m,a),borderRadius:s})}const ee={common:H,self:Z},oe=h([e("descriptions",{fontSize:"var(--n-font-size)"},[e("descriptions-separator",`
 display: inline-block;
 margin: 0 8px 0 2px;
 `),e("descriptions-table-wrapper",[e("descriptions-table",[e("descriptions-table-row",[e("descriptions-table-header",{padding:"var(--n-th-padding)"}),e("descriptions-table-content",{padding:"var(--n-td-padding)"})])])]),N("bordered",[e("descriptions-table-wrapper",[e("descriptions-table",[e("descriptions-table-row",[h("&:last-child",[e("descriptions-table-content",{paddingBottom:0})])])])])]),M("left-label-placement",[e("descriptions-table-content",[h("> *",{verticalAlign:"top"})])]),M("left-label-align",[h("th",{textAlign:"left"})]),M("center-label-align",[h("th",{textAlign:"center"})]),M("right-label-align",[h("th",{textAlign:"right"})]),M("bordered",[e("descriptions-table-wrapper",`
 border-radius: var(--n-border-radius);
 overflow: hidden;
 background: var(--n-merged-td-color);
 border: 1px solid var(--n-merged-border-color);
 `,[e("descriptions-table",[e("descriptions-table-row",[h("&:not(:last-child)",[e("descriptions-table-content",{borderBottom:"1px solid var(--n-merged-border-color)"}),e("descriptions-table-header",{borderBottom:"1px solid var(--n-merged-border-color)"})]),e("descriptions-table-header",`
 font-weight: 400;
 background-clip: padding-box;
 background-color: var(--n-merged-th-color);
 `,[h("&:not(:last-child)",{borderRight:"1px solid var(--n-merged-border-color)"})]),e("descriptions-table-content",[h("&:not(:last-child)",{borderRight:"1px solid var(--n-merged-border-color)"})])])])])]),e("descriptions-header",`
 font-weight: var(--n-th-font-weight);
 font-size: 18px;
 transition: color .3s var(--n-bezier);
 line-height: var(--n-line-height);
 margin-bottom: 16px;
 color: var(--n-title-text-color);
 `),e("descriptions-table-wrapper",`
 transition:
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[e("descriptions-table",`
 width: 100%;
 border-collapse: separate;
 border-spacing: 0;
 box-sizing: border-box;
 `,[e("descriptions-table-row",`
 box-sizing: border-box;
 transition: border-color .3s var(--n-bezier);
 `,[e("descriptions-table-header",`
 font-weight: var(--n-th-font-weight);
 line-height: var(--n-line-height);
 display: table-cell;
 box-sizing: border-box;
 color: var(--n-th-text-color);
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `),e("descriptions-table-content",`
 vertical-align: top;
 line-height: var(--n-line-height);
 display: table-cell;
 box-sizing: border-box;
 color: var(--n-td-text-color);
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `,[k("content",`
 transition: color .3s var(--n-bezier);
 display: inline-block;
 color: var(--n-td-text-color);
 `)]),k("label",`
 font-weight: var(--n-th-font-weight);
 transition: color .3s var(--n-bezier);
 display: inline-block;
 margin-right: 14px;
 color: var(--n-th-text-color);
 `)])])])]),e("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color);
 --n-merged-td-color: var(--n-td-color);
 --n-merged-border-color: var(--n-border-color);
 `),W(e("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color-modal);
 --n-merged-td-color: var(--n-td-color-modal);
 --n-merged-border-color: var(--n-border-color-modal);
 `)),G(e("descriptions-table-wrapper",`
 --n-merged-th-color: var(--n-th-color-popover);
 --n-merged-td-color: var(--n-td-color-popover);
 --n-merged-border-color: var(--n-border-color-popover);
 `))]),F="DESCRIPTION_ITEM_FLAG";function re(t){return typeof t=="object"&&t&&!Array.isArray(t)?t.type&&t.type[F]:!1}const te=Object.assign(Object.assign({},V.props),{title:String,column:{type:Number,default:3},columns:Number,labelPlacement:{type:String,default:"top"},labelAlign:{type:String,default:"left"},separator:{type:String,default:":"},size:String,bordered:Boolean,labelClass:String,labelStyle:[Object,String],contentClass:String,contentStyle:[Object,String]}),ie=E({name:"Descriptions",props:te,slots:Object,setup(t){const{mergedClsPrefixRef:c,inlineThemeDisabled:p,mergedComponentPropsRef:i}=Q(t),n=T(()=>{var s,d;return t.size||((d=(s=i?.value)===null||s===void 0?void 0:s.Descriptions)===null||d===void 0?void 0:d.size)||"medium"}),b=V("Descriptions","-descriptions",oe,ee,t,c),m=T(()=>{const{bordered:s}=t,d=n.value,{common:{cubicBezierEaseInOut:S},self:{titleTextColor:r,thColor:v,thColorModal:u,thColorPopover:B,thTextColor:j,thFontWeight:D,tdTextColor:A,tdColor:o,tdColorModal:y,tdColorPopover:O,borderColor:g,borderColorModal:f,borderColorPopover:w,borderRadius:z,lineHeight:x,[I("fontSize",d)]:P,[I(s?"thPaddingBordered":"thPadding",d)]:$,[I(s?"tdPaddingBordered":"tdPadding",d)]:R}}=b.value;return{"--n-title-text-color":r,"--n-th-padding":$,"--n-td-padding":R,"--n-font-size":P,"--n-bezier":S,"--n-th-font-weight":D,"--n-line-height":x,"--n-th-text-color":j,"--n-td-text-color":A,"--n-th-color":v,"--n-th-color-modal":u,"--n-th-color-popover":B,"--n-td-color":o,"--n-td-color-modal":y,"--n-td-color-popover":O,"--n-border-radius":z,"--n-border-color":g,"--n-border-color-modal":f,"--n-border-color-popover":w}}),a=p?U("descriptions",T(()=>{let s="";const{bordered:d}=t;return d&&(s+="a"),s+=n.value[0],s}),m,t):void 0;return{mergedClsPrefix:c,cssVars:p?void 0:m,themeClass:a?.themeClass,onRender:a?.onRender,compitableColumn:X(t,["columns","column"]),inlineThemeDisabled:p,mergedSize:n}},render(){const t=this.$slots.default,c=t?K(t()):[];c.length;const{contentClass:p,labelClass:i,compitableColumn:n,labelPlacement:b,labelAlign:m,mergedSize:a,bordered:s,title:d,cssVars:S,mergedClsPrefix:r,separator:v,onRender:u}=this;u?.();const B=c.filter(o=>re(o)),j={span:0,row:[],secondRow:[],rows:[]},A=B.reduce((o,y,O)=>{const g=y.props||{},f=B.length-1===O,w=["label"in g?g.label:_(y,"label")],z=[_(y)],x=g.span||1,P=o.span;o.span+=x;const $=g.labelStyle||g["label-style"]||this.labelStyle,R=g.contentStyle||g["content-style"]||this.contentStyle;if(b==="left")s?o.row.push(l("th",{class:[`${r}-descriptions-table-header`,i],colspan:1,style:$},w),l("td",{class:[`${r}-descriptions-table-content`,p],colspan:f?(n-P)*2+1:x*2-1,style:R},z)):o.row.push(l("td",{class:`${r}-descriptions-table-content`,colspan:f?(n-P)*2:x*2},l("span",{class:[`${r}-descriptions-table-content__label`,i],style:$},[...w,v&&l("span",{class:`${r}-descriptions-separator`},v)]),l("span",{class:[`${r}-descriptions-table-content__content`,p],style:R},z)));else{const L=f?(n-P)*2:x*2;o.row.push(l("th",{class:[`${r}-descriptions-table-header`,i],colspan:L,style:$},w)),o.secondRow.push(l("td",{class:[`${r}-descriptions-table-content`,p],colspan:L,style:R},z))}return(o.span>=n||f)&&(o.span=0,o.row.length&&(o.rows.push(o.row),o.row=[]),b!=="left"&&o.secondRow.length&&(o.rows.push(o.secondRow),o.secondRow=[])),o},j).rows.map(o=>l("tr",{class:`${r}-descriptions-table-row`},o));return l("div",{style:S,class:[`${r}-descriptions`,this.themeClass,`${r}-descriptions--${b}-label-placement`,`${r}-descriptions--${m}-label-align`,`${r}-descriptions--${a}-size`,s&&`${r}-descriptions--bordered`]},d||this.$slots.header?l("div",{class:`${r}-descriptions-header`},d||J(this,"header")):null,l("div",{class:`${r}-descriptions-table-wrapper`},l("table",{class:`${r}-descriptions-table`},l("tbody",null,b==="top"&&l("tr",{class:`${r}-descriptions-table-row`,style:{visibility:"collapse"}},q(n*2,l("td",null))),A))))}}),ne={label:String,span:{type:Number,default:1},labelClass:String,labelStyle:[Object,String],contentClass:String,contentStyle:[Object,String]},se=E({name:"DescriptionsItem",[F]:!0,props:ne,slots:Object,render(){return null}});export{ie as N,se as a};
