import asyncio

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bot.services import ensure_admin_defaults, refresh_admin_settings
from bot.telegram.handlers import router


class AdminSettingsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        await refresh_admin_settings()
        return await handler(event, data)


class Command(BaseCommand):
    help = 'Запускает Telegram-бота (long polling)'

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError('Не задан TELEGRAM_BOT_TOKEN в файле .env')
        ensure_admin_defaults()
        asyncio.run(self._run())

    async def _run(self):
        await refresh_admin_settings(force=True)
        bot = Bot(settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher(storage=MemoryStorage())
        dp.update.outer_middleware(AdminSettingsMiddleware())
        dp.include_router(router)
        await bot.set_my_commands([
            BotCommand(command='new', description='Новый расчёт перевозки'),
        ])
        me = await bot.get_me()
        self.stdout.write(self.style.SUCCESS(f'Бот @{me.username} запущен. Остановить: Ctrl+C'))
        try:
            await dp.start_polling(bot)
        finally:
            await bot.session.close()
