/**
 * BULKA Attestation Telegram Mini App Frontend
 */

(function () {
  'use strict';

  // Telegram WebApp SDK
  const tg = window.Telegram?.WebApp;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
    } catch (e) {
      console.warn('tg init warning:', e);
    }
  }

  function getTelegramInitData() {
    let data = tg?.initData || '';
    if (!data && window.location.hash) {
      try {
        const hashParams = new URLSearchParams(window.location.hash.substring(1));
        data = hashParams.get('tgWebAppData') || '';
      } catch (e) {}
    }
    if (!data) {
      const urlParams = new URLSearchParams(window.location.search);
      const debugUid = urlParams.get('debug_user_id');
      if (debugUid) {
        data = `debug_user_id=${debugUid}`;
      }
    }
    return data;
  }

  // Global error safety
  window.addEventListener('error', function (e) {
    console.error('Attestation runtime error:', e.error || e.message);
    const lt = document.querySelector('#screen-loading .loader-text');
    if (lt && screens.loading?.classList.contains('active')) {
      lt.innerText = "Помилка завантаження. Спробуйте оновити сторінку.";
    }
  });
  window.addEventListener('unhandledrejection', function (e) {
    console.error('Attestation unhandled rejection:', e.reason);
    const lt = document.querySelector('#screen-loading .loader-text');
    if (lt && screens.loading?.classList.contains('active')) {
      lt.innerText = "Помилка зв'язку. Спробуйте оновити сторінку.";
    }
  });

  // Стан додатка
  let appState = {
    attemptId: null,
    waveTitle: '',
    roleName: '',
    shopName: '',
    userName: '',
    durationMinutes: 20,
    remainingSeconds: 1200,
    passingScorePct: 80,
    questions: [],
    currentIndex: 0,
    answers: {}, // { question_id: option_number (1..4) }
    timerInterval: null
  };

  // DOM-елементи
  const screens = {
    loading: document.getElementById('screen-loading'),
    locked: document.getElementById('screen-locked'),
    welcome: document.getElementById('screen-welcome'),
    quiz: document.getElementById('screen-quiz'),
    result: document.getElementById('screen-result')
  };

  function showScreen(screenKey) {
    Object.values(screens).forEach(s => s?.classList.remove('active'));
    screens[screenKey]?.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function triggerHaptic(type = 'light') {
    if (tg?.HapticFeedback) {
      try {
        if (type === 'success') tg.HapticFeedback.notificationOccurred('success');
        else if (type === 'error') tg.HapticFeedback.notificationOccurred('error');
        else tg.HapticFeedback.impactOccurred(type);
      } catch (e) {}
    }
  }

  // ==========================================
  // 1. ІНІЦІАЛІЗАЦІЯ ТА ВАЛІДАЦІЯ ДОСТУПУ
  // ==========================================
  async function initApp() {
    // Показуємо екран завантаження
    showScreen('loading');
    const loaderText = document.querySelector('#screen-loading .loader-text');
    if (loaderText) loaderText.innerText = 'Перевірка доступу до атестації...';

    // Даємо iOS Telegram bridge час передати initData
    let initData = getTelegramInitData();
    if (!initData) {
      for (let i = 0; i < 10; i++) {
        await new Promise(r => setTimeout(r, 150));
        initData = getTelegramInitData();
        if (initData) break;
      }
    }

    if (!initData) {
      showLockedScreen('Неавторизований доступ', 'Будь ласка, відкрийте додаток через персональну кнопку в Telegram-боті BULKA.');
      return;
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 12000);

      const response = await fetch('/attestation/api/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initData }),
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        showLockedScreen('Доступ закрито', err.message || 'Не вдалося перевірити доступ до атестації.');
        return;
      }

      const data = await response.json();

      if (data.status === 'locked') {
        showLockedScreen('Атестація недоступна', data.message || 'Для вашого магазину атестація не активна.');
        return;
      }

      if (data.status === 'completed') {
        // Користувач уже склав тест
        showCompletedScreen(data);
        return;
      }

      if (data.status === 'ready') {
        // Успішно підготовлено до складання
        setupReadyState(data);
        return;
      }

      // Неочікуваний статус
      showLockedScreen('Стан не визначено', data.message || 'Спробуйте перезапустити додаток.');
    } catch (e) {
      console.error('API init error:', e);
      const isTimeout = e.name === 'AbortError';
      const msg = isTimeout 
        ? "Час очікування відповіді вичерпано. Перевірте з'єднання з інтернетом."
        : "Перевірте інтернет-з'єднання та спробуйте ще раз.";
      showLockedScreen('Помилка підключення', msg);
    }
  }

  function showLockedScreen(title, message) {
    const titleEl = document.getElementById('locked-title');
    const msgEl = document.getElementById('locked-message');
    if (titleEl) titleEl.innerText = title;
    if (msgEl) msgEl.innerText = message;
    showScreen('locked');

    document.getElementById('btn-close-locked')?.addEventListener('click', () => {
      if (tg) tg.close();
      else window.close();
    });
  }

  function showCompletedScreen(data) {
    const isPassed = data.attempt_status === 'passed';
    const badgeEl = document.getElementById('result-badge');
    const titleEl = document.getElementById('result-title');
    const subtitleEl = document.getElementById('result-subtitle');
    const circleEl = document.getElementById('score-circle');
    const pctEl = document.getElementById('result-score-pct');
    const fracEl = document.getElementById('result-score-fraction');

    if (badgeEl) badgeEl.innerText = isPassed ? '🎉' : '⏳';
    if (titleEl) titleEl.innerText = isPassed ? 'Атестацію складено!' : 'Атестацію не складено';
    if (subtitleEl) {
      subtitleEl.innerText = isPassed 
        ? `Твій результат зараховано до рейтингу магазину ${data.shop_name}!`
        : 'Зверніться до керівника або адміністратора щодо можливої перездачі.';
    }

    if (circleEl) {
      if (isPassed) circleEl.classList.remove('failed');
      else circleEl.classList.add('failed');
    }

    if (pctEl) pctEl.innerText = `${data.score_pct}%`;
    if (fracEl) fracEl.innerText = `${data.score} з ${data.max_score} балів`;

    document.getElementById('res-shop-name').innerText = data.shop_name || '-';
    document.getElementById('res-role-name').innerText = data.role_name || '-';
    document.getElementById('res-status-label').innerText = isPassed ? '✅ Складено' : '❌ Не складено';

    // Форматування тривалості
    const durSec = data.duration_seconds || 0;
    const durMins = Math.floor(durSec / 60);
    document.getElementById('res-duration').innerText = durMins > 0 ? `${durMins} хв` : `${durSec} сек`;

    showScreen('result');

    if (isPassed && window.confetti) {
      triggerHaptic('success');
      window.confetti({ particleCount: 80, spread: 70, origin: { y: 0.6 } });
    }

    document.getElementById('btn-close-app')?.addEventListener('click', () => {
      if (tg) tg.close();
      else window.close();
    });
  }

  function setupReadyState(data) {
    appState.attemptId = data.attempt_id;
    appState.waveTitle = data.wave_title;
    appState.roleName = data.role_name;
    appState.shopName = data.shop_name;
    appState.userName = data.user_name;
    appState.durationMinutes = data.duration_minutes;
    appState.remainingSeconds = data.remaining_seconds;
    appState.passingScorePct = data.passing_score_pct;
    appState.questions = data.questions || [];
    appState.answers = data.saved_answers || {};

    // Заповнення Welcome Screen
    document.getElementById('welcome-wave-badge').innerText = data.wave_title;
    document.getElementById('welcome-user-name').innerText = data.user_name || 'Співробітник';
    document.getElementById('welcome-role').innerText = data.role_name;
    document.getElementById('welcome-shop').innerText = data.shop_name;
    document.getElementById('rule-time').innerText = `${data.duration_minutes} хвилин на проходження`;
    document.getElementById('rule-questions-count').innerText = `${appState.questions.length} фахових запитань`;
    document.getElementById('rule-pass-pct').innerText = `Прохідний поріг: ${data.passing_score_pct}%`;

    showScreen('welcome');

    document.getElementById('btn-start-quiz')?.addEventListener('click', startQuiz);
  }

  // ==========================================
  // 2. СТАРТ ТА ПРОВЕДЕННЯ ТЕСТУ
  // ==========================================
  function startQuiz() {
    triggerHaptic('medium');
    showScreen('quiz');
    startTimer();
    renderRibbon();
    renderQuestion(0);
  }

  function startTimer() {
    updateTimerDisplay();

    if (appState.timerInterval) clearInterval(appState.timerInterval);

    appState.timerInterval = setInterval(() => {
      appState.remainingSeconds--;
      updateTimerDisplay();

      if (appState.remainingSeconds <= 0) {
        clearInterval(appState.timerInterval);
        submitQuiz(true); // timeout auto-submit
      }
    }, 1000);
  }

  function updateTimerDisplay() {
    const timerBadge = document.getElementById('quiz-timer');
    const timerDisplay = document.getElementById('timer-display');
    const sec = Math.max(0, appState.remainingSeconds);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    const formatted = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

    if (timerDisplay) timerDisplay.innerText = formatted;

    if (timerBadge) {
      if (sec <= 180) { // менше 3 хвилин
        timerBadge.className = 'timer-badge critical';
      } else if (sec <= 360) { // менше 6 хвилин
        timerBadge.className = 'timer-badge warning';
      } else {
        timerBadge.className = 'timer-badge';
      }
    }
  }

  function renderRibbon() {
    const ribbonEl = document.getElementById('questions-ribbon');
    if (!ribbonEl) return;
    ribbonEl.innerHTML = '';

    appState.questions.forEach((q, idx) => {
      const pill = document.createElement('div');
      pill.className = 'ribbon-pill';
      pill.innerText = idx + 1;
      pill.id = `ribbon-pill-${idx}`;

      if (idx === appState.currentIndex) pill.classList.add('active');
      if (appState.answers[q.id.toString()] !== undefined) pill.classList.add('answered');

      pill.addEventListener('click', () => {
        triggerHaptic('light');
        renderQuestion(idx);
      });

      ribbonEl.appendChild(pill);
    });
  }

  function updateRibbonState() {
    appState.questions.forEach((q, idx) => {
      const pill = document.getElementById(`ribbon-pill-${idx}`);
      if (!pill) return;
      pill.classList.remove('active');
      if (idx === appState.currentIndex) pill.classList.add('active');

      if (appState.answers[q.id.toString()] !== undefined) {
        pill.classList.add('answered');
      } else {
        pill.classList.remove('answered');
      }
    });

    // Авто-прокрутка стрічки до активного питання
    const activePill = document.getElementById(`ribbon-pill-${appState.currentIndex}`);
    if (activePill) {
      activePill.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
  }

  function renderQuestion(index) {
    if (index < 0 || index >= appState.questions.length) return;
    appState.currentIndex = index;

    const q = appState.questions[index];
    const total = appState.questions.length;

    // Лічильники
    document.getElementById('current-q-num').innerText = index + 1;
    document.getElementById('total-q-num').innerText = total;

    // Прогрес-бар
    const progressFill = document.getElementById('progress-fill');
    if (progressFill) {
      const pct = Math.round(((index + 1) / total) * 100);
      progressFill.style.width = `${pct}%`;
    }

    // Текст питання та бали
    document.getElementById('question-points-badge').innerText = `${q.points || 1} бал`;
    document.getElementById('question-text').innerText = q.question_text;

    // Варіанти відповідей
    const optionsContainer = document.getElementById('options-list');
    optionsContainer.innerHTML = '';

    const letters = ['А', 'Б', 'В', 'Г'];
    const currentSelected = appState.answers[q.id.toString()];

    q.options.forEach((optText, optIdx) => {
      const optNumber = optIdx + 1; // 1-based
      const item = document.createElement('div');
      item.className = 'option-item';
      if (currentSelected === optNumber) item.classList.add('selected');

      item.innerHTML = `
        <div class="option-letter">${letters[optIdx] || optNumber}</div>
        <div class="option-label">${optText}</div>
      `;

      item.addEventListener('click', () => {
        triggerHaptic('medium');
        // Записуємо відповідь
        appState.answers[q.id.toString()] = optNumber;

        // Оновлюємо стилі вибору
        optionsContainer.querySelectorAll('.option-item').forEach(el => el.classList.remove('selected'));
        item.classList.add('selected');

        updateRibbonState();

        // Авто-перехід до наступного питання через 300мс для драйву (якщо не останнє)
        if (index < total - 1) {
          setTimeout(() => {
            renderQuestion(index + 1);
          }, 320);
        } else {
          updateNavButtons();
        }
      });

      optionsContainer.appendChild(item);
    });

    updateRibbonState();
    updateNavButtons();
  }

  function updateNavButtons() {
    const prevBtn = document.getElementById('btn-prev-question');
    const nextBtn = document.getElementById('btn-next-question');
    const finishBtn = document.getElementById('btn-finish-quiz');
    const total = appState.questions.length;
    const isLast = appState.currentIndex === total - 1;

    if (prevBtn) prevBtn.disabled = appState.currentIndex === 0;

    if (isLast) {
      if (nextBtn) nextBtn.classList.add('hidden');
      if (finishBtn) finishBtn.classList.remove('hidden');
    } else {
      if (nextBtn) nextBtn.classList.remove('hidden');
      if (finishBtn) finishBtn.classList.add('hidden');
    }
  }

  // Обробники навігації
  document.getElementById('btn-prev-question')?.addEventListener('click', () => {
    triggerHaptic('light');
    if (appState.currentIndex > 0) renderQuestion(appState.currentIndex - 1);
  });

  document.getElementById('btn-next-question')?.addEventListener('click', () => {
    triggerHaptic('light');
    if (appState.currentIndex < appState.questions.length - 1) renderQuestion(appState.currentIndex + 1);
  });

  document.getElementById('btn-finish-quiz')?.addEventListener('click', () => {
    triggerHaptic('medium');
    const answeredCount = Object.keys(appState.answers).length;
    const total = appState.questions.length;

    if (answeredCount < total) {
      const confirmUnanswered = confirm(`Ви відповіли на ${answeredCount} з ${total} запитань. Бажаєте завершити зараз?`);
      if (!confirmUnanswered) return;
    }

    submitQuiz(false);
  });

  // ==========================================
  // 3. САБМІТ ТА ФІНІШ ТЕСТУ
  // ==========================================
  async function submitQuiz(isTimeout = false) {
    if (appState.timerInterval) clearInterval(appState.timerInterval);

    showScreen('loading');
    const loaderText = document.querySelector('#screen-loading .loader-text');
    if (loaderText) loaderText.innerText = isTimeout ? 'Час вичерпано! Підрахунок результатів...' : 'Збереження ваших відповідей...';

    try {
      const response = await fetch('/attestation/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          init_data: getTelegramInitData(),
          attempt_id: appState.attemptId,
          answers: appState.answers
        })
      });

      if (!response.ok) {
        throw new Error('Помилка надсилання результатів');
      }

      const resultData = await response.json();
      showCompletedScreen({
        attempt_status: resultData.attempt_status,
        score: resultData.score,
        max_score: resultData.max_score,
        score_pct: resultData.score_pct,
        shop_name: resultData.shop_name,
        role_name: appState.roleName,
        duration_seconds: resultData.duration_seconds
      });
    } catch (e) {
      console.error('Submit error:', e);
      alert("Не вдалося зберегти результати. Перевірте з'єднання з інтернетом.");
      showScreen('quiz');
    }
  }

  // Запуск при завантаженні сторінки (безпечно для iOS WebView)
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

})();
