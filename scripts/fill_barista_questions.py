import asyncio
import os
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from bot.services.attestation_excel import (
    generate_attestation_template,
    parse_attestation_excel,
    _sanitize_sheet_title,
    FONT_TITLE,
    FONT_HEADER,
    FONT_DATA,
    FONT_BOLD,
    HEADER_FILL_GOLD,
    HEADER_FILL_DARK,
    HEADER_FILL_SUB,
    ZEBRA_FILL,
    BORDER_THIN
)
from database.attestation import save_questions_for_role, get_questions_for_role, get_questions_count_by_role
from database.positions import get_all_positions


BARISTA_QUESTIONS = [
    {
        "question_text": "Який стандартний час екстракції класичного одинарного/подвійного еспресо?",
        "option_1": "10-15 секунд",
        "option_2": "25-30 секунд",
        "option_3": "40-45 секунд",
        "option_4": "50-60 секунд",
        "correct_option": 2,
        "points": 1,
        "explanation": "Класичний стандарт екстракції еспресо становить 25–30 секунд. Менший час веде до недоекстракції (кислий смак), більший — до переекстракції (гіркота та палений присмак)."
    },
    {
        "question_text": "Якщо еспресо витікає за 15 секунд і має водянистий, надмірно кислий смак, які дії бариста є правильними?",
        "option_1": "Зробити помел дрібнішим (finer)",
        "option_2": "Зробити помел грубішим (coarser)",
        "option_3": "Зменшити тиск темперування",
        "option_4": "Збільшити температуру води в групі на 5°C",
        "correct_option": 1,
        "points": 2,
        "explanation": "Занадто швидка екстракція (15 с) свідчить про недоекстракцію через занадто великі фракції зерна або каналування. Потрібно зменшити фракцію помолу (зробити його дрібнішим)."
    },
    {
        "question_text": "Яка оптимальна температура збивання коров'ячого молока для капучино та лате?",
        "option_1": "40-45°C",
        "option_2": "60-65°C",
        "option_3": "75-80°C",
        "option_4": "90-95°C",
        "correct_option": 2,
        "points": 1,
        "explanation": "При температурі 60-65°C лактоза розкриває максимальну природну солодкість. При нагріванні вище 68-70°C білки денатурують, піна руйнується і з'являється неприємний присмак кип'яченого молока."
    },
    {
        "question_text": "Яка головна відмінність класичного напою Флет Вайт (Flat White) від Капучино?",
        "option_1": "Флет Вайт готується на одинарному еспресо з товстим шаром піни",
        "option_2": "Флет Вайт готується на подвійному еспресо (допіо) з тонким шаром гладкої мікропіни",
        "option_3": "Флет Вайт готується на розчинній каві зі збитими вершками",
        "option_4": "У Флет Вайт додається ванільний сироп та кориця за стандартом",
        "correct_option": 2,
        "points": 2,
        "explanation": "Флет Вайт базується на подвійній порції еспресо (допіо) та заливається молоком з мінімальним тонким глянцевим шаром мікропіни (близько 0.5 см), що дає насичений кавовий смак."
    },
    {
        "question_text": "Яка правильна технологія приготування класичного кавового напою Раф?",
        "option_1": "Еспресо змішується з окропом і зверху додається холодний молочний крем",
        "option_2": "Еспресо, вершки (10-15%) та ванільний цукор збиваються паровиком разом у пітчері",
        "option_3": "Шоколадний топінг заливається подвійним еспресо та молоком без збивання",
        "option_4": "Кава фільтр з додаванням вершкового масла та згущеного молока",
        "correct_option": 2,
        "points": 2,
        "explanation": "Особливість Раф-кави в тому, що порція еспресо, вершки (зазвичай 10-15%) та ванільний/звичайний цукор збиваються паровою трубкою разом безпосередньо в пітчері до однорідної шовковистої текстури."
    },
    {
        "question_text": "Що необхідно зробити з паровою трубкою (стімером/форсункою) ДО та ПІСЛЯ збивання молока?",
        "option_1": "Нічого, достатньо помити ввечері",
        "option_2": "Продути паром перед зануренням у молоко, а після збивання протерти вологою окремою серветкою та знову продути",
        "option_3": "Занурити в склянку з холодною водою на 5 хвилин",
        "option_4": "Обробити антисептиком для рук",
        "correct_option": 1,
        "points": 1,
        "explanation": "Продування перед роботою видаляє конденсат води з трубки. Після збивання обов'язково видаляються залишки молока вологою серветкою, виділеною суто для стімера, і трубка продувається для очищення сопла зсередини."
    },
    {
        "question_text": "Чому категорично заборонено повторно збивати вже нагріте або залишене молоко в пітчері?",
        "option_1": "Молоко стане занадто густим для лате-арту",
        "option_2": "Руйнується структура білка, напій набуває гіркого присмаку та створюється ризик бактеріального розмноження",
        "option_3": "Кавомашина видасть помилку тиску пари",
        "option_4": "Збільшується собівартість напою",
        "correct_option": 2,
        "points": 2,
        "explanation": "Повторний нагрів денатурує білок, вбиває молочний цукор, псує смак напою та є прямим порушенням санітарно-гігієнічних вимог HACCP."
    },
    {
        "question_text": "Який термін придатності відкритого пастеризованого молока за температури зберігання +2...+6°C?",
        "option_1": "Не більше 12 годин",
        "option_2": "До 24–48 годин за умови щільно закритого пакування в холодильнику",
        "option_3": "До 7 діб",
        "option_4": "Термін необмежений до появи кислого запаху",
        "correct_option": 2,
        "points": 1,
        "explanation": "Відкрите молоко зберігається виключно в холодильнику при +2...+6°C не більше 24-48 годин (з обов'язковим маркуванням часу відкриття)."
    },
    {
        "question_text": "Що слід зробити із залишками кавового зерна у бункері кавомолки наприкінці робочої зміни?",
        "option_1": "Залишити в бункері, досипавши свіже зерно зверху",
        "option_2": "Пересипати назад у герметичний пакет або світлонепроникний контейнер з клапаном та закрити шибер",
        "option_3": "Змолоти все зерно про запас на ранок",
        "option_4": "Залити бункер миючим розчином",
        "correct_option": 2,
        "points": 1,
        "explanation": "Зерно в прозорому бункері кавомолки за ніч окислюється під впливом повітря і світла та втрачає ефірні олії. Його необхідно герметично упакувати до ранку."
    },
    {
        "question_text": "Як правильно очищати жорна професійної кавомолки від кавових масел та нальоту?",
        "option_1": "Промити проточною водою з милом під краном",
        "option_2": "Використовувати спеціальні чистячі гранули для кавомолок або очистити сухою щіткою (вода суворо заборонена)",
        "option_3": "Засипати харчову соду або сіль",
        "option_4": "Жорна не потребують очищення протягом усього терміну служби",
        "correct_option": 2,
        "points": 2,
        "explanation": "Вода призводить до корозії металевих жорен та виходу кавомолки з ладу. Чищення здійснюється спеціальними зерновими гранулами або сухим механічним способом (щітка/пензлик)."
    },
    {
        "question_text": "Що таке зворотна промивка (Backflush) кавомашини і коли вона проводиться?",
        "option_1": "Промивка бойлера холодною водою раз на рік",
        "option_2": "Щоденне вечірнє промивання кавових груп зі сліпим фільтром та спеціальним порошком/таблетками",
        "option_3": "Злив гарячої води з крана окропу в середині зміни",
        "option_4": "Очищення холдера металевою губкою",
        "correct_option": 2,
        "points": 1,
        "explanation": "Backflush зі сліпим холдером та спеціальним кавовим детергентом проводиться щодня наприкінці зміни для видалення кавових смол та нагару з триходового клапана і душової сітки групи."
    },
    {
        "question_text": "Яка ознака свідчить про наявність 'каналювання' (channeling) у кавовій таблетці під час екстракції?",
        "option_1": "Потік еспресо рівномірний, насиченого темно-горіхового кольору з густою пінкою",
        "option_2": "Струмінь кави б'є нерівномірно, 'стріляє' швидкими світлими струмками, смак напою незбалансований і різкий",
        "option_3": "Кавоварка автоматично вимикається",
        "option_4": "У чашці утворюється занадто висока пінка",
        "correct_option": 2,
        "points": 2,
        "explanation": "Каналювання виникає при нерівномірному розподілі меленої кави або перекосі темпера. Вода знаходить шлях найменшого опору, вимиваючи локальний канал, що дає світлі 'водяні' струмені та різкий кислий/гіркий смак."
    },
    {
        "question_text": "При роботі з рослинним (альтернативним) молоком (вівсяне, мигдальне, кокосове), яка особливість збивання є ключовою?",
        "option_1": "Його треба нагрівати до 85-90°C для густоти",
        "option_2": "Не перегрівати вище 55-60°C, оскільки воно схильне до розшарування та згортання пластівцями",
        "option_3": "Додати лимонну кислоту для стабілізації",
        "option_4": "Збивати без пари ручним вінчиком",
        "correct_option": 2,
        "points": 2,
        "explanation": "Рослинні білки менш стійкі до високих температур, тому критично не перегрівати альтернативне молоко вище 60°C, щоб воно не згорнулося і зберегло приємну текстуру."
    },
    {
        "question_text": "Чому не можна залишати відпрацьовану кавову таблетку в холдері після приготування порції?",
        "option_1": "Таблетка присихає до сітки групи, забруднює її смолами та спотворює смак наступних порцій",
        "option_2": "Холдер почне протікати через ущільнювач",
        "option_3": "Збільшується тиск у бойлері кавомашини",
        "option_4": "Це заборонено виробником чашок",
        "correct_option": 1,
        "points": 1,
        "explanation": "Одразу після приготування холдер вибивається в нок-бокс, протирається сухою серветкою, група коротко проливається водою (flash), і холдер вставляється чистим назад у групу для підтримки температури."
    },
    {
        "question_text": "Який стандартний час подачі гарячого класичного кавового напою гостю в пекарні BULKA?",
        "option_1": "До 2-3 хвилин",
        "option_2": "7-10 хвилин",
        "option_3": "15-20 хвилин",
        "option_4": "Час не має значення, головне дизайн стаканчика",
        "correct_option": 1,
        "points": 1,
        "explanation": "Стандарт швидкості сервісу в BULKA для кавової зони складає 2-3 хвилини, забезпечуючи високу якість напою та відсутність черги."
    },
    {
        "question_text": "Якщо гість скаржиться, що його капучино кислий або холодний, яка правильна дія бариста за стандартами BULKA?",
        "option_1": "Пояснити гостю, що він не розуміється на спешелті зерні",
        "option_2": "Ввічливо перепросити, з'ясувати причину, негайно переробити напій з дотриманням стандарту та посмішкою",
        "option_3": "Сказати, що так налаштована кавомашина і нічого не можна змінити",
        "option_4": "Відправити гостя писати скаргу керівнику пекарні",
        "correct_option": 2,
        "points": 1,
        "explanation": "Правило гостинності BULKA — лояльність гостя понад усе. Бариста доброзичливо перепрошує, негайно переробляє напій і перевіряє налаштування помелу/температури."
    },
    {
        "question_text": "Яка ідеальна супутня пропозиція (up-sale) від бариста до замовленого американо чи капучино?",
        "option_1": "Запропонувати другу чашку окропу",
        "option_2": "Запропонувати свіжу фірмову випічку або десерт (наприклад, теплий круасан чи сирник)",
        "option_3": "Запропонувати купити кілограм сирої муки",
        "option_4": "Мовчки пробити чек без пропозицій",
        "correct_option": 2,
        "points": 1,
        "explanation": "Бариста в пекарні BULKA не лише готує каву, а й створює атмосферу та смакові комбінації: 'До вашого капучино рекомендую наш свіжоспечений мигдалевий круасан!'"
    },
    {
        "question_text": "Який тиск пари вважається нормальним робочим показником у бойлері професійної еспресо-машини?",
        "option_1": "0.1 - 0.3 бар",
        "option_2": "1.0 - 1.3 бар",
        "option_3": "3.5 - 4.5 бар",
        "option_4": "9.0 - 10.0 бар",
        "correct_option": 2,
        "points": 1,
        "explanation": "Тиск у паровому бойлері зазвичай підтримується на рівні 1.0–1.3 бар (що забезпечує температуру близько 120-125°C для сухої сухої пари). Не плутати з тиском помпи під час проливу еспресо (9 бар)."
    }
]


async def main():
    print("🚀 Генерація заповненого бланку атестації для 'ВВ Бариста'...")
    positions = await get_all_positions()
    roles = [p["name"] for p in positions]
    if "Керівник" not in roles:
        roles.insert(0, "Керівник")
    if "ВВ Бариста" not in roles:
        roles.append("ВВ Бариста")
    roles = sorted(list(set(roles)))

    # 1. Створюємо книгу Excel
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    headers = [
        "Питання",
        "Варіант 1",
        "Варіант 2",
        "Варіант 3",
        "Варіант 4",
        "Вірна відповідь (1-4)",
        "Бали",
        "Пояснення (опціонально)"
    ]

    existing_titles = set()

    for role in roles:
        safe_title = _sanitize_sheet_title(role, existing_titles)
        ws = wb.create_sheet(title=safe_title)
        ws.views.sheetView[0].showGridLines = True

        # Header
        ws.merge_cells("A1:H1")
        top_cell = ws["A1"]
        top_cell.value = f"🥐 БАНК ПИТАНЬ АТЕСТАЦІЇ: {role.upper()}"
        top_cell.font = FONT_TITLE
        top_cell.fill = HEADER_FILL_GOLD
        top_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 32

        for col_idx, h_text in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col_idx, value=h_text)
            cell.font = FONT_HEADER
            cell.fill = HEADER_FILL_DARK
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = BORDER_THIN
        ws.row_dimensions[2].height = 28

        if role == "ВВ Бариста":
            # Заповнюємо 18 професійних питань
            for row_idx, q in enumerate(BARISTA_QUESTIONS, 3):
                ws.row_dimensions[row_idx].height = 36
                fill_to_use = ZEBRA_FILL if row_idx % 2 == 0 else PatternFill(fill_type=None)

                c1 = ws.cell(row=row_idx, column=1, value=q["question_text"])
                c1.font = FONT_DATA
                c1.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                c1.border = BORDER_THIN
                if fill_to_use.fill_type: c1.fill = fill_to_use

                for opt_i in range(1, 5):
                    opt_val = q.get(f"option_{opt_i}", "")
                    c_opt = ws.cell(row=row_idx, column=1 + opt_i, value=opt_val)
                    c_opt.font = FONT_DATA
                    c_opt.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                    c_opt.border = BORDER_THIN
                    if fill_to_use.fill_type: c_opt.fill = fill_to_use

                c_corr = ws.cell(row=row_idx, column=6, value=q["correct_option"])
                c_corr.font = FONT_BOLD
                c_corr.alignment = Alignment(horizontal="center", vertical="center")
                c_corr.border = BORDER_THIN
                if fill_to_use.fill_type: c_corr.fill = fill_to_use

                c_pts = ws.cell(row=row_idx, column=7, value=q["points"])
                c_pts.font = FONT_BOLD
                c_pts.alignment = Alignment(horizontal="center", vertical="center")
                c_pts.border = BORDER_THIN
                if fill_to_use.fill_type: c_pts.fill = fill_to_use

                c_exp = ws.cell(row=row_idx, column=8, value=q.get("explanation", ""))
                c_exp.font = FONT_DATA
                c_exp.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                c_exp.border = BORDER_THIN
                if fill_to_use.fill_type: c_exp.fill = fill_to_use
        else:
            # Зразок рядка
            ws.row_dimensions[3].height = 30
            sample_data = [
                f"Зразкове питання для посади {role}?",
                "Варіант А",
                "Варіант Б (Правильний)",
                "Варіант В",
                "Варіант Г",
                2,
                1,
                "Пояснення чому відповідь 2 вірна."
            ]
            for col_idx, val in enumerate(sample_data, 1):
                c = ws.cell(row=3, column=col_idx, value=val)
                c.font = FONT_DATA
                c.alignment = Alignment(horizontal="center" if col_idx in (6, 7) else "left", vertical="center")
                c.border = BORDER_THIN

        # Налаштування ширини колонок
        col_widths = {1: 45, 2: 26, 3: 26, 4: 26, 5: 26, 6: 18, 7: 12, 8: 45}
        for col_idx, width in col_widths.items():
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width

    # Зберігаємо файл у корінь проекту
    output_path = "template_attestation.xlsx"
    wb.save(output_path)
    print(f"✅ Файл успішно збережено: {output_path} (розмір: {os.path.getsize(output_path)} байт)")

    # 2. Зберігаємо питання в базу даних SQLite
    print("📦 Збереження питань у базу даних SQLite (таблиця attestation_questions)...")
    saved_count = await save_questions_for_role("ВВ Бариста", BARISTA_QUESTIONS)
    print(f"✅ Успішно збережено в базі даних для 'ВВ Бариста': {saved_count} питань")

    # 3. Перевірка валідації через парсер
    with open(output_path, "rb") as f:
        file_bytes = f.read()
    parsed_data, warnings = parse_attestation_excel(file_bytes, roles)
    print(f"🔍 Валідація парсером: розпізнано посад = {len(parsed_data)}, попереджень = {len(warnings)}")
    if "ВВ Бариста" in parsed_data:
        print(f"☕ Питань для 'ВВ Бариста' розпарсено: {len(parsed_data['ВВ Бариста'])}")

    counts = await get_questions_count_by_role()
    print("📊 Актуальна кількість питань за посадами в БД:")
    for r_name, count in counts.items():
        print(f"  - {r_name}: {count} питань")


if __name__ == "__main__":
    asyncio.run(main())
