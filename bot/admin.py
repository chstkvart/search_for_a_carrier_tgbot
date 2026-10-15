from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.actions import delete_selected

from .carriers import CARRIERS
from .models import BotText, CalculationRequest, CarrierConfig
from .texts import DEFAULT_TEXTS

admin.site.site_header = 'Управление ботом'
admin.site.site_title = 'Управление ботом'
admin.site.index_title = 'Настройки'


class BuiltinFilter(admin.SimpleListFilter):
    title = 'тип'
    parameter_name = 'kind'
    field = ''

    def lookups(self, request, model_admin):
        return [('builtin', 'Встроенные'), ('custom', 'Добавленные')]

    def queryset(self, request, queryset):
        if self.value() == 'builtin':
            return queryset.filter(**{f'{self.field}__isnull': False})
        if self.value() == 'custom':
            return queryset.filter(**{f'{self.field}__isnull': True})
        return queryset


class BuiltinTextFilter(BuiltinFilter):
    field = 'key'


class BuiltinCarrierFilter(BuiltinFilter):
    field = 'code'


def delete_custom_selected(modeladmin, request, queryset):
    builtin = queryset.filter(**{f'{modeladmin.builtin_field}__isnull': False}).count()
    if builtin and not request.POST.get('post'):
        modeladmin.message_user(request, f'Встроенные записи не удаляются (пропущено: {builtin}). '
                                         'Их можно выключить или изменить.', messages.WARNING)
    custom = queryset.filter(**{f'{modeladmin.builtin_field}__isnull': True})
    if not custom.exists():
        return None
    return delete_selected(modeladmin, request, custom)


class ProtectBuiltinMixin:
    """Встроенные записи нужны коду бота: их можно менять, но не удалять."""

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_builtin:
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            actions['delete_selected'] = (
                delete_custom_selected, 'delete_selected', 'Удалить выбранные (только добавленные)',
            )
        return actions


@admin.register(CalculationRequest)
class CalculationRequestAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'username', 'telegram_id', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('username', 'telegram_id')
    readonly_fields = ('created_at', 'telegram_id', 'username', 'params', 'results')


@admin.register(BotText)
class BotTextAdmin(ProtectBuiltinMixin, admin.ModelAdmin):
    builtin_field = 'key'
    list_display = ('title', 'kind', 'place', 'enabled', 'position', 'short_text')
    list_editable = ('position',)
    list_filter = (BuiltinTextFilter, 'place')
    search_fields = ('title', 'text')

    def get_fields(self, request, obj=None):
        if obj and obj.is_builtin:
            return ('title', 'text', 'default_text', 'position')
        return ('title', 'place', 'text', 'enabled', 'position')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_builtin:
            return ('title', 'default_text')
        return ()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not (obj and obj.is_builtin):
            form.base_fields['place'].required = True
            form.base_fields['text'].required = True
        return form

    @admin.display(description='Тип')
    def kind(self, obj):
        return 'встроенный' if obj.is_builtin else 'добавленный'

    @admin.display(description='Текст')
    def short_text(self, obj):
        text = obj.text or DEFAULT_TEXTS.get(obj.key, ('', ''))[1]
        return text if len(text) <= 80 else text[:79] + '…'

    @admin.display(description='Текст по умолчанию')
    def default_text(self, obj):
        return DEFAULT_TEXTS.get(obj.key, ('', ''))[1]


class CarrierConfigForm(forms.ModelForm):
    class Meta:
        model = CarrierConfig
        fields = '__all__'
        widgets = {'secret': forms.PasswordInput(render_value=True)}


@admin.register(CarrierConfig)
class CarrierConfigAdmin(ProtectBuiltinMixin, admin.ModelAdmin):
    builtin_field = 'code'
    form = CarrierConfigForm
    list_display = ('name', 'kind', 'enabled', 'position', 'status')
    list_editable = ('enabled', 'position')
    list_filter = (BuiltinCarrierFilter, 'enabled')

    def get_fields(self, request, obj=None):
        if obj and obj.is_builtin:
            carrier = self._carrier(obj)
            fields = ['name', 'enabled', 'position', 'contacts']
            if carrier and carrier.login_setting:
                fields.append('login')
            if carrier and carrier.secret_setting:
                fields.append('secret')
            return fields
        return ('name', 'enabled', 'position', 'supports_avia', 'contacts')

    @staticmethod
    def _carrier(obj):
        return next((c for c in CARRIERS if c.code == obj.code), None)

    @admin.display(description='Тип')
    def kind(self, obj):
        return 'встроенная (API)' if obj.is_builtin else 'добавленная'

    @admin.display(description='Подключение')
    def status(self, obj):
        carrier = self._carrier(obj) if obj.is_builtin else None
        if carrier is None:
            return 'без онлайн-расчёта, показываются контакты'
        if not (carrier.login_setting or carrier.secret_setting):
            return 'ключ не нужен'
        has_secret = obj.secret or getattr(settings, carrier.secret_setting, '')
        has_login = not carrier.login_setting or obj.login or getattr(settings, carrier.login_setting, '')
        return 'ключ задан' if has_secret and has_login else 'нет ключа'
