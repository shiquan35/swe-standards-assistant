from guard.models import SecurityConfig

from app.core.env import env

# Define your security configuration
security_config = SecurityConfig(
    # IP Management
    whitelist=[],  # Add trusted IPs like load balancers, monitoring systems
    blacklist=[],  # Add known malicious IPs
    # Geographic restrictions
    # blocked_countries=["CN", "RU", "KP"],  # Block high-risk countries if needed
    # User-Agent filtering
    blocked_user_agents=[
        "curl",
        "wget",
        "python-requests",
        "bot",
        "crawler",
        "scanner",
    ],  # Block automated tools and bots
    # Auto-ban configuration
    auto_ban_threshold=10,  # Increase threshold for production
    auto_ban_duration=3600,  # 1 hour ban (shorter than 24h for better UX)
    # Rate limiting (requests per minute)
    enable_penetration_detection=True
    if env.ENVIRONMENT == "production"
    else False,  # ! enable_penetration_detection will cause serious performance overhead
    enable_ip_banning=True if env.ENVIRONMENT == "production" else False,
    enable_rate_limiting=True if env.ENVIRONMENT == "production" else False,
    rate_limit=60,  # More conservative rate limit
    rate_limit_window=60,  # Specify time window
    # Security headers
    enforce_https=True if env.ENVIRONMENT == "production" else False,
    # CORS configuration
    enable_cors=True,
    cors_allow_origins=[
        "https://yourdomain.com",
    ]
    if env.ENVIRONMENT == "production"
    else ["*"],  # Restrict origins in production
    cors_allow_credentials=True if env.ENVIRONMENT == "production" else False,
    cors_allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    cors_allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "Accept",
        "Origin",
        "X-CSRF-Token",
    ],
    cors_expose_headers=["X-Process-Time", "X-Request-ID"],
    cors_max_age=86400,  # 24 hours cache for preflight
    # Cloud provider blocking (enable if you don't expect cloud traffic)
    # block_cloud_providers={"AWS", "GCP", "Azure", "DigitalOcean"},
    # Logging
    custom_log_file="logs/security.log"
    if env.ENVIRONMENT == "production"
    else None,  # Use logs directory
    enable_detailed_logging=False,  # Enable for better monitoring
)
