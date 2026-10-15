from django.db import models


class CalculationRequest(models.Model):
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    telegram_id = models.BigIntegerField('Telegram ID', db_index=True)
    username = models.CharField('Username', max_length=64, blank=True)
    params = models.JSONField('Параметры груза')
    results = models.JSONField('Результаты')

    class Meta:
        verbose_name = 'Расчёт'
        verbose_name_plural = 'Расчёты'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.params.get("from_city")} → {self.params.get("to_city")} ({self.created_at:%d.%m.%Y %H:%M})'


class BotText(models.Model):
    PLACE_AFTER_WELCOME = 'after_welcome'
    PLACE_BEFORE_RESULTS = 'before_results'
    PLACE_AFTER_RESULTS = 'after_results'
    PLACES = [
        (PLACE_AFTER_WELCOME, 'После приветствия'),
        (PLACE_BEFORE_RESULTS, 'Перед результатами расчёта'),
        (PLACE_AFTER_RESULTS, 'После результатов расчёта'),
    ]

    key = models.CharField('Код', max_length=64, unique=True, null=True, blank=True, editable=False)
    title = models.CharField('Название', max_length=200)
    place = models.CharField(
        'Где показывать', max_length=32, choices=PLACES, blank=True,
        help_text='Только для добавленных вами сообщений.',
    )
    text = models.TextField(
        'Текст', blank=True,
        help_text='У встроенных текстов пустое поле возвращает текст по умолчанию. '
                  'Слова в фигурных скобках, например {city}, бот заменит сам — не удаляйте их.',
    )
    enabled = models.BooleanField('Показывать', default=True, help_text='Только для добавленных вами сообщений.')
    position = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Текст бота'
        verbose_name_plural = 'Тексты бота'
        ordering = ['position', 'id']

    def __str__(self):
        return self.title

    @property
    def is_builtin(self) -> bool:
        return bool(self.key)


class CarrierConfig(models.Model):
    code = models.CharField('Код', max_length=32, unique=True, null=True, blank=True, editable=False)
    name = models.CharField('Название в боте', max_length=100)
    enabled = models.BooleanField('Включена', default=True)
    position = models.PositiveIntegerField('Порядок', default=0)
    supports_avia = models.BooleanField(
        'Есть авиадоставка', default=False,
        help_text='Только для добавленных вами компаний: показывать ли её при выборе авиадоставки.',
    )
    contacts = models.CharField(
        'Контакты', max_length=255, blank=True,
        help_text='Телефон, сайт — показываются вместо расчёта, если у компании нет онлайн-расчёта.',
    )
    login = models.CharField(
        'Логин / ID клиента', max_length=255, blank=True,
        help_text='СДЭК — Client ID, DPD — номер клиента. Пусто — берётся из файла .env.',
    )
    secret = models.CharField(
        'Ключ API', max_length=255, blank=True,
        help_text='СДЭК — Client Secret, DPD — ключ, Деловые Линии — appkey, Байкал — API-ключ, '
                  'КИТ — токен. Пусто — берётся из файла .env.',
    )

    class Meta:
        verbose_name = 'Транспортная компания'
        verbose_name_plural = 'Транспортные компании'
        ordering = ['position', 'id']

    def __str__(self):
        return self.name

    @property
    def is_builtin(self) -> bool:
        return bool(self.code)
