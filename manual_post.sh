#!/bin/bash
# Manually trigger the bot to post the next verse
docker exec qurantwitterbot-bot-1 python -c "from bot import post_verse; post_verse()"
