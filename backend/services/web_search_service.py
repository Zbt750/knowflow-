"""Optional external search boundary. No configured provider means no network claim."""
from dataclasses import dataclass,field
from datetime import datetime,timezone
from urllib.parse import urlsplit
from ipaddress import ip_address

@dataclass
class WebSearchOutcome:
    available:bool
    sources:list[dict]=field(default_factory=list)
    reason:str|None=None

def search_web(query,*,provider=None,timeout=8,enabled=True):
    if not enabled:return WebSearchOutcome(False,reason="disabled")
    if provider is None:return WebSearchOutcome(False,reason="provider_not_configured")
    try:
        results=provider.search(query,timeout=timeout)
        sources=[]
        for row in results[:5]:
            url=str(row.get("url",""));parts=urlsplit(url)
            if parts.scheme not in {"http","https"} or not parts.hostname or parts.username or parts.password:continue
            if parts.hostname.lower() in {"localhost","localhost.localdomain"}:continue
            try:
                if not ip_address(parts.hostname).is_global:continue
            except ValueError:pass
            sources.append({"title":str(row.get("title",""))[:200],"url":url,"snippet":str(row.get("snippet",""))[:1200],
                "retrieved_at":datetime.now(timezone.utc).isoformat()})
        return WebSearchOutcome(bool(sources),sources,reason=None if sources else "no_valid_sources")
    except (TimeoutError,ConnectionError,OSError):return WebSearchOutcome(False,reason="search_unavailable")
