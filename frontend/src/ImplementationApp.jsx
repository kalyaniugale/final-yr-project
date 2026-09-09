import React,{useState} from "react";
import {LayoutDashboard,Layers,MapPin,BarChart3,FileText,Menu,X,Building2,ChevronRight} from "lucide-react";
import RecommendationPage from "./components/RecommendationPage.jsx";
import {OverviewPage,ZoneRegistryPage,AnalysisPage,ReviewPage} from "./pages/ImplementationPages.jsx";
import "./ImplementationApp.css";
const NAV=[{id:"overview",title:"Overview",icon:LayoutDashboard},{id:"zones",title:"Zone registry",icon:Layers},{id:"recommend",title:"Recommendations",icon:MapPin},{id:"analysis",title:"GIS & model insights",icon:BarChart3},{id:"review",title:"Expert review",icon:FileText}];
export default function ImplementationApp(){
 const [page,setPage]=useState("overview"),[mobileOpen,setMobileOpen]=useState(false),[requestedDivision,setRequestedDivision]=useState("");
 const navigate=id=>{setPage(id);setMobileOpen(false);};
 const openZone=division=>{setRequestedDivision(division==="Citywide"?"":division);navigate("recommend");};
 const current=NAV.find(x=>x.id===page);
 return <div className="implementation-shell"><aside className={`implementation-sidebar ${mobileOpen?"mobile-open":""}`}>
   <div className="brand"><div className="brand-mark"><Building2 size={22}/></div><div><strong>Nashik</strong><span>Vendor Management</span></div><button className="mobile-close" onClick={()=>setMobileOpen(false)} aria-label="Close menu"><X size={19}/></button></div>
   <div className="sidebar-section-label">WORKSPACE</div><nav className="implementation-nav" aria-label="Main navigation">{NAV.map(x=><button key={x.id} className={page===x.id?"active":""} onClick={()=>navigate(x.id)}><x.icon size={18}/><span>{x.title}</span>{page===x.id&&<ChevronRight size={15} className="nav-arrow"/>}</button>)}</nav>
   <div className="sidebar-bottom"><div className="sidebar-bottom-label">PROJECT STATUS</div><strong>Decision-support platform</strong><p>GIS · K-Means · MCDA</p><span>Research implementation</span></div>
 </aside>
 {mobileOpen&&<button className="sidebar-backdrop" onClick={()=>setMobileOpen(false)} aria-label="Close navigation"/>}
 <div className="implementation-content"><header className="implementation-topbar"><button className="mobile-menu" onClick={()=>setMobileOpen(true)} aria-label="Open navigation"><Menu size={20}/></button><div className="topbar-breadcrumb">Workspace <ChevronRight size={13}/> <strong>{current?.title}</strong></div><div className="topbar-right"><span className="topbar-dot"/> Nashik Municipal Corporation <span className="topbar-avatar">N</span></div></header>
 <div className="implementation-view">{page==="overview"&&<OverviewPage navigate={navigate}/>}
 {page==="zones"&&<ZoneRegistryPage openZone={openZone}/>}
 {page==="recommend"&&<RecommendationPage key={requestedDivision||"default"} initialDivision={requestedDivision}/>}
 {page==="analysis"&&<AnalysisPage/>}
 {page==="review"&&<ReviewPage/>}</div>
 </div></div>;
}
