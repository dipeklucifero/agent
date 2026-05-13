"""Discord skills - bot-based only. Self-bots are ToS-banned; don't script them.

ROADMAP:
  - discord.send_message(channel_id, text) -> message_id
  - discord.react(channel_id, message_id, emoji) -> ok
  - discord.list_guilds() -> [ {id, name} ]
  - discord.fetch_invite_meta(invite_code) -> {guild_id, name, member_count}

For JOINING arbitrary guilds:
  Discord does not allow bots to self-join via invite codes. Workflow is:
    1. Use the website/mobile to paste the invite while logged in as you.
    2. Tell the agent 'I joined <guild_name>'; agent notes it and can now
       interact if you've also invited the bot with correct scopes.
  We do NOT script this step.

Implementation notes:
  - Use discord.py's Client with intents = Intents.default() + members.
  - Run the Discord client in a background task from main.py so it's alive
    for send_message calls.
"""
