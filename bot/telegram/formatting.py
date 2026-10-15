from html import escape

from ..carriers.base import Quote
from ..services import SearchResult
from ..texts import MESSAGE_LIMIT, t


def money(value: float) -> str:
    text = f'{value:,.2f}'.replace(',', ' ').replace('.', ',')
    return (text[:-3] if text.endswith(',00') else text) + ' ₽'


def quote_block(position: int, quote: Quote) -> str:
    total = f'💰 Общая стоимость: <b>{money(quote.total)}</b>'
    missing = ', '.join(quote.missing)
    if missing:
        total += f' ({t("total_without", items=missing)})'
    lines = [
        f'<b>{position}. {escape(quote.carrier)}</b>' + (f' — {escape(quote.tariff)}' if quote.tariff else ''),
        f'⏱ Ориентировочный срок: {quote.days_text}',
        total,
    ]
    if quote.items:
        lines.append('Из чего состоит цена:')
        lines += [f'  • {escape(item.name)} — {money(item.price)}' for item in quote.items]
    if missing:
        lines.append(f'<b>{t("missing_line", items=missing)}</b>')
    if quote.note:
        lines.append(f'<i>{escape(quote.note)}</i>')
    return '\n'.join(lines)


def results_messages(result: SearchResult) -> list[str]:
    blocks = []
    complete = [q for q in result.quotes if q.is_complete]
    partial = [q for q in result.quotes if not q.is_complete]
    if complete:
        blocks.append(f'<b>{t("results_header")}</b>')
        blocks += [quote_block(i, q) for i, q in enumerate(complete, 1)]
    if partial:
        blocks.append(f'<b>{t("results_partial_header")}</b>')
        blocks += [quote_block(i, q) for i, q in enumerate(partial, len(complete) + 1)]
    if not result.quotes:
        blocks.append(t('no_results'))
    if result.failures:
        blocks.append(f'<b>{t("failures_header")}</b>\n' + '\n'.join(
            f'  • {escape(name)}: {escape(reason)}' for name, reason in result.failures
        ))
    if result.not_configured:
        blocks.append('<i>Не подключены (нет ключа API): ' + escape(', '.join(result.not_configured)) + '</i>')

    messages, current = [], ''
    for block in blocks:
        if current and len(current) + len(block) + 2 > MESSAGE_LIMIT:
            messages.append(current)
            current = ''
        current = f'{current}\n\n{block}' if current else block
    if current:
        messages.append(current)
    return messages
