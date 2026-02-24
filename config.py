from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    voyage_api_key: str = ""
    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./pressroom.db"
    scout_github_repos: list[str] = ["dreamfactorysoftware/dreamfactory"]
    scout_hn_keywords: list[str] = ["DreamFactory", "REST API", "API gateway"]
    scout_subreddits: list[str] = ["selfhosted", "webdev"]
    scout_rss_feeds: list[str] = []
    claude_model: str = "claude-sonnet-4-6"
    claude_model_fast: str = "claude-haiku-4-5-20251001"
    df_base_url: str = "http://localhost:8080"
    df_api_key: str = ""
    github_webhook_secret: str = ""
    # Social OAuth (Pressroom-owned apps)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    # Google OAuth (for GSC, YouTube, etc.)
    google_client_id: str = ""
    google_client_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
