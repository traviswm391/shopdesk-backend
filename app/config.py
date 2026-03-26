from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str  # From Supabase: Settings -> API -> JWT Secret
    openai_api_key: str
    retell_api_key: str = ""
    elevenlabs_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    stripe_secret_key: str
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    clerk_secret_key: str = ""
    clerk_webhook_secret: str = ""
    app_url: str = "https://shopdesk-ai.vercel.app"
    backend_url: str = "https://shopdesk-backend-production.up.railway.app"

    class Config:
        env_file = ".env"


settings = Settings()
