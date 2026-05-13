"""X (Twitter) skills - burner account only.

TOS WARNING: Automation of X actions violates the X Terms of Service. Only
use a burner account you are willing to lose. Set conservative pacing in
config/policies.yaml -> social_pacing.x.

ROADMAP (via twikit):
  - x.login() -> session_cookie_path  (saves cookies to X_COOKIES_PATH)
  - x.follow(username) -> ok
  - x.like(tweet_url) -> ok
  - x.retweet(tweet_url) -> ok
  - x.post(text) -> tweet_url
  - x.reply(tweet_url, text) -> reply_url

Implementation notes:
  - Prefer cookie-based auth (X_COOKIES_PATH). Only fall back to password
    login on a clean session, and expect captcha.
  - Respect social_pacing: sleep(random.uniform(min, max)) between ops.
  - Set social=True so the agent loop applies pacing globally.
"""
