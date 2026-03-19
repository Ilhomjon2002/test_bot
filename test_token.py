# test_token.py
import asyncio
from telegram import Bot

async def test_token():
    # YANGI TOKENNI BU YERGA QO'YING
    NEW_TOKEN = "8158654510:AAF2S_0EqqIXJe8bg8z7XZ4aV9UVFyZGp54"  # @BotFather dan olingan yangi token
    
    bot = Bot(token=NEW_TOKEN)
    
    try:
        # Bot ma'lumotlarini olish
        me = await bot.get_me()
        print(f"✅ Bot connected successfully!")
        print(f"Bot name: {me.first_name}")
        print(f"Bot username: @{me.username}")
        print(f"Bot ID: {me.id}")
        
        # Webhook holatini tekshirish
        webhook_info = await bot.get_webhook_info()
        print(f"\n📡 Webhook info:")
        print(f"   URL: {webhook_info.url}")
        print(f"   Pending updates: {webhook_info.pending_update_count}")
        
        if webhook_info.url:
            print("\n⚠️ Webhook mavjud, o'chirilmoqda...")
            await bot.delete_webhook(drop_pending_updates=True)
            print("✅ Webhook o'chirildi")
        
        return True, me.username
        
    except Exception as e:
        print(f"❌ Xato: {e}")
        return False, None

if __name__ == "__main__":
    success, username = asyncio.run(test_token())
    if success:
        print(f"\n🚀 Bot @{username} tayyor!")