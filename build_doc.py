import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def add_hyperlink(paragraph, url, text, color="004B91", underline=True):
    part = paragraph.part
    r_id = part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)
    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    if color:
        c = OxmlElement('w:color')
        c.set(qn('w:val'), color)
        rPr.append(c)
    if underline:
        u = OxmlElement('w:u')
        u.set(qn('w:val'), 'single')
        rPr.append(u)
    new_run.append(rPr)
    text_elem = OxmlElement('w:t')
    text_elem.text = text
    new_run.append(text_elem)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)

def create_document():
    doc = docx.Document()
    
    # Page setup: standard 0.8 inch margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
        
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(10.5)
    font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    
    # Title
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    r_title = p_title.add_run("Рішення тестового завдання: Спеціаліст з автоматизації бізнес-процесів")
    r_title.font.size = Pt(17)
    r_title.font.bold = True
    r_title.font.color.rgb = RGBColor(0x11, 0x18, 0x27)
    
    # Subtitle metadata
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(10)
    r_cand = p_sub.add_run("Кандидат: ")
    r_cand.bold = True
    p_sub.add_run("Даніїл Душинський   |   ")
    r_comp = p_sub.add_run("Компанія: ")
    r_comp.bold = True
    p_sub.add_run("Manimama OÜ (Tallinn, Estonia)   |   ")
    r_date = p_sub.add_run("Дата: ")
    r_date.bold = True
    p_sub.add_run("24 вересня 2026")
    
    # Divider
    p_div = doc.add_paragraph()
    p_div.paragraph_format.space_after = Pt(10)
    r_div = p_div.add_run("―" * 50)
    r_div.font.color.rgb = RGBColor(0xD1, 0xD5, 0xDB)

    # 1. Аналіз та пріоритизація процесів
    h1 = doc.add_heading("1. Аналіз та пріоритизація процесів", level=1)
    h1.paragraph_format.space_before = Pt(8)
    h1.paragraph_format.space_after = Pt(5)
    for r in h1.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
        r.font.size = Pt(13)
        
    p1 = doc.add_paragraph("Для першої черги автоматизації я вибрав два процеси з найвищою частотою повторень (High Frequency) та критичним впливом на інформаційну безпеку компанії.")
    p1.paragraph_format.space_after = Pt(6)
    
    # 1.1 Priority 1
    h2_1 = doc.add_heading("1.1. Пребординг, онбординг та офбординг: безпека доступів і кадрових документів", level=2)
    h2_1.paragraph_format.space_before = Pt(6)
    h2_1.paragraph_format.space_after = Pt(4)
    for r in h2_1.runs:
        r.font.color.rgb = RGBColor(0x25, 0x63, 0xEB)
        r.font.size = Pt(11.5)

    p_p1_prob = doc.add_paragraph(style='List Bullet')
    p_p1_prob.paragraph_format.space_after = Pt(3)
    r = p_p1_prob.add_run("Яку проблему вирішує: ")
    r.bold = True
    p_p1_prob.add_run("HR вручну збирає копії документів, створює структуру папок на Google Drive, переносить паспортні дані в договори та пише сисадміну про створення акаунтів. При звільненні відсутній єдиний регламентований контроль своєчасного закриття доступів.")
    
    p_p1_why = doc.add_paragraph(style='List Bullet')
    p_p1_why.paragraph_format.space_after = Pt(3)
    r = p_p1_why.add_run("Чому на першому етапі: ")
    r.bold = True
    p_p1_why.add_run("Manimama спеціалізується на Law & Crypto. Затримка з підписанням NDA або людський фактор при звільненні (незакритий доступ колишнього працівника до пошти, дисків, репозиторіїв чи чатів) несуть прямий юридичний і фінансовий ризик для клієнтів.")

    p_p1_res = doc.add_paragraph(style='List Bullet')
    p_p1_res.paragraph_format.space_after = Pt(7)
    r = p_p1_res.add_run("Очікуваний бізнес-ефект: ")
    r.bold = True
    p_p1_res.add_run("Скорочення витрат часу HR на оформлення одного новачка з 4 годин до 40 хвилин. Усунення дублювання файлів. Гарантований регламент відкликання доступів при офбордингу через автоматизовані задачі контролю.")

    # 1.2 Priority 2
    h2_2 = doc.add_heading("1.2. HR Operations: облік відпусток, лікарняних і Day Off через Telegram", level=2)
    h2_2.paragraph_format.space_before = Pt(6)
    h2_2.paragraph_format.space_after = Pt(4)
    for r in h2_2.runs:
        r.font.color.rgb = RGBColor(0x25, 0x63, 0xEB)
        r.font.size = Pt(11.5)

    p_p2_prob = doc.add_paragraph(style='List Bullet')
    p_p2_prob.paragraph_format.space_after = Pt(3)
    r = p_p2_prob.add_run("Яку проблему вирішує: ")
    r.bold = True
    p_p2_prob.add_run("Повідомлення про відсутність пишуться хаотично в чатах Telegram. HR вручну рахує баланс днів у таблицях Excel і руками переносить події в Google Calendar.")

    p_p2_why = doc.add_paragraph(style='List Bullet')
    p_p2_why.paragraph_format.space_after = Pt(3)
    r = p_p2_why.add_run("Чому на першому етапі: ")
    r.bold = True
    p_p2_why.add_run("Класичний Quick Win. Процес простий у побудові, відбувається щотижня для всієї команди і дає миттєвий результат у вигляді прозорості графіків.")

    p_p2_res = doc.add_paragraph(style='List Bullet')
    p_p2_res.paragraph_format.space_after = Pt(8)
    r = p_p2_res.add_run("Очікуваний бізнес-ефект: ")
    r.bold = True
    p_p2_res.add_run("Співробітник бачить свій залишок днів у боті за 5 секунд. Тімлід погоджує запит кнопкою в Telegram. Подія автоматично записується в календар команди без участі HR.")

    # 1.3 What NOT to automate
    h2_not = doc.add_heading("1.3. Процеси, які не варто автоматизувати на першому етапі", level=2)
    h2_not.paragraph_format.space_before = Pt(6)
    h2_not.paragraph_format.space_after = Pt(4)
    for r in h2_not.runs:
        r.font.color.rgb = RGBColor(0xDC, 0x26, 0x26)
        r.font.size = Pt(11.5)

    p_not1 = doc.add_paragraph(style='List Bullet')
    p_not1.paragraph_format.space_after = Pt(3)
    r = p_not1.add_run("Саммарі та оцінка співбесід через ChatGPT (розділ 2.3 Рекрутинг): ")
    r.bold = True
    p_not1.add_run("Для естонської компанії повна автоматизація оцінки кандидатів несе регуляторні ризики:")

    p_sub1 = doc.add_paragraph()
    p_sub1.paragraph_format.left_indent = Inches(0.35)
    p_sub1.paragraph_format.space_after = Pt(3)
    p_sub1.add_run("1. Відповідно до ")
    add_hyperlink(p_sub1, "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689", "EU AI Act (Regulation 2024/1689, Annex III, Point 4)")
    p_sub1.add_run(", системи ШІ у сфері працевлаштування та оцінки кандидатів класифіковані як High-Risk. Вони вимагають обов'язкового принципу Human Oversight (людського контролю за статтею 14) та моніторингу алгоритмічної упередженості (AI Bias).")

    p_sub2 = doc.add_paragraph()
    p_sub2.paragraph_format.left_indent = Inches(0.35)
    p_sub2.paragraph_format.space_after = Pt(3)
    p_sub2.add_run("2. За нормами ")
    add_hyperlink(p_sub2, "https://gdpr-info.eu/art-22-gdpr/", "GDPR (стаття 22)")
    p_sub2.add_run(", автоматизоване ухвалення рішень, що мають юридичні наслідки для людини, обмежене суворими критеріями. Передача аудіозаписів співбесід із персональними даними у зовнішні хмарні моделі вимагає наявності Data Processing Agreement (DPA) та оцінки ризиків передачі даних.")

    p_sub_concl = doc.add_paragraph()
    p_sub_concl.paragraph_format.left_indent = Inches(0.35)
    p_sub_concl.paragraph_format.space_after = Pt(5)
    r_rec = p_sub_concl.add_run("Технічне розмежування: ")
    r_rec.bold = True
    p_sub_concl.add_run("Саммарі внутрішніх мітингів команди (розділ 2.1) є безпечним внутрішнім процесом, де ШІ є корисним помічником. А ось оцінку співбесід (розділ 2.3) не слід автоматизувати повністю. ШІ тут може слугувати лише чорновим конспектом, але фінальне структурування та висновок мають залишатися за рекрутером.")

    p_not2 = doc.add_paragraph(style='List Bullet')
    p_not2.paragraph_format.space_after = Pt(10)
    r = p_not2.add_run("Оцінка 360 та індивідуальні плани розвитку (ІПР): ")
    r.bold = True
    p_not2.add_run("Оцінка 360 проводиться лише 1-2 рази на рік. Автоматизація низькочастотних процесів на ранньому етапі дає низький ROI. Для неї наразі цілком достатньо уніфікованої Google-форми.")

    # 2. Розробка рішення
    h1_2 = doc.add_heading("2. Розробка рішення: наскрізний пребординг та онбординг", level=1)
    h1_2.paragraph_format.space_before = Pt(10)
    h1_2.paragraph_format.space_after = Pt(5)
    for r in h1_2.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
        r.font.size = Pt(13)

    p_flow_cur = doc.add_paragraph()
    p_flow_cur.paragraph_format.space_after = Pt(3)
    r = p_flow_cur.add_run("Поточний стан (AS-IS): ")
    r.bold = True
    p_flow_cur.add_run("Після прийняття офферу HR вручну пише привітання, створює папку на Drive, надсилає форму для документів, копіює дані в договір і NDA, надсилає на підпис, просить сисадміна видати пошту і контролює строки вручну в таблиці.")

    p_flow_new = doc.add_paragraph()
    p_flow_new.paragraph_format.space_after = Pt(6)
    r = p_flow_new.add_run("Цільовий стан (TO-BE): ")
    r.bold = True
    p_flow_new.add_run("Єдиний подієво-орієнтований контур від зміни статусу кандидата до виходу на роботу із закріпленим чеклістом завдань.")

    # Table of process passport
    table = doc.add_table(rows=8, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    headers = [
        ("Параметр процесу", "Опис технічної та бізнес-логіки"),
        ("Тригер (Trigger)", "Зміна статусу кандидата на «Оффер прийнято» в таблиці або Bitrix24 (webhook подія з передачею candidate_id)"),
        ("Вхідні дані (Input Data)", "ПІБ, посада, дата виходу, особистий Telegram, email, реквізити, скани документів, призначений тімлід і наставник"),
        ("Автоматичні дії (Actions)", "1. Створення папки кандидата на Google Drive за єдиним неймінгом з обмеженими правами доступу\n2. Відправка кандидату посилання на форму завантаження даних\n3. Автогенерація заповненого NDA та договору через Google Docs Template\n4. Створення профілю в Bitrix24 зі статусом «Випробувальний термін»\n5. Створення інцидент-задачі для IT з дедлайном: видати пошту і робочі доступи\n6. Відправка новачку доступу до вітального Telegram-бота в День 1 о 09:00"),
        ("Умови та винятки (Exceptions)", "Якщо кандидат не надав документи за 48 годин до дати виходу: HR отримує алерт у Telegram для ручного дзвінка.\nЯкщо IT не закрило задачу на доступи за 24 години до старту: автоматична ескалація тімліду"),
        ("Сповіщення (Notifications)", "Кандидату: вітальний лист і форма (одразу), нагадування за 24 години до виходу, посилання на бота в День 1.\nHR: звіт про успішний збір документів або сповіщення про затримки.\nТімліду: картка новачка і призначена дата старту"),
        ("Зберігання даних (Storage)", "Документи та підписані договори: ізольований Google Drive з контролем прав доступу.\nКадрова картка, статуси задач та історія: Bitrix24 (єдине джерело правди для операційки)"),
        ("Дії за людиною (Human Oversight)", "HR перевіряє коректність реквізитів і справжність документів. Уповноважена особа підписує договір. Тімлід проводить обов'язкову живу зустріч 1:1 у перший робочий день")
    ]
    
    for i, (col1, col2) in enumerate(headers):
        row = table.rows[i]
        c1, c2 = row.cells[0], row.cells[1]
        c1.width = Inches(2.2)
        c2.width = Inches(4.7)
        c1.text = col1
        c2.text = col2
        if i == 0:
            c1.paragraphs[0].runs[0].bold = True
            c2.paragraphs[0].runs[0].bold = True
            c1.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            c2.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            shd1 = OxmlElement('w:shd')
            shd1.set(qn('w:val'), 'clear')
            shd1.set(qn('w:color'), 'auto')
            shd1.set(qn('w:fill'), '1F2937')
            c1._tc.get_or_add_tcPr().append(shd1)
            shd2 = OxmlElement('w:shd')
            shd2.set(qn('w:val'), 'clear')
            shd2.set(qn('w:color'), 'auto')
            shd2.set(qn('w:fill'), '1F2937')
            c2._tc.get_or_add_tcPr().append(shd2)
        else:
            c1.paragraphs[0].runs[0].bold = True

    p_sp = doc.add_paragraph()
    p_sp.paragraph_format.space_before = Pt(6)

    # 3. Інструменти та реалізація
    h1_3 = doc.add_heading("3. Інструменти, архітектура та реалізація", level=1)
    h1_3.paragraph_format.space_before = Pt(10)
    h1_3.paragraph_format.space_after = Pt(5)
    for r in h1_3.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
        r.font.size = Pt(13)

    p_tools = doc.add_paragraph()
    p_tools.paragraph_format.space_after = Pt(3)
    r = p_tools.add_run("Стек інструментів:")
    r.bold = True

    tools_list = [
        ("n8n (або Make): ", "Оркестратор подій та інтеграцій. Поєднує Bitrix24, Google Workspace і Telegram без розробки громіздкого моноліту. Підтримує self-hosted розгортання в закритому контурі компанії, що критично для захисту банківських і кадрових даних."),
        ("Telegram Bot API: ", "Інтерфейс для сповіщень співробітника, доставки чеклістів та швидкого погодження запитів тімлідами."),
        ("Google Workspace (Drive, Docs, Sheets API): ", "Збереження кадрових файлів, структуроване автозаповнення шаблонів угод за змінними реквізитів."),
        ("Bitrix24 REST API: ", "Управління задачами, дедлайнами, статусами та картками співробітників.")
    ]
    for name, desc in tools_list:
        p_t = doc.add_paragraph(style='List Bullet')
        p_t.paragraph_format.space_after = Pt(3)
        r = p_t.add_run(name)
        r.bold = True
        p_t.add_run(desc)

    # Risk analysis section - expanded and detailed
    h2_risk = doc.add_heading("3.1. Технічні ризики та заходи їх нейтралізації", level=2)
    h2_risk.paragraph_format.space_before = Pt(8)
    h2_risk.paragraph_format.space_after = Pt(4)
    for r in h2_risk.runs:
        r.font.color.rgb = RGBColor(0x25, 0x63, 0xEB)
        r.font.size = Pt(11.5)

    risks = [
        ("1. Повторний запуск вебхуків та захист від дублювання (Idempotency): ", 
         "Якщо Bitrix24 чи веб-форма надішле один і той самий вебхук двічі через збій мережі, є ризик створення дублікатів папок чи договорів. Рішення: використання ідемпотентного ключа (Idempotency Key) на базі candidate_id та перевірка наявності запису перед виконанням сценарію."),
        ("2. Частковий збій сценарію та збереження стану (Correlation ID): ", 
         "Якщо папка на Drive створилася, але генерація договору впала через тимчасову помилку Google API. Рішення: кожен запуск сценарію має єдиний correlation_id, а кроки логуються зі статусами (folder_created, doc_pending). При збої надсилається алерт адміністратору, а сценарій відновлюється з точки зупинки без повторного створення вже готових сутностей."),
        ("3. Ліміти API та тимчасова недоступність сервісів (Rate Limits 429/500): ", 
         "При масових діях Bitrix24 або Google Drive можуть повернути HTTP 429. Рішення: використання черги повідомлень у n8n з експоненційною затримкою повторних спроб (Exponential Backoff with Retry)."),
        ("4. Безпека ключів доступу та секретів: ", 
         "Усі API-токени та облікові дані OAuth зберігаються виключно в захищеному сховищі n8n Credentials і шифруються через системний ENCRYPTION_KEY, без збереження у тілі самих сценаріїв."),
        ("5. Розмежування прав доступу на Google Drive: ", 
         "Ризик витоку документів інших кандидатів. Рішення: налаштування успадкування прав (Role-Based Access Control). Доступ до кореневої кадрової папки має лише HR, а тімлід отримує доступ виключно до папки свого співробітника.")
    ]
    for r_title, r_desc in risks:
        p_r = doc.add_paragraph(style='List Bullet')
        p_r.paragraph_format.space_after = Pt(3)
        r = p_r.add_run(r_title)
        r.bold = True
        p_r.add_run(r_desc)

    # Timeline & MVP
    h2_plan = doc.add_heading("3.2. Строки, етапи та розмежування MVP", level=2)
    h2_plan.paragraph_format.space_before = Pt(8)
    h2_plan.paragraph_format.space_after = Pt(4)
    for r in h2_plan.runs:
        r.font.color.rgb = RGBColor(0x25, 0x63, 0xEB)
        r.font.size = Pt(11.5)

    p_time = doc.add_paragraph()
    p_time.paragraph_format.space_after = Pt(4)
    r = p_time.add_run("Орієнтовний термін реалізації MVP: ")
    r.bold = True
    p_time.add_run("12-14 робочих днів за умови вчасного надання доступів до API.")

    steps = [
        ("Етап 1: Стандартизація та доступи (3 дні). ", "Узгодження шаблонів NDA, структури папок Drive, перевірка API-токенів Bitrix24 та Google Workspace."),
        ("Етап 2: Розробка інтеграцій (5-6 днів). ", "Створення сценаріїв n8n, налаштування вебхуків, генерації папок і документів, створення задач у Bitrix24."),
        ("Етап 3: Обробка винятків і тестування (3 дні). ", "Прогін тестових сценаріїв з імітацією збоїв мережі та неповних даних від кандидатів, налаштування алертів."),
        ("Етап 4: Впровадження та навчання (2 дні). ", "Передача готових регламентів команді HR та технічним спеціалістам.")
    ]
    for title, desc in steps:
        p_s = doc.add_paragraph(style='List Bullet')
        p_s.paragraph_format.space_after = Pt(2)
        r = p_s.add_run(title)
        r.bold = True
        p_s.add_run(desc)

    p_mvp = doc.add_paragraph()
    p_mvp.paragraph_format.space_before = Pt(5)
    p_mvp.paragraph_format.space_after = Pt(3)
    r = p_mvp.add_run("Розподіл функціоналу між MVP та наступними релізами:")
    r.bold = True

    p_mvp_in = doc.add_paragraph(style='List Bullet')
    p_mvp_in.paragraph_format.space_after = Pt(2)
    p_mvp_in.add_run("У першій версії (MVP): автоматичне створення папок на Drive, форма збору даних, автогенерація документів і NDA, створення задач у Bitrix24. Для офбордингу в MVP реалізується автоматична інцидент-задача для IT з обов'язковим чеклістом деактивації акаунтів та жорстким контролем дедлайну.")

    p_mvp_next = doc.add_paragraph(style='List Bullet')
    p_mvp_next.paragraph_format.space_after = Pt(8)
    p_mvp_next.add_run("На наступні етапи: повноцінний інтерактивний Telegram-бот для навчання новачка з тестуванням матеріалів. Програмне відкликання корпоративних акаунтів і доступів до API в один клік через Google Admin SDK та Bitrix24 API.")

    # 4. Уточнення
    h1_4 = doc.add_heading("4. Запитання команді перед початком робіт", level=1)
    h1_4.paragraph_format.space_before = Pt(10)
    h1_4.paragraph_format.space_after = Pt(5)
    for r in h1_4.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
        r.font.size = Pt(13)

    p_q_intro = doc.add_paragraph("Перед початком розробки архітектури важливо погодити наступні технічні параметри:")
    p_q_intro.paragraph_format.space_after = Pt(4)

    questions = [
        ("1. Що є головною базою кадрових даних (Single Source of Truth): ", "Bitrix24 чи таблиці Google Sheets? Яка система вважається первинною при виникненні розбіжностей?"),
        ("2. Конфігурація та тарифний план Bitrix24: ", "Використовується хмарна версія чи коробкова On-Premise? Чи є активна підписка на Bitrix24.Маркет і відкритий доступ до REST API для вхідних та вихідних вебхуків?"),
        ("3. Внутрішні вимоги щодо обробки персональних даних: ", "Чи дозволено політикою безпеки передавати паспортні та банківські дані кандидатів через сторонні хмарні сервіси автоматизації (Make), чи архітектура вимагає виключно локального self-hosted розгортання оркестратора n8n на сервері компанії?"),
        ("4. Реєстр систем для офбордингу: ", "Який точний перелік робочих ресурсів, де співробітники отримують доступ (пошта, Bitrix24, внутрішні бази, клієнтські кабінети, корпоративні менеджери паролів)?"),
        ("5. Середній щомісячний потік найму: ", "Скільки нових фахівців у середньому проходить через процедуру онбордингу щомісяця?")
    ]
    for q_title, q_body in questions:
        p_q = doc.add_paragraph(style='List Bullet')
        p_q.paragraph_format.space_after = Pt(3)
        r = p_q.add_run(q_title)
        r.bold = True
        p_q.add_run(q_body)

    output_path = "/Users/daniildusinskij/All/Dev/Bulka_Edu/Manimama_Test_Danik.docx"
    doc.save(output_path)
    print(f"Document saved to {output_path}")

if __name__ == "__main__":
    create_document()
