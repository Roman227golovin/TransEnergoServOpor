"""
Python-версия mobile/lib/models/pole_field_shema.dart + pole_reference.dart.

Нужна веб-интерфейсу, чтобы показывать человекочитаемые подписи и применять те же
условия видимости/редактирования, что и в мобильном приложении. Схема дублируется
намеренно (Dart и Python не делят код) — при изменении полей на телефоне такие же
изменения нужно вносить и здесь.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional

@dataclass
class FieldDef:
    key: str
    label: str
    type: str  # text, integer, real, year, date, dropdown, multiselect, computed
    options: Optional[List[str]] = None
    options_for: Optional[Callable[[dict], List[str]]] = None
    enabled_when: Optional[Callable[[dict], bool]] = None
    compute: Optional[Callable[[dict], str]] = None


STOYKA_OPTIONS = [
    'ЖБК', 'УЖБК', 'СЖБК', 'СК', 'СКУ', 'СКЦ', 'СКЦо', 'СО', 'СС', 'СТ', 'СТА', 'С', 'ССА', 'ССП', 'ГК', 'СКМ (СКА)', 'СП',
    'СД', 'СДУ', 'СБД', 'ЖБД',
    'М', 'МН', 'МК', 'МП', 'МШ', 'МШП', 'МШК', 'МГК', 'МГП', 'МГТ', 'МЛК', 'МТК', 'МЛП', 'МТП', 'ОК', 'ОП',
    'нет',
]

FUNDAMENT_OPTIONS = [
    'ТСП', 'ТСС', 'ТСА', 'ТСАР', 'ДС', 'ТС', 'ТСН', 'ФКА', 'СТО', 'С', 'ФС',
    'ФТП', 'ФСТП', 'ФТ', 'ФСТ', 'К', 'АК', 'П', 'ПА', 'Р', 'СВ', 'СВП', 'СВТ',
    'нет',
]

PURPOSE_OPTIONS = [
    'Анкерная', 'Фиксирующая', 'Промежуточная', 'Переходная',
    'Опора жёсткой поперечины', 'Опора гибкой поперечины', 'Тоннель',
    'Анкерная + фиксирующая', 'Анкерная + опора жёсткой поперечины',
    'Анкерная + опора гибкой поперечины', 'Фидерная', 'Мост', 'Средней анкеровки',
]

SOIL_OPTIONS = [
    'Песок', 'Супесок', 'Суглинок', 'Глина', 'Садовая земля',
    'Чернозем', 'Торф', 'Каменистая глина', 'Скала и валуны', 'Известняк и мергель',
]

DEFECT_SEVERITY_OPTIONS = [
    'без снижения несущей способности',
    'со снижением несущей способности',
    'со значительным снижением несущей способности',
    'с предельным снижением несущей способности, ежегодный контроль',
    'остродефектная',
    'нет',
]

DEFECT_ITEMS = [
    ('1', ['Ц', 'Д', 'М', 'Ф']),
    ('2', ['Ц', 'Д', 'М', 'Ф']),
    ('3', ['Ц', 'Д', 'Ф']),
    ('3.1', ['М']),
    ('3.2', ['М']),
    ('4', ['Ц', 'Д', 'М', 'Ф']),
    ('5', ['Ц', 'Д', 'Ф']),
    ('5.1', ['М']),
    ('5.2', ['М']),
    ('5.3', ['М']),
    ('5.4', ['М']),
    ('6', ['Ц', 'Д', 'Ф']),
    ('6.1', ['М']),
    ('6.2', ['М']),
    ('7', ['Ц', 'Д', 'М', 'Ф']),
    ('8', ['Ц', 'Д']),
    ('8.1', ['М']),
    ('8.2', ['М']),
    ('8.3', ['М']),
    ('9', ['М']),
    ('10', ['М']),
]

def _any_defect_selected(data: dict, part: str) -> bool:
    return any(data.get(f'defect_{key}_{part}') for key, _ in DEFECT_ITEMS)

def has_any_defects(data: dict) -> bool:
    """Использует и enabled_when поля defect_card, и генератор карточки (defect_card.py)."""
    return _any_defect_selected(data, 'above') or _any_defect_selected(data, 'below')

def _defect_has_material(data: dict, part: str, material: str) -> bool:
    for key, _ in DEFECT_ITEMS:
        raw = str(data.get(f'defect_{key}_{part}') or '')
        if material in raw.split(','):
            return True
    return False

def _filter_defect_options(options: List[str], data: dict) -> List[str]:
    """Марка/тип стойки уже определяет материал опоры (is_metal_pole) — металлические
    опоры отмечаются только по М (и всегда по Ф), железобетонные — только по Ц/Д
    (и всегда по Ф). Пункт, которого нет среди options этого дефекта, просто не
    появится — свойство пустого множества, а не отдельная проверка."""
    allowed = {'М', 'Ф'} if is_metal_pole(data.get('pole_mark')) else {'Ц', 'Д', 'Ф'}
    return [o for o in options if o in allowed]

def _generate_defect_fields(part: str) -> List[FieldDef]:
    prefix = 'Н' if part == 'above' else 'П'
    return [
        FieldDef(
            key=f'defect_{key}_{part}', label=f'{prefix}{key}', type='multiselect', options=options,
            options_for=lambda d, opts=options: _filter_defect_options(opts, d),
            # Если для текущего материала опоры у этого пункта не осталось ни одного
            # применимого варианта (например, чисто металлические 3.1/9/10 и т.п. на
            # железобетонной опоре) — сам пункт скрывается целиком, отмечать нечего.
            enabled_when=lambda d, opts=options: bool(_filter_defect_options(opts, d)),
        )
        for key, options in DEFECT_ITEMS
    ]

def _compute_p2(data: dict, part: str) -> str:
    try:
        g = float(str(data.get(f'p1g_{part}', '')).replace(',', '.'))
        v = float(str(data.get(f'p1v_{part}', '')).replace(',', '.'))
    except (TypeError, ValueError):
        return ''
    if g == 0:
        return ''
    return f'{v / g:.3f}'

def _generate_part_fields(part: str) -> List[FieldDef]:
    part_label = 'надземная' if part == 'above' else 'подземная'
    return [
        FieldDef(key=f'inspection_date_{part}', label=f'Дата обследования ({part_label})', type='date'),
        FieldDef(key=f'inspector_name_{part}', label=f'Ф.И.О ({part_label} часть)', type='text'),
        FieldDef(
            key=f'p1g_{part}', label=f'П1г max, мкс ({part_label})', type='real',
            enabled_when=lambda d: _defect_has_material(d, part, 'Ц'),
        ),
        FieldDef(
            key=f'p1v_{part}', label=f'П1в max, мкс ({part_label})', type='real',
            enabled_when=lambda d: _defect_has_material(d, part, 'Ц'),
        ),
        FieldDef(
            key=f'p2_{part}', label=f'П2 max, мкс ({part_label})', type='computed',
            enabled_when=lambda d: _defect_has_material(d, part, 'Ц'),
            compute=lambda d: _compute_p2(d, part),
        ),
        FieldDef(
            key=f'ultrasound_speed_{part}', label=f'Скорость ультразвука, м/с ({part_label})', type='real',
            enabled_when=lambda d: _defect_has_material(d, part, 'Д') or _defect_has_material(d, part, 'Ф'),
        ),
        FieldDef(
            key=f'defect_conclusion_{part}', label=f'Заключение о степени дефектности ({part_label})',
            type='dropdown', options=DEFECT_SEVERITY_OPTIONS,
            enabled_when=lambda d: _any_defect_selected(d, part),
        ),
        FieldDef(key=f'defect_description_{part}', label=f'Описание дефектов ({part_label})', type='text'),
    ]

def _worse_of(a, b) -> str:
    order = DEFECT_SEVERITY_OPTIONS[:5]

    def rank(v):
        if not v:
            return -1
        return order.index(v) if v in order else -1

    return (a or '') if rank(a) >= rank(b) else (b or '')

def _replacement_deadline(purpose) -> str:
    # Поддержки/жёсткие и гибкие поперечины проверяются раньше анкерных, так как
    # назначение может быть комбинированным ("Анкерная + опора жёсткой поперечины").
    value = purpose or ''
    if 'жёсткой поперечины' in value or 'гибкой поперечины' in value:
        return '1 год'
    if 'Анкерная' in value:
        return '1 месяц'
    return '3 месяца'

_PROTECTION_DEVICES = ['ИПМ', 'ГРПЗ', 'УК', 'ДЗ']

FIELDS: List[FieldDef] = [
    FieldDef('directorate', 'Дирекция по энергообеспечению', 'text'),
    FieldDef('distance', 'Дистанция электроснабжения', 'text'),
    FieldDef('ks_region', 'Район контактной сети', 'text'),
    FieldDef('station', 'Станция, Перегон', 'text'),
    FieldDef('line_class', 'Класс линии', 'dropdown', options=['1', '2', '3', '4', '5']),
    FieldDef('km', 'км', 'integer'),
    FieldDef('pk', 'ПК', 'integer'),
    FieldDef('m', 'м', 'integer'),
    FieldDef('track_number', '№ пути', 'integer'),
    FieldDef('current_type', 'Род тока', 'dropdown', options=['постоянный', 'переменный']),

    FieldDef('soil_type', 'Краткая характеристика почвы', 'dropdown', options=SOIL_OPTIONS),
    FieldDef('os6_name', 'Наименование объекта в ОС-6', 'text'),
    FieldDef('os_inventory_number', 'Инвентарный номер объекта ОС', 'text'),

    FieldDef('pole_number', '№ опоры', 'integer'),
    FieldDef('pole_index', 'индекс номера', 'text'),
    FieldDef('purpose', 'Назначение', 'dropdown', options=PURPOSE_OPTIONS),
    FieldDef('pole_mark', 'Марка, тип стойки', 'dropdown', options=STOYKA_OPTIONS),
    FieldDef('pole_height', 'высота стойки', 'dropdown', options=['100', '120', '136', '150', '200']),
    FieldDef('foundation_mark', 'Марка, тип фундамента/анкера', 'dropdown', options=FUNDAMENT_OPTIONS),
    FieldDef('foundation_length', 'Длина фундамента', 'dropdown', options=['3', '4', '4,5', '5', '6']),
    FieldDef('foundation_diameter', 'Диаметр (для винтовых свай)', 'dropdown', options=['325', '351']),
    FieldDef('install_year', 'Год установки', 'year'),
    FieldDef('dismantle_date', 'Год демонтажа (архив)', 'date'),

    *_generate_defect_fields('above'),
    *_generate_part_fields('above'),
    *_generate_defect_fields('below'),
    *_generate_part_fields('below'),

    FieldDef('avg_positive_potential', 'Средний положительный потенциал, В', 'real', enabled_when=lambda d: d.get('current_type') == 'постоянный'),
    FieldDef('avg_negative_potential', 'Средний отрицательный потенциал, В', 'real', enabled_when=lambda d: d.get('current_type') == 'постоянный'),
    FieldDef('potential_zone', 'Потенциальная зона', 'dropdown', options=['катодная', 'анодная', 'знакопеременная'], enabled_when=lambda d: d.get('current_type') == 'постоянный'),
    FieldDef('potential_measure_date', 'Дата измерения потенциалов', 'date'),
    FieldDef('potential_measure_inspector', 'Ф.И.О (измерение потенциалов)', 'text'),
    FieldDef('r_before_prev', 'R, кОм (пред-предпоследнее)', 'real'),
    FieldDef('r_before_prev_date', 'Дата измерения пред-предпоследнего R, кОм', 'date'),
    FieldDef('r_before_prev_inspector', 'Ф.И.О (пред-предпоследнее измерение R)', 'text'),
    FieldDef('r_prev', 'R, кОм (предпоследнее)', 'real'),
    FieldDef('r_prev_date', 'Дата предпоследнего измерения R', 'date'),
    FieldDef('r_prev_inspector', 'Ф.И.О (предпоследнее измерение R)', 'text'),
    FieldDef('r_current', 'R, кОм (последнее)', 'real'),
    FieldDef('r_current_date', 'Дата измерения последнего R', 'date'),
    FieldDef('r_current_inspector', 'Ф.И.О (последнее измерение R)', 'text'),
    FieldDef('leak_current', 'Ток утечки, mI', 'real'),
    FieldDef('corrosion_danger', 'Опасность электрокоррозии', 'dropdown', options=['да', 'нет']),

    FieldDef('grounding_type', 'Тип заземления', 'dropdown', options=['индивидуальное', 'групповое']),
    FieldDef('descent_pole_number', '№ опоры со спуском', 'integer', enabled_when=lambda d: d.get('grounding_type') == 'групповое'),
    FieldDef('descent_pole_index', 'индекс № опоры со спуском', 'text', enabled_when=lambda d: d.get('grounding_type') == 'групповое'),
    FieldDef('protection_device', 'Наличие защитного устройства', 'dropdown', options=['НЕТ', 'ИПМ', 'ГРПЗ', 'УК', 'ДЗ']),
    FieldDef('protection_install_date', 'Дата установки защитного устройства', 'date', enabled_when=lambda d: d.get('protection_device') in _PROTECTION_DEVICES),
    FieldDef('rail_connection', 'Подключение спуска к рельсовой цепи', 'dropdown', options=['ДТ', 'КС-107', 'УКЗ', 'ПРК', 'Контур']),
    FieldDef('protection_check_date', 'Дата проверки защитного прибора', 'date', enabled_when=lambda d: d.get('protection_device') in _PROTECTION_DEVICES),

    FieldDef('incline_field', 'Наклон в поле/на путь, %', 'real'),
    FieldDef('incline_track', 'Наклон вдоль пути, %', 'real'),
    FieldDef('gabarit', 'Габарит опоры, м', 'real'),
    FieldDef('gabarit_second_track', 'Габарит опоры к второму пути', 'dropdown', options=['да', 'нет']),
    FieldDef('lezhen', 'Наличие лежня/стяжки', 'dropdown', options=['лежень', 'стяжка', 'нет']),
    FieldDef('incline_measure_date', 'Дата измерения', 'date'),
    FieldDef('incline_measure_inspector', 'Ф.И.О (измерение наклона)', 'text'),
    FieldDef('has_dynamics', 'Наличие динамики', 'dropdown', options=['да', 'нет']),
    FieldDef('can_correct', 'Возможность выправки', 'dropdown', options=['да', 'нет']),

    FieldDef(
        'final_conclusion', 'Итоговое заключение о степени дефектности конструкции', 'computed',
        compute=lambda d: _worse_of(d.get('defect_conclusion_above'), d.get('defect_conclusion_below')),
    ),
    FieldDef(
        'defect_card', 'Дефектная карточка (xlsx)', 'file',
        enabled_when=has_any_defects,
    ),
    FieldDef(
        'safety_tie', 'Наличие страхующей стяжки (фото/ссылка)', 'text',
        enabled_when=lambda d: d.get('final_conclusion') == 'остродефектная',
    ),
    FieldDef(
        'pole_replacement_deadline', 'Срок замены опоры', 'computed',
        enabled_when=lambda d: d.get('final_conclusion') == 'остродефектная',
        compute=lambda d: _replacement_deadline(d.get('purpose')),
    ),

    FieldDef('next_check_year_above', 'Год очередной проверки надземной части', 'text'),
    FieldDef('next_check_year_below', 'Год очередной проверки подземной части', 'text'),
    FieldDef('next_check_year_r', 'Год очередной проверки R', 'text'),
    FieldDef('month', 'Месяц', 'text'),
    FieldDef('measure', 'Мероприятие', 'dropdown', options=['замена', 'ремонт', 'установка ЗУ', 'выправка']),
    FieldDef('measure_deadline', 'Срок выполнения мероприятий', 'date'),
    FieldDef('measure_done', 'Факт выполнения мероприятий', 'text'),
    FieldDef('ipm_check_date', 'Дата проверки ИПМ', 'date'),

    FieldDef('inspector_name', 'Ф.И.О', 'text'),
]

# Совпадает с RolePermissions._restrictedFields на телефоне: всё от начала списка
# до "dismantle_date" включительно недоступно для редактирования ролям ECh/EChK.
_ALL_KEYS = [f.key for f in FIELDS]
_RESTRICTED_CUTOFF = _ALL_KEYS.index('dismantle_date')
RESTRICTED_FIELDS = set(_ALL_KEYS[:_RESTRICTED_CUTOFF + 1])

def can_edit_field(role: str, field_key: str) -> bool:
    if role in ('TE', 'NTE'):
        return True
    if role in ('ECh', 'EChK'):
        return field_key not in RESTRICTED_FIELDS
    return False

def is_dismantled(data: dict) -> bool:
    return bool(str(data.get('dismantle_date') or '').strip())

def is_metal_pole(pole_mark) -> bool:
    """Для планирования диагностики: марка/тип стойки, начинающаяся на М, либо сама
    марка ОК или ОП (это не префикс — если появятся другие марки, начинающиеся на
    ОК/ОП, но не являющиеся ими самими, они не должны попасть в металлические)."""
    mark = str(pole_mark or '').strip().upper()
    result = mark.startswith(('М')) or mark in ("ОК", "ОП")
    return result

def is_anchor(purpose) -> bool:
    """Для планирования диагностики: назначение, содержащее слово «анкер»
    (в т.ч. «Анкерная», «Средней анкеровки», «Анкерная + ...») — анкер, иначе опора."""
    return 'анкер' in str(purpose or '').strip().lower()

# Названия листов и ключ последнего поля на листе — сами поля идут в том же порядке,
# что и в FIELDS, разбиение только группирует их для отображения (совпадает с Dart).
SHEET_BOUNDARIES = [
    ('Паспорт', 'os_inventory_number'),
    ('Характеристика', 'dismantle_date'),
    ('Дефекты (надземная часть)', 'defect_description_above'),
    ('Дефекты (подземная часть)', 'defect_description_below'),
    ('Измерения', 'corrosion_danger'),
    ('Доп. характеристики', 'can_correct'),
    ('Итог', 'inspector_name'),
]

def sheets() -> List[tuple]:
    result = []
    remaining = list(FIELDS)
    for name, end_key in SHEET_BOUNDARIES:
        index = next(i for i, f in enumerate(remaining) if f.key == end_key)
        result.append((name, remaining[:index + 1]))
        remaining = remaining[index + 1:]
    return result
