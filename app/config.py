from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    openai_api_key: str
    retell_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    stripe_secret_key: str
    stripe_webhook_secret: str = ""
    clerk_secret_key: str
    app_url: str = "https://shopdesk-ai.vercel.app"

    class Config:
        env_file = ".env"

settings = Settings()
