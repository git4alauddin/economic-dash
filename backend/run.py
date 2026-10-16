"""Start the local development server from the backend directory."""

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "development",
        # Query strings can contain accidentally pasted credentials. No raw
        # request access log. Collector diagnostics remain structured/safe.
        access_log=False,
        # Ignore client-supplied Forwarded/X-Forwarded-* unless an operator
        # explicitly configures trusted peer IPs/CIDRs after the M7 host check.
        proxy_headers=bool(settings.trusted_proxy_ips),
        forwarded_allow_ips=",".join(settings.trusted_proxy_ips),
    )
